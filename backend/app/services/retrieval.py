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
"""
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Project
from ..providers import resolver
from ..providers.registry import get_embedder

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

    semantic = [dict(row) for row in db.execute(SEMANTIC_SQL, params).mappings()]

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
