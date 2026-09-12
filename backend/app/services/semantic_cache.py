"""Semantic (L2) query cache in pgvector.

The Redis CAG cache (L1) only hits when the normalized question text matches
exactly. This layer catches the far more common case of *similar* questions
from different users: each answered question is stored with its embedding, and
a standalone question is served only when similarity clears the threshold AND
the request wording passes a conservative equivalence check. Topic similarity
alone says nothing about whether the user wants code, detail, or a definition.

Everything is best-effort and never raises: a cache problem must degrade to
"just answer normally", not break the query path. Lookup returns the query
vector alongside the hit so a subsequent store() never re-embeds.
"""
import dataclasses
import logging
import math
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Project, SemanticQueryCache
from ..providers import resolver
from ..providers.base import ProviderUnavailableError
from ..providers.registry import get_embedder
from . import agentic
from .query_cache import normalize_question

logger = logging.getLogger(__name__)

# Seven equality columns plus expires_at make this extremely selective: the
# vector ORDER BY runs over the handful of rows left after the scope filter,
# not over the table, and migration 0018 adds a btree on exactly that scope.
# That is also why this table gets NO HNSW index - the planner would rarely
# choose one given these quals, and it is the highest-churn table in the schema
# (one INSERT per cache miss, a bulk DELETE on every store and sweep), so graph
# maintenance would be pure cost.
_LOOKUP_SQL = text(
    """
    SELECT question, result, 1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
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


def _request_identity(question: str) -> str:
    """Allow only small, known wording variations without an extra model call.

    Keep subject order, qualifiers, numbers, negation, identifiers and output
    requests intact. No bag-of-words comparison or fuzzy spelling: those can
    turn a framework/version change into a hit. Unrecognised paraphrases simply
    generate fresh answers, including languages without a known wrapper here.
    """
    question = normalize_question(question)
    question = re.sub(r"^(?:(?:can|could|would) you (?:please )?|please )", "", question)
    question = re.sub(r"[, ]+please$", "", question)
    # These definition requests can share an answer only when the ENTIRE
    # remaining subject/constraints match. Other actions stay literal.
    match = re.fullmatch(r"(?:what is|what are|define|explain|describe|tell me about) (.+)", question)
    if match:
        subject = re.sub(r" to me$", "", match.group(1))
        return "definition:" + subject
    return "literal:" + question


def equivalent_request(question: str, cached_question: str) -> bool:
    return bool(question.strip() and cached_question.strip()) and (
        agentic.detect_depth(question) == agentic.detect_depth(cached_question)
    ) and (
        _request_identity(question) == _request_identity(cached_question)
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
        if row is None:
            return None, vector, None
        score = float(row.similarity)
        if (
            not math.isfinite(score)
            or score < settings.semantic_cache_min_similarity
            or not equivalent_request(question, row.question)
        ):
            return None, vector, None
        result = agentic.AgenticResult(**row.result)
        if result.needs_clarification or not result.answer:
            return None, vector, None
        similarity = round(score, 4)
        logger.info(
            "Semantic cache hit (similarity %.3f) for project %s",
            similarity,
            project.id,
        )
        return result, vector, similarity
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
