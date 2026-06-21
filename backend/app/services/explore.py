"""Agentic, graph-aware retrieval over the project's "brain".

Flat RAG returns top-k chunks. This instead *seeds* on the chunks and memories
most similar to the query, then walks their `related` links outward a few hops,
returning a connected subgraph (nodes carry their text) for an agent to reason
over and traverse. Document chunks and saved memories share the project's
embedding space, so both are first-class nodes and link to each other.

All neighbour expansion references each node's stored embedding by id (no vector
round-trips), and the whole walk is bounded by a node budget.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Project
from ..providers import resolver
from ..providers.base import ProviderUnavailableError
from ..providers.registry import get_embedder
from ..schemas import MemoryGraphEdge, MemoryGraphNode

# Seeds: nearest chunks / memories to the query vector.
_SEED_CHUNK_SQL = text(
    """
    SELECT c.id, c.content, c.page_number, c.chunk_index, f.filename,
           1 - (c.embedding <=> CAST(:qvec AS vector)) AS similarity
    FROM chunks c JOIN files f ON f.id = c.file_id
    WHERE c.project_id = :pid
    ORDER BY c.embedding <=> CAST(:qvec AS vector)
    LIMIT :k
    """
)
_SEED_MEMORY_SQL = text(
    """
    SELECT id, content, tags, pinned, source,
           1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
    FROM memories
    WHERE project_id = :pid AND embedding IS NOT NULL
    ORDER BY embedding <=> CAST(:qvec AS vector)
    LIMIT :k
    """
)

# Neighbours: nearest nodes to a given node, by that node's stored embedding.
_CHUNK_REL_CHUNK_SQL = text(
    """
    SELECT c.id, c.content, c.page_number, c.chunk_index, f.filename,
           1 - (c.embedding <=> x.embedding) AS similarity
    FROM chunks x JOIN chunks c ON c.project_id = x.project_id AND c.id <> x.id
    JOIN files f ON f.id = c.file_id
    WHERE x.id = :id AND x.project_id = :pid
    ORDER BY c.embedding <=> x.embedding
    LIMIT :k
    """
)
_CHUNK_REL_MEMORY_SQL = text(
    """
    SELECT m.id, m.content, m.tags, m.pinned, m.source,
           1 - (m.embedding <=> x.embedding) AS similarity
    FROM chunks x JOIN memories m
      ON m.project_id = x.project_id AND m.embedding IS NOT NULL
    WHERE x.id = :id AND x.project_id = :pid
    ORDER BY m.embedding <=> x.embedding
    LIMIT :k
    """
)
_MEMORY_REL_CHUNK_SQL = text(
    """
    SELECT c.id, c.content, c.page_number, c.chunk_index, f.filename,
           1 - (c.embedding <=> x.embedding) AS similarity
    FROM memories x JOIN chunks c ON c.project_id = x.project_id
    JOIN files f ON f.id = c.file_id
    WHERE x.id = :id AND x.project_id = :pid AND x.embedding IS NOT NULL
    ORDER BY c.embedding <=> x.embedding
    LIMIT :k
    """
)
_MEMORY_REL_MEMORY_SQL = text(
    """
    SELECT m.id, m.content, m.tags, m.pinned, m.source,
           1 - (m.embedding <=> x.embedding) AS similarity
    FROM memories x JOIN memories m
      ON m.project_id = x.project_id AND m.id <> x.id AND m.embedding IS NOT NULL
    WHERE x.id = :id AND x.project_id = :pid AND x.embedding IS NOT NULL
    ORDER BY m.embedding <=> x.embedding
    LIMIT :k
    """
)


def _chunk_node(row) -> MemoryGraphNode:
    return MemoryGraphNode(
        id=f"chunk:{int(row['id'])}",
        type="chunk",
        label=f"{row['filename']} / chunk {row['chunk_index']}",
        text=row["content"],
        metadata={
            "filename": row["filename"],
            "page_number": row["page_number"],
            "chunk_index": row["chunk_index"],
            "similarity": round(float(row["similarity"]), 4),
        },
    )


def _memory_node(row) -> MemoryGraphNode:
    label = " ".join((row["content"] or "").split())
    return MemoryGraphNode(
        id=f"memory:{int(row['id'])}",
        type="memory",
        label=(label[:60] + "…") if len(label) > 60 else (label or "(memory)"),
        text=row["content"],
        metadata={
            "tags": list(row["tags"] or []),
            "pinned": row["pinned"],
            "source": row["source"],
            "similarity": round(float(row["similarity"]), 4),
        },
    )


def _neighbours(db: Session, project: Project, node_id: str, k: int):
    kind, raw = node_id.split(":", 1)
    params = {"id": int(raw), "pid": str(project.id), "k": k}
    out: list[tuple[MemoryGraphNode, float]] = []
    if kind == "chunk":
        for row in db.execute(_CHUNK_REL_CHUNK_SQL, params).mappings():
            out.append((_chunk_node(row), float(row["similarity"])))
        for row in db.execute(_CHUNK_REL_MEMORY_SQL, params).mappings():
            out.append((_memory_node(row), float(row["similarity"])))
    else:
        for row in db.execute(_MEMORY_REL_CHUNK_SQL, params).mappings():
            out.append((_chunk_node(row), float(row["similarity"])))
        for row in db.execute(_MEMORY_REL_MEMORY_SQL, params).mappings():
            out.append((_memory_node(row), float(row["similarity"])))
    return out


def explore_brain(
    db: Session, project: Project, query: str, hops: int
) -> tuple[list[str], list[MemoryGraphNode], list[MemoryGraphEdge]]:
    key = resolver.resolve_embedding_key(db, project)
    if resolver.requires_key(project.embedding_provider) and not key:
        raise ProviderUnavailableError(
            "Brain exploration needs an embedding key. Add one in Settings → API keys."
        )
    embedder = get_embedder(project.embedding_provider, project.embedding_model, key)
    qvec = "[" + ",".join(repr(v) for v in embedder.embed_query(query)) + "]"

    max_nodes = settings.explore_max_nodes
    fanout = settings.explore_fanout
    seeds_per_type = settings.explore_seeds_per_type

    nodes: dict[str, MemoryGraphNode] = {}
    edges: list[MemoryGraphEdge] = []
    edge_seen: set[tuple[str, str]] = set()

    def add_node(node: MemoryGraphNode) -> bool:
        if node.id in nodes:
            return True
        if len(nodes) >= max_nodes:
            return False
        nodes[node.id] = node
        return True

    def add_edge(src: str, dst: str, sim: float) -> None:
        pair = (src, dst) if src < dst else (dst, src)
        if pair in edge_seen or src == dst:
            return
        edge_seen.add(pair)
        edges.append(
            MemoryGraphEdge(
                source=src, target=dst, type="related",
                metadata={"similarity": round(sim, 4)},
            )
        )

    seeds: list[str] = []
    seed_params = {"qvec": qvec, "pid": str(project.id), "k": seeds_per_type}
    for row in db.execute(_SEED_CHUNK_SQL, seed_params).mappings():
        node = _chunk_node(row)
        if add_node(node):
            seeds.append(node.id)
    for row in db.execute(_SEED_MEMORY_SQL, seed_params).mappings():
        node = _memory_node(row)
        if add_node(node):
            seeds.append(node.id)

    frontier = list(seeds)
    for _ in range(max(0, hops)):
        if len(nodes) >= max_nodes:
            break
        nxt: list[str] = []
        for node_id in frontier:
            if len(nodes) >= max_nodes:
                break
            for neighbour, sim in _neighbours(db, project, node_id, fanout):
                existed = neighbour.id in nodes
                if add_node(neighbour):
                    add_edge(node_id, neighbour.id, sim)
                    if not existed:
                        nxt.append(neighbour.id)
        frontier = nxt

    return seeds, list(nodes.values()), edges
