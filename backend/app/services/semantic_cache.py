"""Semantic (L2) query cache in pgvector.

The Redis CAG cache (L1) only hits when the normalized question text matches
exactly. This layer catches the far more common case of *similar* questions
from different users: each answered question is stored with its embedding, and
a new question is served from cache when its cosine similarity to a cached one
clears ``settings.semantic_cache_min_similarity``; below the threshold the
query runs for real.

Everything is best-effort and never raises: a cache problem must degrade to
"just answer normally", not break the query path. Lookup returns the query
vector alongside the hit so a subsequent store() never re-embeds.
"""
import dataclasses
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Project, SemanticQueryCache
from ..providers import resolver
from ..providers.base import ProviderUnavailableError
from ..providers.registry import get_embedder
from . import agentic

logger = logging.getLogger(__name__)

_LOOKUP_SQL = text(
    """
    SELECT result, 1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
    FROM semantic_query_cache
    WHERE project_id = :project_id
      AND content_signature = :signature
      AND embedding_provider = :embedding_provider
      AND embedding_model = :embedding_model
      AND llm_provider = :llm_provider
      AND llm_model = :llm_model
      AND top_k = :top_k
      AND expires_at > now()
    ORDER BY embedding <=> CAST(:qvec AS vector)
    LIMIT 1
    """
)


def _embed_question(db: Session, project: Project, question: str) -> list[float] | None:
    key = resolver.resolve_embedding_key(db, project)
    if resolver.requires_key(project.embedding_provider) and not key:
        return None
    embedder = get_embedder(
        project.embedding_provider,
        project.embedding_model,
        key,
        dimensions=project.embedding_dimensions,
    )
    return embedder.embed_query(question)


def lookup(
    db: Session,
    project: Project,
    question: str,
    top_k: int,
    signature: str,
    embed_fn=None,
) -> tuple["agentic.AgenticResult | None", list[float] | None, float | None]:
    """Return (cached result, the question's embedding, hit similarity).

    The embedding comes back even on a miss so store() never re-embeds; the
    similarity comes back only on a hit (for response transparency). query.py
    passes its per-request memoized embedder as ``embed_fn`` so this embed is
    shared with retrieval instead of being a separate provider round-trip.
    """
    if not settings.semantic_cache_enabled:
        return None, None, None
    try:
        try:
            vector = (
                embed_fn(question) if embed_fn else _embed_question(db, project, question)
            )
        except ProviderUnavailableError:
            # No usable embedding key - same graceful miss `_embed_question`
            # signals with None; retrieval will surface the real 503 later.
            vector = None
        if vector is None:
            return None, None, None
        qvec = "[" + ",".join(repr(v) for v in vector) + "]"
        row = db.execute(
            _LOOKUP_SQL,
            {
                "qvec": qvec,
                "project_id": str(project.id),
                "signature": signature,
                "embedding_provider": project.embedding_provider,
                "embedding_model": project.embedding_model,
                "llm_provider": project.llm_provider,
                "llm_model": project.llm_model,
                "top_k": top_k,
            },
        ).first()
        if row is None or float(row.similarity) < settings.semantic_cache_min_similarity:
            return None, vector, None
        similarity = round(float(row.similarity), 4)
        logger.info(
            "Semantic cache hit (similarity %.3f) for project %s",
            similarity,
            project.id,
        )
        return agentic.AgenticResult(**row.result), vector, similarity
    except Exception:
        logger.exception("Semantic cache lookup failed; answering normally")
        db.rollback()
        return None, None, None


def store(
    db: Session,
    project: Project,
    question: str,
    top_k: int,
    signature: str,
    result: "agentic.AgenticResult",
    vector: list[float] | None,
) -> None:
    """Remember a freshly computed answer (skips clarification results)."""
    if not settings.semantic_cache_enabled or result.needs_clarification:
        return
    try:
        if vector is None:
            vector = _embed_question(db, project, question)
            if vector is None:
                return
        now = datetime.now(timezone.utc)
        db.add(
            SemanticQueryCache(
                project_id=project.id,
                question=question,
                embedding=vector,
                content_signature=signature,
                embedding_provider=project.embedding_provider,
                embedding_model=project.embedding_model,
                llm_provider=project.llm_provider,
                llm_model=project.llm_model,
                top_k=top_k,
                result=dataclasses.asdict(result),
                expires_at=now + timedelta(seconds=settings.semantic_cache_ttl_seconds),
            )
        )
        # lazy housekeeping: drop this project's expired rows on the way through
        db.execute(
            text(
                "DELETE FROM semantic_query_cache "
                "WHERE project_id = :project_id AND expires_at <= now()"
            ),
            {"project_id": str(project.id)},
        )
        db.commit()
    except Exception:
        logger.exception("Semantic cache store failed; answer already served")
        db.rollback()
