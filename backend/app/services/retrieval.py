"""Hybrid retrieval over a project's chunks.

Two searches run per query and their rankings are fused:

  * semantic - pgvector cosine over embeddings; matches MEANING, so a question
    phrased nothing like the document still finds it;
  * lexical  - Postgres full-text over ``content_tsv``; matches EXACT terms
    (error codes, part numbers, names) that embeddings fumble.

Fusion is Reciprocal Rank Fusion (RRF): only each chunk's positions in the two
lists matter (the engines' raw scores aren't comparable), so a chunk found by
both engines outranks one found by a single engine at similar positions. Rows
keep their cosine ``similarity`` value - the agentic loop's grounding
thresholds and the UI's "match %" depend on it; RRF decides only the ORDER.

This sits strictly BELOW the answer caches: L1 (Redis, exact question) and L2
(pgvector, similar question) intercept repeated questions before retrieval is
ever called, and nothing here touches their keys or flow. If the lexical
column is missing (migration 0012 not applied yet), retrieval degrades to
semantic-only instead of failing.

This module also owns the ANN (HNSW) planner - see "approximate nearest
neighbour planning" below - because the rules for routing a chunk vector
search onto an index belong next to the SQL they govern. services/explore.py
imports the gate from here rather than duplicating it.
"""
import logging
import re
import threading
import time
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Project
from ..providers import resolver
from ..providers.registry import get_embedder
from . import query_cache

logger = logging.getLogger(__name__)

# Standard RRF damping: rank 1 scores 1/61, rank 10 scores 1/70 - steep enough
# to reward top ranks, flat enough that a #1 in one engine beats a #8 in both.
RRF_K = 60

SEMANTIC_SQL = text(
    """
    SELECT c.id, c.content, c.page_number, c.chunk_index, f.filename,
           1 - (c.embedding <=> CAST(:qvec AS vector)) AS similarity
    FROM chunks c
    JOIN files f ON f.id = c.file_id
    WHERE c.project_id = :project_id
    ORDER BY c.embedding <=> CAST(:qvec AS vector)
    LIMIT :limit
    """
)

# websearch_to_tsquery is forgiving of raw user input (plain words, "quoted
# phrases", OR). Cosine similarity is still selected so lexical-only hits
# carry a meaningful `similarity` downstream.
LEXICAL_SQL = text(
    """
    SELECT c.id, c.content, c.page_number, c.chunk_index, f.filename,
           1 - (c.embedding <=> CAST(:qvec AS vector)) AS similarity
    FROM chunks c
    JOIN files f ON f.id = c.file_id
    WHERE c.project_id = :project_id
      AND c.content_tsv @@ websearch_to_tsquery('simple', :question)
    ORDER BY ts_rank_cd(c.content_tsv, websearch_to_tsquery('simple', :question)) DESC
    LIMIT :limit
    """
)


# ── approximate nearest neighbour (HNSW) planning ───────────────────────────
#
# `chunks.embedding` is a DIMENSIONLESS `vector`, so one table holds every
# project's dimension and no plain HNSW index is possible. Migration 0018 adds
# one PARTIAL index per dimension instead
# (`chunks_embedding_hnsw_<d>_idx ... where vector_dims(embedding) = <d>`).
#
# Routing a query onto those indexes is a DECISION, not a default. Every vector
# statement here is `WHERE project_id = X ORDER BY embedding <=> q LIMIT k`, and
# a global HNSW index knows nothing about project_id, so it must POST-FILTER.
# Post-filter recall depends on the project's SHARE of the indexed rows; the
# exact scan's cost depends on the project's absolute SIZE. A small project
# inside a big table therefore gets an exact scan that is both fast AND
# perfect, while ANN would burn its candidate budget on other tenants' rows;
# a project big enough to need ANN is usually also a large enough share of the
# table for ANN to be safe. So the ANN path opens only when FOUR gates pass,
# and SEMANTIC_SQL / LEXICAL_SQL above stay the default, unchanged.
#
# The gate fails CLOSED on anything unexpected - no pgvector, an old pgvector,
# a missing or invalid index, an unknown dimension, a probe error. Correctness
# never depends on an index existing: the rewritten SQL is the same computation
# expressed so the planner CAN use one, and without it Postgres just scans.

# Dimensions with a partial HNSW index in migration 0018. 3072 is absent on
# purpose: pgvector's HNSW limit is 2000 dimensions for `vector`, and the
# halfvec workaround would change the distance arithmetic and therefore the
# `similarity` value the agentic thresholds and the UI depend on.
ANN_DIMENSIONS = frozenset({256, 384, 512, 768, 1024, 1536})

ANN_INDEX_PREFIX = "chunks_embedding_hnsw_"
_ANN_INDEX_RE = re.compile(rf"^{ANN_INDEX_PREFIX}(\d+)_idx$")

# How long a per-(project, content_version) chunk count is reused. Per process
# and NOT Redis: this is only a gate input, cheap to recompute, and a network
# round trip to decide whether to use an index would defeat the point.
ANN_SIZE_CACHE_TTL_SECONDS = 600


def ann_index_name(dim: int) -> str:
    return f"{ANN_INDEX_PREFIX}{dim}_idx"


def _is_ann_dimension(dim) -> bool:
    return isinstance(dim, int) and not isinstance(dim, bool) and dim in ANN_DIMENSIONS


@dataclass(frozen=True)
class AnnCapability:
    """What the server can actually do, as of the last probe."""

    pgvector: tuple[int, int, int]
    dimensions: frozenset[int]   # dimensions with a VALID hnsw index
    total_chunks: float          # pg_class.reltuples for public.chunks


NO_ANN = AnnCapability(pgvector=(0, 0, 0), dimensions=frozenset(), total_chunks=0.0)

# One round trip answers all three questions. Every read is a catalog lookup
# (no table scan), and `to_regclass` returns NULL instead of raising when
# public.chunks is absent, so the statement itself cannot fail on a live
# server. `indisvalid` matters: a CREATE INDEX CONCURRENTLY that failed leaves
# an index that is never used for reads but IS maintained on writes, and
# treating it as absent is exactly right.
_CAPABILITY_SQL = text(
    """
    SELECT (SELECT extversion FROM pg_extension WHERE extname = 'vector')
             AS vector_version,
           (SELECT coalesce(array_agg(c.relname::text), ARRAY[]::text[])
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_index i ON i.indexrelid = c.oid
             WHERE n.nspname = 'public'
               AND strpos(c.relname::text, 'chunks_embedding_hnsw_') = 1
               AND i.indisvalid) AS hnsw_indexes,
           (SELECT c.reltuples FROM pg_class c
             WHERE c.oid = to_regclass('public.chunks')) AS chunk_reltuples
    """
)

# `files` is capped at 1000 rows per project, and this is the same number the
# projects router already reports.
_PROJECT_CHUNKS_SQL = text(
    "SELECT coalesce(sum(chunk_count), 0) FROM files WHERE project_id = :pid"
)

# set_config(name, value, is_local => true) IS `SET LOCAL`: it reverts at the
# end of the current transaction and so cannot leak across the shared pool onto
# whichever request borrows this connection next. `SET` itself takes no bind
# parameters, which is also why set_config is used - the values come from
# settings with no string interpolation anywhere. One round trip sets all
# three, and it must be re-issued after any commit or rollback (both reset
# LOCAL settings), so callers apply it immediately before the ANN statement.
_ANN_GUCS_SQL = text(
    "SELECT set_config('hnsw.iterative_scan', :mode, true), "
    "set_config('hnsw.ef_search', :ef_search, true), "
    "set_config('hnsw.max_scan_tuples', :max_scan_tuples, true)"
)

_ANN_SEMANTIC_TEMPLATE = """
    WITH nn AS MATERIALIZED (
        SELECT c.id, c.content, c.page_number, c.chunk_index, c.file_id,
               c.embedding::vector({dim}) <=> CAST(:qvec AS vector({dim})) AS distance
        FROM chunks c
        WHERE c.project_id = :project_id
          AND vector_dims(c.embedding) = {dim}
        ORDER BY c.embedding::vector({dim}) <=> CAST(:qvec AS vector({dim}))
        LIMIT :limit
    )
    SELECT nn.id, nn.content, nn.page_number, nn.chunk_index, f.filename,
           1 - nn.distance AS similarity
    FROM nn JOIN files f ON f.id = nn.file_id
    ORDER BY nn.distance
    """

_capability_guard = threading.Lock()
_capability_cache: tuple[float, AnnCapability] | None = None
_ann_size_cache = query_cache.InMemoryBackend(max_entries=256)
_ann_sql_cache: dict[int, object] = {}


def reset_ann_caches() -> None:
    """Forget the capability probe and the per-project size memo.

    Both are refreshed on their own TTL in normal operation; this exists for
    tests and for an operator who has just built (or dropped) an index and does
    not want to wait out vector_ann_capability_ttl_seconds.
    """
    global _capability_cache
    with _capability_guard:
        _capability_cache = None
    _ann_size_cache.clear()


def build_ann_sql(template: str, dim: int | None):
    """Render an ANN statement for `dim`, or None to take the exact path.

    The dimension is part of a TYPE, so it cannot be a bind parameter - it is
    interpolated. Membership of the frozen ANN_DIMENSIONS allowlist is
    therefore both the correctness guard (an index exists for it) and the
    injection guard (it is one of six known ints). The isinstance check is not
    redundant: `1536.0 in ANN_DIMENSIONS` is True in Python, and it would
    render `::vector(1536.0)`.
    """
    if not _is_ann_dimension(dim):
        return None
    return text(template.format(dim=dim))


def ann_semantic_sql(dim: int | None):
    """The indexable sibling of SEMANTIC_SQL, cached per dimension.

    Same columns in the same order, same bind parameters, same ordering
    (distance ascending), and the same `1 - distance` similarity arithmetic, so
    rrf_merge and every downstream threshold see exactly what they see today.
    Three things must line up or the planner silently ignores the index and we
    pay for the cast for nothing: the ORDER BY left operand must be TEXTUALLY
    the index expression, the WHERE clause must repeat the index predicate
    verbatim, and both must carry the same dimension. `MATERIALIZED` pins the
    ANN scan as its own node so the planner cannot pull the `files` join under
    the LIMIT; the join is on a NOT NULL FK, so hoisting it above the LIMIT
    cannot change the row set.
    """
    if not _is_ann_dimension(dim):
        return None
    stmt = _ann_sql_cache.get(dim)
    if stmt is None:
        stmt = build_ann_sql(_ANN_SEMANTIC_TEMPLATE, dim)
        _ann_sql_cache[dim] = stmt
    return stmt


def _parse_pgvector_version(raw) -> tuple[int, int, int]:
    parts = re.findall(r"\d+", str(raw or ""))[:3]
    parts += ["0"] * (3 - len(parts))
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def _indexed_dimensions(names) -> frozenset[int]:
    found = set()
    for name in names or ():
        match = _ANN_INDEX_RE.match(str(name))
        if match and int(match.group(1)) in ANN_DIMENSIONS:
            found.add(int(match.group(1)))
    return frozenset(found)


def ann_capability(db: Session) -> AnnCapability:
    """Probe (and memoize) what this server supports.

    Cached for vector_ann_capability_ttl_seconds so a newly built index takes
    effect without a restart and a dropped one closes the gate within the same
    window. The probe runs inside a SAVEPOINT on the session's own connection:
    a statement error would otherwise abort the caller's read transaction and
    take the real query down with it, which is a far worse failure than not
    using an index. Any exception - including a session that cannot hand out a
    Core connection - reports "no ANN" without consuming a statement.
    """
    global _capability_cache
    now = time.monotonic()
    with _capability_guard:
        cached = _capability_cache
    if cached is not None and now < cached[0]:
        return cached[1]

    capability = NO_ANN
    try:
        connection = db.connection()
        with connection.begin_nested():
            row = connection.execute(_CAPABILITY_SQL).mappings().first()
        if row is not None:
            capability = AnnCapability(
                pgvector=_parse_pgvector_version(row["vector_version"]),
                dimensions=_indexed_dimensions(row["hnsw_indexes"]),
                total_chunks=float(row["chunk_reltuples"] or 0.0),
            )
    except Exception:
        logger.debug(
            "HNSW capability probe unavailable; using exact vector search",
            exc_info=True,
        )

    with _capability_guard:
        _capability_cache = (
            now + settings.vector_ann_capability_ttl_seconds,
            capability,
        )
    return capability


def _project_chunk_count(db: Session, project: Project) -> int:
    """This project's chunk total, memoized on its content_version.

    Self-invalidating: any content write bumps content_version, so this is at
    most one cheap query per content version per process. Same SAVEPOINT
    protection and same fail-closed rule as the capability probe - an
    unanswerable question means 0, which closes the gate.
    """
    key = f"annsize:{project.id}:v{project.content_version}"
    cached = _ann_size_cache.get(key)
    if cached is not None:
        try:
            return int(cached)
        except (TypeError, ValueError):
            pass
    try:
        connection = db.connection()
        with connection.begin_nested():
            total = connection.execute(
                _PROJECT_CHUNKS_SQL, {"pid": str(project.id)}
            ).scalar()
    except Exception:
        logger.debug(
            "Project chunk count unavailable; using exact vector search",
            exc_info=True,
        )
        return 0
    count = int(total or 0)
    _ann_size_cache.set(key, str(count), ANN_SIZE_CACHE_TTL_SECONDS)
    return count


def ann_dimension(db: Session, project: Project) -> int | None:
    """The dimension to run ANN at, or None to use the exact SQL.

    Ordered cheapest-first, and every DB-touching gate sits behind the local
    ones so a closed gate costs nothing.
    """
    if not settings.vector_ann_enabled:
        return None
    dim = project.embedding_dimensions
    if not _is_ann_dimension(dim):
        return None
    capability = ann_capability(db)
    # hnsw.iterative_scan landed in 0.8.0. Without it a post-filtered HNSW scan
    # stops after ef_search candidates and silently returns however few
    # survived the project_id filter, and on some builds setting an unknown GUC
    # aborts the transaction outright. Neither is acceptable, so below 0.8 we
    # never emit the ANN SQL at all.
    if capability.pgvector < (0, 8, 0):
        return None
    if dim not in capability.dimensions:
        return None
    total = capability.total_chunks
    if total <= 0:   # reltuples is -1 until the table is analyzed: unknown
        return None
    owned = _project_chunk_count(db, project)
    if owned < settings.vector_ann_min_chunks:
        return None
    share = owned / total
    if share < settings.vector_ann_min_project_share:
        return None
    logger.debug(
        "retrieval_path=ann project=%s dim=%s chunks=%s share=%.4f",
        project.id, dim, owned, share,
    )
    return dim


def apply_ann_gucs(db: Session) -> bool:
    """Set the HNSW scan settings for the CURRENT transaction only.

    `relaxed_order` rather than `strict_order`: the rewritten SQL already
    re-sorts its (at most top_k) rows in an outer ORDER BY, so we get strict
    ordering at relaxed cost. Failure closes the gate for this call - and rolls
    back, because a failed statement leaves the transaction unusable and the
    exact query still has to run.
    """
    try:
        db.execute(
            _ANN_GUCS_SQL,
            {
                "mode": settings.vector_ann_iterative_scan,
                "ef_search": str(settings.vector_ann_ef_search),
                "max_scan_tuples": str(settings.vector_ann_max_scan_tuples),
            },
        )
        return True
    except Exception:
        logger.warning(
            "Could not set HNSW scan settings; using exact vector search",
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return False


def ann_plan(db: Session, project: Project) -> int | None:
    """Decide the path AND prepare the transaction for it.

    Returns the dimension to build ANN statements for, or None for the exact
    path. Callers must treat None as "use today's SQL"; nothing downstream may
    depend on a non-None answer.
    """
    dim = ann_dimension(db, project)
    if dim is None:
        return None
    if not apply_ann_gucs(db):
        return None
    return dim


def rrf_merge(
    semantic: list[dict], lexical: list[dict], top_k: int, k: int = RRF_K
) -> list[dict]:
    """Fuse two ranked lists by Reciprocal Rank Fusion, capped at top_k.

    Identity is the chunk ``id`` (stripped from the returned payloads - the
    rest of the pipeline expects exactly the SourceChunk fields).
    """
    scores: dict[int, float] = {}
    payloads: dict[int, dict] = {}
    for rows in (semantic, lexical):
        for rank, row in enumerate(rows, start=1):
            rid = row["id"]
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank)
            payloads.setdefault(rid, row)
    ranked = sorted(scores, key=lambda rid: scores[rid], reverse=True)[:top_k]
    out: list[dict] = []
    for rid in ranked:
        row = dict(payloads[rid])
        row.pop("id", None)
        out.append(row)
    return out


def retrieve(
    db: Session,
    project: Project,
    question: str,
    top_k: int,
    embed_fn=None,
) -> list[dict]:
    # query.py passes its per-request memoized embedder as ``embed_fn`` so the
    # same string is never embedded twice in one request (each embed is a
    # blocking provider round-trip). Standalone callers omit it and embedding
    # is resolved here as before.
    if embed_fn is None:
        api_key = resolver.resolve_embedding_key(db, project)
        embedder = get_embedder(
            project.embedding_provider,
            project.embedding_model,
            api_key,
            dimensions=project.embedding_dimensions,
        )
        query_vector = embedder.embed_query(question)
    else:
        query_vector = embed_fn(question)
    qvec = "[" + ",".join(repr(v) for v in query_vector) + "]"
    params = {"qvec": qvec, "project_id": str(project.id), "limit": top_k}

    # Exact by default. The ANN sibling is used only when every gate passes,
    # and it returns the same columns, the same ordering and the same
    # `similarity` arithmetic - so rrf_merge and the grounding thresholds
    # cannot tell the two apart except by which rows the scan reached.
    # (`or` is not usable here: a TextClause raises on __bool__.)
    semantic_sql = ann_semantic_sql(ann_plan(db, project))
    if semantic_sql is None:
        semantic_sql = SEMANTIC_SQL
    semantic = [dict(row) for row in db.execute(semantic_sql, params).mappings()]

    lexical: list[dict] = []
    if settings.hybrid_search_enabled:
        try:
            lexical = [
                dict(row)
                for row in db.execute(
                    LEXICAL_SQL, {**params, "question": question}
                ).mappings()
            ]
        except Exception:
            # e.g. content_tsv missing (migration 0012 not applied) - degrade
            # to semantic-only rather than failing the query. Roll back so the
            # aborted transaction doesn't poison later statements.
            logger.warning(
                "Lexical search unavailable; using semantic-only retrieval",
                exc_info=True,
            )
            db.rollback()

    return rrf_merge(semantic, lexical, top_k)
