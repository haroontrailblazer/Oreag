import logging
import re
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Chunk, File, Memory, Project
from ..schemas import MemoryGraphEdge, MemoryGraphNode, MemoryGraphResponse, ProjectInfo
from . import query_cache, storage

logger = logging.getLogger(__name__)

# The graph is derived data that only changes when content changes - cache the
# built response per (project, content_version) so repeat calls between
# ingests are free instead of re-walking every file and chunk. Small entry
# cap: graph JSON can run to megabytes.
_graph_cache = query_cache.make_backend(settings.redis_url, max_entries=8)
GRAPH_CACHE_TTL_SECONDS = 600

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

# Cross-file topic linking knobs.
RELATED_K = 5               # nearest cross-file neighbours considered per chunk
RELATED_THRESHOLD = 0.6     # min cosine similarity for a "related" edge
RELATED_MAX_EDGES = 600     # safety cap on emitted chunk pairs
RELATED_CHUNK_CAP = 1500    # skip the heavy pass for very large projects

# Memory linking knobs - connect memories to chunks and to each other.
MEMORY_RELATED_K = 5
MEMORY_RELATED_THRESHOLD = 0.6
MEMORY_RELATED_MAX_EDGES = 400
MEMORY_CAP = 1000           # skip the memory linking pass above this many memories

# For every chunk, find its nearest chunks that live in a *different* file of the
# same project (exact cosine scan - every project's chunks share one embedding
# dimension, so the operator is well defined). Returns candidate pairs with the
# creation times needed to orient each edge from the newer file back to the older.
RELATED_SQL = text(
    """
    SELECT a.id AS source_id, a.file_id AS source_file, a.created_at AS source_created,
           n.id AS target_id, n.file_id AS target_file, n.created_at AS target_created,
           1 - (a.embedding <=> n.embedding) AS similarity
    FROM chunks a
    CROSS JOIN LATERAL (
        SELECT c.id, c.file_id, c.embedding, c.created_at
        FROM chunks c
        WHERE c.project_id = a.project_id
          AND c.file_id <> a.file_id
        ORDER BY c.embedding <=> a.embedding
        LIMIT :k
    ) n
    WHERE a.project_id = :project_id
      AND (1 - (a.embedding <=> n.embedding)) >= :threshold
    ORDER BY similarity DESC
    LIMIT :max_edges
    """
)


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    level: int
    start: int
    end: int


def _load_markdown(file: File) -> str:
    if not file.markdown_storage_path:
        return ""
    try:
        return storage.download(file.markdown_storage_path).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _sections(markdown: str, file_id: str) -> list[Section]:
    matches = list(HEADING_RE.finditer(markdown))
    sections: list[Section] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append(
            Section(
                id=f"section:{file_id}:{index}",
                title=match.group(2).strip(),
                level=len(match.group(1)),
                start=match.start(),
                end=end,
            )
        )
    return sections


def _chunk_position(markdown: str, content: str, cursor: int) -> tuple[int, int]:
    probe = content.strip()
    if not probe:
        return -1, cursor
    probe = probe[: min(len(probe), 160)]
    found = markdown.find(probe, cursor)
    if found == -1:
        found = markdown.find(probe)
    return found, found if found >= 0 else cursor


def _section_for_position(sections: list[Section], position: int) -> Section | None:
    if position < 0:
        return None
    for section in sections:
        if section.start <= position < section.end:
            return section
    return None


def _related_edges(
    db: Session, project: Project, chunk_count: int
) -> list[MemoryGraphEdge]:
    """Connect chunks (and the files that own them) whose embeddings are most
    similar across different documents, so shared topics join up in the graph.

    Each undirected pair is emitted exactly once (collision-free) and oriented
    from the newer file back to the related older one.
    """
    if chunk_count < 2 or chunk_count > RELATED_CHUNK_CAP:
        return []

    rows = (
        db.execute(
            RELATED_SQL,
            {
                "project_id": str(project.id),
                "k": RELATED_K,
                "threshold": RELATED_THRESHOLD,
                "max_edges": RELATED_MAX_EDGES,
            },
        )
        .mappings()
        .all()
    )

    seen: set[tuple[int, int]] = set()
    chunk_edges: list[MemoryGraphEdge] = []
    # file pair (sorted) -> [count, similarity_sum, newer_file, older_file]
    file_pairs: dict[tuple[str, str], list] = {}

    for row in rows:
        a_id, b_id = int(row["source_id"]), int(row["target_id"])
        if a_id == b_id:
            continue
        pair = (a_id, b_id) if a_id < b_id else (b_id, a_id)
        if pair in seen:
            continue
        seen.add(pair)
        sim = round(float(row["similarity"]), 4)

        # orient newer -> older ("recent file joins back to the related topic")
        if row["source_created"] >= row["target_created"]:
            newer, older = a_id, b_id
            newer_file, older_file = str(row["source_file"]), str(row["target_file"])
        else:
            newer, older = b_id, a_id
            newer_file, older_file = str(row["target_file"]), str(row["source_file"])

        chunk_edges.append(
            MemoryGraphEdge(
                source=f"chunk:{newer}",
                target=f"chunk:{older}",
                type="related",
                metadata={"similarity": sim},
            )
        )

        fkey = tuple(sorted((newer_file, older_file)))
        agg = file_pairs.setdefault(fkey, [0, 0.0, newer_file, older_file])
        agg[0] += 1
        agg[1] += sim

    file_edges = [
        MemoryGraphEdge(
            source=f"file:{newer_file}",
            target=f"file:{older_file}",
            type="related",
            metadata={
                "shared_topics": count,
                "avg_similarity": round(total / count, 4),
            },
        )
        for count, total, newer_file, older_file in file_pairs.values()
    ]
    # files first (high-level joins), then the underlying topic links
    return file_edges + chunk_edges


# Memories share the project's embedding space with chunks, so the same cosine
# operator links a memory to its nearest document chunks and to its nearest other
# memories - weaving the saved session memory into the document graph.
MEMORY_CHUNK_SQL = text(
    """
    SELECT m.id AS mem_id, c.id AS chunk_id,
           1 - (m.embedding <=> c.embedding) AS similarity
    FROM memories m
    CROSS JOIN LATERAL (
        SELECT id, embedding FROM chunks
        WHERE project_id = m.project_id
        ORDER BY embedding <=> m.embedding
        LIMIT :k
    ) c
    WHERE m.project_id = :project_id AND m.embedding IS NOT NULL
      AND (1 - (m.embedding <=> c.embedding)) >= :threshold
    ORDER BY similarity DESC
    LIMIT :max_edges
    """
)

MEMORY_MEMORY_SQL = text(
    """
    SELECT a.id AS a_id, n.id AS b_id,
           1 - (a.embedding <=> n.embedding) AS similarity
    FROM memories a
    CROSS JOIN LATERAL (
        SELECT id, embedding FROM memories
        WHERE project_id = a.project_id AND id <> a.id
        ORDER BY embedding <=> a.embedding
        LIMIT :k
    ) n
    WHERE a.project_id = :project_id AND a.embedding IS NOT NULL
      AND (1 - (a.embedding <=> n.embedding)) >= :threshold
    ORDER BY similarity DESC
    LIMIT :max_edges
    """
)


def _memory_related_edges(
    db: Session, project: Project, memory_count: int, chunk_count: int
) -> list[MemoryGraphEdge]:
    if memory_count < 1 or memory_count > MEMORY_CAP:
        return []

    params = {
        "project_id": str(project.id),
        "k": MEMORY_RELATED_K,
        "threshold": MEMORY_RELATED_THRESHOLD,
        "max_edges": MEMORY_RELATED_MAX_EDGES,
    }
    edges: list[MemoryGraphEdge] = []

    if chunk_count:
        for row in db.execute(MEMORY_CHUNK_SQL, params).mappings().all():
            edges.append(
                MemoryGraphEdge(
                    source=f"memory:{int(row['mem_id'])}",
                    target=f"chunk:{int(row['chunk_id'])}",
                    type="related",
                    metadata={"similarity": round(float(row["similarity"]), 4)},
                )
            )

    seen: set[tuple[int, int]] = set()
    for row in db.execute(MEMORY_MEMORY_SQL, params).mappings().all():
        a, b = int(row["a_id"]), int(row["b_id"])
        if a == b:
            continue
        pair = (a, b) if a < b else (b, a)
        if pair in seen:
            continue
        seen.add(pair)
        edges.append(
            MemoryGraphEdge(
                source=f"memory:{pair[0]}",
                target=f"memory:{pair[1]}",
                type="related",
                metadata={"similarity": round(float(row["similarity"]), 4)},
            )
        )
    return edges


def build_memory_graph(db: Session, project: Project) -> MemoryGraphResponse:
    cache_key = f"graph:{project.id}:v{project.content_version}"
    cached = _graph_cache.get(cache_key)
    if isinstance(cached, str):
        try:
            return MemoryGraphResponse.model_validate_json(cached)
        except Exception:  # schema drift - rebuild
            pass

    response = _build_memory_graph(db, project)

    try:
        _graph_cache.set(cache_key, response.model_dump_json(), GRAPH_CACHE_TTL_SECONDS)
    except Exception:  # cache write is best-effort (e.g. value too large)
        logger.warning("Memory-graph cache write failed", exc_info=True)
    return response


def _build_memory_graph(db: Session, project: Project) -> MemoryGraphResponse:
    files = db.scalars(
        select(File).where(File.project_id == project.id).order_by(File.created_at)
    ).all()
    file_count = len(files)
    nodes: list[MemoryGraphNode] = [
        MemoryGraphNode(
            id=f"project:{project.id}",
            type="project",
            label=project.name,
            metadata={
                "project_id": str(project.id),
                "status": project.status,
                "file_count": file_count,
            },
        )
    ]
    edges: list[MemoryGraphEdge] = []

    # ONE project-scoped query for every file's chunks, selecting only the
    # columns the graph uses. The old per-file SELECT * was an N+1 that also
    # shipped each chunk's full embedding vector (tens of KB per row, never
    # used here) over the wire - 1000 files meant 1000 queries of dead weight.
    chunks_by_file: dict = defaultdict(list)
    chunk_rows = db.execute(
        select(
            Chunk.id,
            Chunk.file_id,
            Chunk.chunk_index,
            Chunk.page_number,
            Chunk.content,
        )
        .where(Chunk.project_id == project.id)
        .order_by(Chunk.file_id, Chunk.chunk_index)
    ).all()
    for row in chunk_rows:
        chunks_by_file[row.file_id].append(row)

    for file in files:
        file_node_id = f"file:{file.id}"
        nodes.append(
            MemoryGraphNode(
                id=file_node_id,
                type="file",
                label=file.filename,
                metadata={
                    "file_id": str(file.id),
                    "filename": file.filename,
                    "content_type": file.content_type,
                    "source_extension": file.source_extension,
                    "size_bytes": file.size_bytes,
                    "page_count": file.page_count,
                    "chunk_count": file.chunk_count,
                    "status": file.status,
                    "markdown_available": bool(file.markdown_storage_path),
                },
            )
        )
        edges.append(
            MemoryGraphEdge(
                source=f"project:{project.id}",
                target=file_node_id,
                type="contains",
            )
        )

        markdown = _load_markdown(file)
        sections = _sections(markdown, str(file.id))
        for section in sections:
            nodes.append(
                MemoryGraphNode(
                    id=section.id,
                    type="section",
                    label=section.title,
                    text=markdown[section.start : section.end].strip() or None,
                    metadata={
                        "file_id": str(file.id),
                        "level": section.level,
                    },
                )
            )
            edges.append(
                MemoryGraphEdge(source=file_node_id, target=section.id, type="contains")
            )

        chunks = chunks_by_file.get(file.id, [])
        cursor = 0
        previous_chunk_node_id: str | None = None
        for chunk in chunks:
            chunk_node_id = f"chunk:{chunk.id}"
            position, cursor = _chunk_position(markdown, chunk.content, cursor)
            section = _section_for_position(sections, position)
            nodes.append(
                MemoryGraphNode(
                    id=chunk_node_id,
                    type="chunk",
                    label=f"{file.filename} / chunk {chunk.chunk_index}",
                    text=chunk.content,
                    metadata={
                        "chunk_id": chunk.id,
                        "project_id": str(project.id),
                        "file_id": str(file.id),
                        "filename": file.filename,
                        "chunk_index": chunk.chunk_index,
                        "page_number": chunk.page_number,
                        "section_id": section.id if section else None,
                        "section_title": section.title if section else None,
                    },
                )
            )
            edges.append(
                MemoryGraphEdge(
                    source=section.id if section else file_node_id,
                    target=chunk_node_id,
                    type="contains",
                )
            )
            edges.append(
                MemoryGraphEdge(source=chunk_node_id, target=file_node_id, type="derived_from")
            )
            if previous_chunk_node_id is not None:
                edges.append(
                    MemoryGraphEdge(
                        source=previous_chunk_node_id,
                        target=chunk_node_id,
                        type="next",
                    )
                )
            previous_chunk_node_id = chunk_node_id

    chunk_count = db.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.project_id == project.id)
    )

    # cross-file topic links (auto-detected related nodes)
    edges.extend(_related_edges(db, project, chunk_count or 0))

    # memories as nodes, woven into the same interlinked brain
    memories = db.scalars(
        select(Memory).where(Memory.project_id == project.id).order_by(Memory.created_at)
    ).all()
    for mem in memories:
        label = " ".join((mem.content or "").split())
        nodes.append(
            MemoryGraphNode(
                id=f"memory:{mem.id}",
                type="memory",
                label=(label[:60] + "…") if len(label) > 60 else (label or "(memory)"),
                text=mem.content,
                metadata={
                    "memory_id": mem.id,
                    "tags": list(mem.tags or []),
                    "pinned": mem.pinned,
                    "source": mem.source,
                },
            )
        )
        edges.append(
            MemoryGraphEdge(
                source=f"project:{project.id}", target=f"memory:{mem.id}", type="contains"
            )
        )
    edges.extend(_memory_related_edges(db, project, len(memories), chunk_count or 0))

    project_info = ProjectInfo(
        id=project.id,
        name=project.name,
        status=project.status,
        file_count=file_count,
        chunk_count=chunk_count or 0,
    )
    return MemoryGraphResponse(project=project_info, nodes=nodes, edges=edges)
