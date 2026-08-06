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
from ..providers import registry
from ..providers.registry import (
    embed_batch_size,
    get_embedder,
    prefix_normalize,
)
from ..schemas import MemoryCreate
from . import retrieval
from .content_version import bump_content_version

logger = logging.getLogger(__name__)


def _embed_many(
    db: Session, project: Project, texts: list[str]
) -> list[tuple[list[float], list[float] | None]] | None:
    """Embed several texts in as FEW provider calls as possible.

    One request per provider batch, not one per text. Splitting a long memory
    used to embed each piece on its own: a 6000-character memory cost 21
    sequential HTTPS round trips inside a single API request, all of them with
    the caller's DB transaction already open. That is seconds of blocked request
    and a connection pinned across every one of those calls, and it scaled with
    memory length - exactly the case the splitting exists to support.
    ingestion.py has batched from the start; this is the same rule.

    Returns None (not a partial list) if no key is available or the provider
    fails, so callers get one unambiguous "could not embed" answer.
    """
    key = resolver.resolve_embedding_key(db, project)
    if resolver.requires_key(project.embedding_provider) and not key:
        return None
    if not texts:
        return []
    active_dims = project.embedding_dimensions
    # Resolved through the registry rather than read straight off the project:
    # a model switch can leave embedding_native_dimensions pointing at a width
    # the current model rejects, and get_embedder RAISES on that - which the
    # except below would swallow into "no embedding", silently, on every write.
    native_dims = (
        registry.usable_native_dimensions(
            project.embedding_provider,
            project.embedding_model,
            project.embedding_native_dimensions,
            active_dims,
        )
        if active_dims
        else active_dims
    )
    # embedding_dimensions is NOT NULL in the schema, but a Project constructed
    # in memory rather than loaded can still carry None, and `None > None` is a
    # TypeError - which would fail the entire memory save over a comparison
    # whose only job is to decide whether to bank an archive.
    archiving = bool(native_dims and active_dims and native_dims > active_dims)
    try:
        embedder = get_embedder(
            project.embedding_provider,
            project.embedding_model,
            key,
            dimensions=native_dims,
        )
        # Respect the provider's own comfortable request size - hosted APIs take
        # large batches, local Ollama prefers small ones. A memory splits into at
        # most ~20 pieces, so this is usually a single request either way.
        size = embed_batch_size(embedder)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), size):
            vectors.extend(embedder.embed_texts(texts[start : start + size]))
    except Exception:
        logger.exception("Memory embedding failed; storing without embedding")
        return None
    if len(vectors) != len(texts):
        # A provider that drops or duplicates rows would silently pair a piece
        # with another piece's vector - worse than no embedding, because it
        # retrieves confidently and wrongly.
        logger.error(
            "Embedder returned %d vectors for %d texts; storing without embedding",
            len(vectors),
            len(texts),
        )
        return None
    if not archiving:
        return [(v, None) for v in vectors]
    return [(prefix_normalize(v, active_dims), v) for v in vectors]


def _embed(
    db: Session, project: Project, content: str
) -> tuple[list[float], list[float] | None] | None:
    """Best-effort embedding of ONE memory, as (stored_vector, archive_or_None).

    Thin wrapper over _embed_many so the batching, the native-width resolution
    and the archive rule cannot drift between the single and multi cases.

    Returns None if no key / on failure.

    While a project is SHRUNK this embeds at the project's NATIVE width and
    returns the wide vector as the archive, storing only the re-normalised
    prefix - exactly what ingestion.py:350-366 does for file chunks, and for
    exactly the same reason.

    Without it, a memory written while shrunk has no wide numbers anywhere, so
    growing back cannot restore it: _RESTORE_MEMORIES_SQL skips it (the archive
    is NULL), the follow-up statement nulls its vector because the width no
    longer matches, and _DROP_UNRESTORABLE_MEMORY_CHUNKS_SQL deletes its pieces.
    The memory text survives, unsearchable, and nothing reports it.

    It is FREE: embedding APIs bill per TOKEN, not per dimension, so asking for
    3072 costs exactly what asking for 1536 costs.
    """
    out = _embed_many(db, project, [content])
    return out[0] if out else None


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
                embedded = _embed(db, project, memory.content)
                # Never write a None over an existing vector: _embed returns
                # None when no key is available, and on the restore path that
                # would erase a memory that had just been correctly restored.
                if embedded is not None:
                    memory.embedding, archive = embedded
                    if archive is not None:
                        memory.embedding_full = archive
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
    embedded = _embed(db, project, body.content)
    memory = Memory(
        project_id=project.id,
        content=body.content,
        tags=body.tags,
        pinned=body.pinned,
        source=body.source,
        embedding=embedded[0] if embedded else None,
    )
    # Only ASSIGNED when there is something to archive, never set to None.
    # Same rule as the chunk INSERT in ingestion.py: naming the column makes
    # SQLAlchemy emit it, which fails on a database without migration 0024.
    if embedded and embedded[1] is not None:
        memory.embedding_full = embedded[1]
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
    # ONE batched call for every piece. Per-piece calls made a long memory cost
    # a round trip per paragraph, serially, inside the request.
    vectors = _embed_many(db, project, pieces)
    if not vectors:
        return 0  # no embedding key or a provider failure - the parent serves it
    # Uniform across the batch: `archiving` is a property of the PROJECT, not of
    # a piece, so either every row carries an archive or none does. That matters
    # because SQLAlchemy's executemany requires every dict to have the same
    # keys - a per-row conditional would split the INSERT or raise.
    archiving = any(archive is not None for _, archive in vectors)
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
            rows = [
                {
                    "memory_id": memory.id,
                    "project_id": project.id,
                    "chunk_index": index,
                    "content": piece,
                    "embedding": vector,
                }
                for index, (piece, (vector, _archive)) in enumerate(
                    zip(pieces, vectors)
                )
            ]
            if archiving:
                # OMITTED, not None, when there is nothing to archive - naming
                # the column makes SQLAlchemy emit it, which fails on a database
                # without migration 0024/0025.
                for row, (_vector, archive) in zip(rows, vectors):
                    row["embedding_full"] = archive
            db.execute(insert(MemoryChunk), rows)
        return len(pieces)
    except Exception:
        logger.exception(
            "Could not split memory %s into chunks - falling back to its single "
            "whole-content vector",
            memory.id,
        )
        return 0


# Deliberately an exact scan, with no HNSW index behind it (migration 0018
# indexes `chunks` ONLY - neither `memories` nor `memory_chunks` has one, and
# this query never consults the ANN gate in retrieval.py, so memory search is
# exact at every size). PERFECT recall, which the graph edges and the answer
# blend both depend on.
#
# The old justification here was "max_memories_per_project caps this at 2000
# rows". That bound DIED when the union below was added, and the number is worth
# writing down rather than re-deriving: a memory can be 8000 characters, which
# splits into 20 pieces, so the worst case is 2000 * 20 = 40,000 memory_chunks
# rows - twenty times the stated cap, and double the 20,000 (vector_ann_min_
# chunks) at which file chunks were judged to need an index.
#
# It is still the right call TODAY, on different grounds: real projects hold
# tens of pieces, not tens of thousands, and a global HNSW index would have to
# post-filter by project_id across every tenant, where a capped per-project
# share is exactly the case post-filtering handles worst.
#
# Two things must BOTH change before an index would help, and an index alone
# would be dead weight:
#   1. This query computes similarity for every row and then groups. An HNSW
#      index is only chosen when a branch reads `ORDER BY embedding <=> q
#      LIMIT k` with the operand textually matching the index expression, so
#      each side of the union would need its own ordered, limited subquery
#      before being merged - same discipline as 0018's partial indexes.
#   2. pgvector cannot build HNSW above 2000 dimensions, so a 3072-wide project
#      gets an exact scan regardless.
# Revisit when a real project's memory_chunks count reaches four figures.
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


# The indexable sibling of _SEARCH_SQL, used once a project's memory_chunks
# clear the same gate document chunks clear (services/retrieval.py).
#
# Only the PIECES branch is rewritten. `memories` is capped at 2000 rows per
# project, so its exact scan is already small and stays exactly as it is - the
# pieces are the side that grows to five figures, and the side an index helps.
#
# Three things must line up or the planner silently ignores the index and the
# cast is paid for nothing: the ORDER BY left operand must be TEXTUALLY the
# index expression, the WHERE clause must repeat the index predicate verbatim,
# and both must carry the same dimension. MATERIALIZED pins the ANN scan as its
# own node so the outer GROUP BY cannot be pushed under the LIMIT.
#
# WHY THE PIECE LIMIT IS SAFE, and it is not the usual ANN trade-off: the
# parents branch is UNLIMITED, so every memory in the project is already a
# candidate with its own whole-content score. A piece that falls outside the
# limit therefore cannot make its memory disappear - the memory simply ranks on
# its parent vector, which is precisely the pre-0025 behaviour. The limit bounds
# how far down the list the piece-level BOOST reaches, not whether a memory can
# be found at all.
_ANN_SEARCH_TEMPLATE = """
    WITH pieces AS MATERIALIZED (
        SELECT memory_id AS id,
               1 - (embedding::vector({dim}) <=> CAST(:qvec AS vector({dim})))
                 AS similarity
        FROM memory_chunks
        WHERE project_id = :project_id
          AND vector_dims(embedding) = {dim}
        ORDER BY embedding::vector({dim}) <=> CAST(:qvec AS vector({dim}))
        LIMIT :piece_limit
    )
    SELECT id, MAX(similarity) AS similarity FROM (
        SELECT id, 1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
        FROM memories
        WHERE project_id = :project_id AND embedding IS NOT NULL
        UNION ALL
        SELECT id, similarity FROM pieces
    ) scored
    GROUP BY id
    ORDER BY similarity DESC
    LIMIT :top_k
    """

# The most pieces ONE memory can split into: the 8000-character content cap
# divided by the stride (size - overlap). The piece branch is oversampled by
# this factor so that even if the nearest pieces all belong to a single long
# memory, top_k DISTINCT memories can still receive a piece-level score. Derived
# from the constants rather than written as a literal, so changing the chunk
# size cannot silently invalidate it.
MAX_PIECES_PER_MEMORY = -(-8000 // (MEMORY_CHUNK_SIZE - MEMORY_CHUNK_OVERLAP))

_ann_sql_cache: dict[int, object] = {}


def _ann_search_sql(dim: int):
    stmt = _ann_sql_cache.get(dim)
    if stmt is None:
        # Rendered through retrieval.build_ann_sql, NOT str.format here: the
        # dimension is part of a TYPE and cannot be a bind parameter, so that
        # helper's ANN_DIMENSIONS allowlist is the injection guard as well as
        # the correctness one. Returns None for anything not on it.
        stmt = retrieval.build_ann_sql(_ANN_SEARCH_TEMPLATE, dim)
        if stmt is None:
            return None
        _ann_sql_cache[dim] = stmt
    return stmt


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
    params = {"qvec": qvec, "project_id": str(project.id), "top_k": top_k}

    # ANN only once this project's PIECES clear the same gate document chunks
    # clear. Fails closed at every step, including apply_ann_gucs: without
    # hnsw.iterative_scan a post-filtered HNSW scan stops after ef_search
    # candidates and returns however few survived the project_id filter, so an
    # un-tuned ANN run is worse than no ANN at all.
    statement = _SEARCH_SQL
    dim = retrieval.memory_ann_dimension(db, project)
    if dim is not None:
        ann = _ann_search_sql(dim)
        if ann is not None and retrieval.apply_ann_gucs(db):
            statement = ann
            params["piece_limit"] = top_k * MAX_PIECES_PER_MEMORY

    rows = db.execute(statement, params).all()
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
