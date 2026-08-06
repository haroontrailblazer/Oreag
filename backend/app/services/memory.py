import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import Memory, MemoryChunk, Project
from ..providers import resolver
from ..providers.base import ProviderUnavailableError
from ..providers.registry import get_embedder
from ..schemas import MemoryCreate
from .content_version import bump_content_version

logger = logging.getLogger(__name__)


def _embed(db: Session, project: Project, content: str) -> list[float] | None:
    """Best-effort embedding of a memory. Returns None if no key / on failure."""
    key = resolver.resolve_embedding_key(db, project)
    if resolver.requires_key(project.embedding_provider) and not key:
        return None
    try:
        embedder = get_embedder(
            project.embedding_provider,
            project.embedding_model,
            key,
            dimensions=project.embedding_dimensions,
        )
        return embedder.embed_texts([content])[0]
    except Exception:
        logger.exception("Memory embedding failed; storing without embedding")
        return None


def reembed_project_memories(
    project_id: uuid.UUID, only_missing: bool = False
) -> None:
    """Background task: re-embed memories with the project's CURRENT model.

    Runs after an embedding model switch - old-model memory vectors live in an
    incompatible space (the caller nulls them out first so search never mixes
    spaces). Best-effort per memory: a failure leaves that one unembedded
    rather than aborting the rest. Owns its DB session (threadpool task).

    only_missing=True restricts it to rows with NO embedding. Required by the
    archive-restore path: that path has just put correct vectors back from the
    archive, and re-embedding everything would spend money to overwrite exactly
    the vectors it was called to preserve. The default stays False because a
    model switch genuinely does need to replace them all.
    """
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if project is None:
            return
        memories = db.scalars(
            select(Memory).where(Memory.project_id == project_id)
        ).all()
        # Which memories already hold their split pieces. Read once for the
        # project rather than per memory - the cap is 2000 rows, so this is one
        # small index scan instead of 2000 COUNT queries.
        chunked = _memories_with_chunks(db, project_id) if only_missing else set()
        touched = 0
        for memory in memories:
            reembed = memory.embedding is None or not only_missing
            if reembed:
                vector = _embed(db, project, memory.content)
                # Never write a None over an existing vector: _embed returns
                # None when no key is available, and on the restore path that
                # would erase a memory that had just been correctly restored.
                if vector is not None or memory.embedding is None:
                    memory.embedding = vector
                touched += 1
            elif memory.id in chunked:
                # Parent restored from the archive AND its pieces came back with
                # it - nothing to do, and re-embedding would spend money to
                # overwrite exactly the vectors this path exists to preserve.
                continue
            # The pieces live in the same vector space as the parent, so a model
            # switch invalidates them too. Rebuilt rather than left stale: a
            # piece embedded with the OLD model would still be scored against
            # new-model queries and could outrank a correct result.
            #
            # Reached on the only_missing path as well, for a memory whose
            # parent restored but whose pieces the archive could not reach and
            # which were therefore dropped. Skipping it there would leave that
            # memory permanently reduced to its single diluted vector, with
            # nothing to ever notice - and it doubles as the backfill for
            # memories written before migration 0025, which have no pieces yet.
            if memory.embedding is not None:
                _rebuild_memory_chunks(db, project, memory)
        bump_content_version(db, project_id)
        db.commit()
        logger.info(
            "Re-embedded %d/%d memories for project %s with %s/%s",
            touched,
            len(memories),
            project_id,
            project.embedding_provider,
            project.embedding_model,
        )
    except Exception:
        logger.exception("Memory re-embedding failed for project %s", project_id)
        db.rollback()
    finally:
        db.close()


def save_memory(db: Session, project: Project, body: MemoryCreate) -> Memory:
    # Memories were the one uncapped content type (files stop at 1000/project);
    # without this, any key could grow the table and embedding spend forever.
    count = (
        db.scalar(
            select(func.count())
            .select_from(Memory)
            .where(Memory.project_id == project.id)
        )
        or 0
    )
    if count >= settings.max_memories_per_project:
        raise HTTPException(
            413,
            f"Project memory limit reached (max {settings.max_memories_per_project}). "
            "Delete old memories to add new ones.",
        )
    memory = Memory(
        project_id=project.id,
        content=body.content,
        tags=body.tags,
        pinned=body.pinned,
        source=body.source,
        embedding=_embed(db, project, body.content),
    )
    db.add(memory)
    db.flush()  # assign memory.id for the chunk rows below
    _rebuild_memory_chunks(db, project, memory)
    bump_content_version(db, project.id)
    db.commit()
    db.refresh(memory)
    return memory


# Roughly a paragraph. Small enough that one piece carries one idea - which is
# the entire point, since an embedding averages whatever it is given - and large
# enough that a normal short memory still fits in a single piece and therefore
# produces no rows at all. The overlap keeps a sentence spanning a boundary
# findable from either side.
MEMORY_CHUNK_SIZE = 480
MEMORY_CHUNK_OVERLAP = 80


def split_memory_content(content: str) -> list[str]:
    """The pieces a memory should be embedded as.

    Returns a SINGLE-ITEM list for anything short enough to be one coherent
    vector, and callers skip writing chunk rows in that case - the parent's own
    embedding already serves it, so the common case costs nothing.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    text_value = content.strip()
    if len(text_value) <= MEMORY_CHUNK_SIZE:
        return [text_value]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=MEMORY_CHUNK_SIZE, chunk_overlap=MEMORY_CHUNK_OVERLAP
    )
    return [p for p in splitter.split_text(text_value) if p.strip()] or [text_value]


def _memories_with_chunks(db: Session, project_id: uuid.UUID) -> set[int]:
    """Ids of memories that currently hold their split pieces.

    Empty set on a database without migration 0025, which is the safe direction:
    every memory then looks unchunked, so the caller rebuilds, and the rebuild
    is itself a no-op savepoint on such a database.
    """
    try:
        with db.begin_nested():
            return set(
                db.scalars(
                    select(MemoryChunk.memory_id)
                    .where(MemoryChunk.project_id == project_id)
                    .distinct()
                )
            )
    except Exception:
        return set()


def _rebuild_memory_chunks(db: Session, project: Project, memory: Memory) -> int:
    """Re-create this memory's chunk rows. Returns how many were written.

    Best-effort by design: the parent's own embedding is always present, so a
    failure here degrades to exactly today's behaviour (one diluted vector for a
    long memory) rather than losing the memory. That also covers a database
    without migration 0025, where the table simply does not exist yet.
    """
    pieces = split_memory_content(memory.content)
    if len(pieces) < 2:
        return 0  # one coherent vector already - the parent's
    vectors = []
    for piece in pieces:
        vector = _embed(db, project, piece)
        if vector is None:
            return 0  # no embedding key - leave it to the parent vector
        vectors.append(vector)
    try:
        # SAVEPOINT, not a bare try/except. Postgres aborts the WHOLE
        # transaction on a statement error, so on a database without migration
        # 0025 the DELETE below would poison the caller's transaction and the
        # memory save itself would fail on commit - catching the exception is
        # not enough to undo that. A nested transaction confines the damage to
        # the chunk work, leaving the parent memory to commit normally.
        with db.begin_nested():
            db.execute(
                sql_delete(MemoryChunk).where(MemoryChunk.memory_id == memory.id)
            )
            db.execute(
                insert(MemoryChunk),
                [
                    {
                        "memory_id": memory.id,
                        "project_id": project.id,
                        "chunk_index": index,
                        "content": piece,
                        "embedding": vector,
                    }
                    for index, (piece, vector) in enumerate(zip(pieces, vectors))
                ],
            )
        return len(pieces)
    except Exception:
        logger.exception(
            "Could not split memory %s into chunks - falling back to its single "
            "whole-content vector",
            memory.id,
        )
        return 0


# Deliberately an exact scan, with no HNSW index behind it (migration 0018
# indexes `chunks` only). max_memories_per_project caps this at 2000 rows per
# project and memories_project_idx bounds the scan to those, so it is tens of
# milliseconds with PERFECT recall. A global HNSW index would have to
# post-filter by project_id across every tenant, and because the per-project
# row count is capped the project's share of the table is guaranteed tiny -
# exactly where post-filtering collapses. It would be strictly worse on both
# axes. Revisit only if that cap moves by an order of magnitude.
#
# Scores the whole-memory vector AND the split pieces of long ones, then keeps
# the BEST score per memory. A memory can therefore be found either by its
# overall gist or by one specific passage inside it - which is the whole reason
# the pieces exist, since a single vector over 8000 characters describes none of
# them well.
#
# MAX, not sum or average: a memory that answers the question in one paragraph
# should rank on that paragraph. Averaging would penalise exactly the long
# memories this exists to rescue, by diluting the good score with the unrelated
# parts - reproducing the original bug one layer up.
#
# The LEFT-JOIN-free UNION means a database without migration 0025 still works:
# the memory_chunks branch simply returns nothing.
_SEARCH_SQL = text(
    """
    SELECT id, MAX(similarity) AS similarity FROM (
        SELECT id, 1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
        FROM memories
        WHERE project_id = :project_id AND embedding IS NOT NULL
        UNION ALL
        SELECT memory_id AS id,
               1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
        FROM memory_chunks
        WHERE project_id = :project_id AND embedding IS NOT NULL
    ) scored
    GROUP BY id
    ORDER BY similarity DESC
    LIMIT :top_k
    """
)


def search_memories(
    db: Session,
    project: Project,
    query: str,
    top_k: int,
    embed_fn=None,
) -> list[tuple[Memory, float]]:
    # Chunks and memories share the project's embedding space, so query.py
    # passes its per-request memoized embedder as ``embed_fn`` - the vector
    # computed for chunk retrieval is reused here instead of paying a second
    # identical provider round-trip. Standalone callers omit it.
    if embed_fn is None:
        key = resolver.resolve_embedding_key(db, project)
        if resolver.requires_key(project.embedding_provider) and not key:
            raise ProviderUnavailableError(
                "Memory search needs an embedding key. Add one in Settings → API keys."
            )
        embedder = get_embedder(
            project.embedding_provider,
            project.embedding_model,
            key,
            dimensions=project.embedding_dimensions,
        )
        query_vector = embedder.embed_query(query)
    else:
        query_vector = embed_fn(query)
    qvec = "[" + ",".join(repr(v) for v in query_vector) + "]"
    rows = db.execute(
        _SEARCH_SQL, {"qvec": qvec, "project_id": str(project.id), "top_k": top_k}
    ).all()
    by_id = {
        m.id: m
        for m in db.scalars(select(Memory).where(Memory.id.in_([r.id for r in rows])))
    }
    return [(by_id[r.id], round(float(r.similarity), 4)) for r in rows if r.id in by_id]


def recent_memories(db: Session, project: Project, limit: int) -> list[Memory]:
    return list(
        db.scalars(
            select(Memory)
            .where(Memory.project_id == project.id)
            .order_by(Memory.pinned.desc(), Memory.created_at.desc())
            .limit(limit)
        )
    )
