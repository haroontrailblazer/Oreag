import dataclasses
import json
import logging
import time
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Chunk, Memory, Project, QueryLog
from ..providers import resolver
from ..providers.base import ProviderUnavailableError
from ..providers.registry import get_llm
from ..schemas import QueryResponse, SourceChunk
from . import agentic
from . import generation
from . import memory as memory_service
from . import query_cache
from . import retrieval
from . import semantic_cache

logger = logging.getLogger(__name__)

# Storage for CAG + conversation memory. Redis when REDIS_URL is set (shared
# across workers, survives restarts), else per-process in-memory. The cache and
# conversation store namespace their keys, so they can share a backend.
_cache_backend = query_cache.make_backend(
    settings.redis_url, max_entries=settings.query_cache_max_entries
)
_conv_backend = query_cache.make_backend(
    settings.redis_url, max_entries=settings.query_cache_max_entries
)


def _serialize_result(result: "agentic.AgenticResult") -> str:
    return json.dumps(dataclasses.asdict(result))


def _deserialize_result(raw: str) -> "agentic.AgenticResult":
    return agentic.AgenticResult(**json.loads(raw))


# CAG cache: repeated questions skip retrieval + the LLM, and simultaneous
# identical asks single-flight through one computation.
_cache = query_cache.QueryCache(
    _cache_backend,
    ttl_seconds=settings.query_cache_ttl_seconds,
    serialize=_serialize_result,
    deserialize=_deserialize_result,
)

# Server-side conversation memory, keyed by conversation_id.
_conversations = query_cache.ConversationStore(
    _conv_backend,
    ttl_seconds=settings.conversation_ttl_seconds,
    max_turns=settings.conversation_max_turns,
)


def run_query(
    db: Session,
    project: Project,
    question: str,
    top_k_override: int | None,
    api_key_id: uuid.UUID | None,
    conversation_id: str | None = None,
) -> QueryResponse:
    """Shared by the dashboard playground and the public /v1 endpoint.

    Answers from the project's "brain": document chunks plus any relevant agent
    memories (both live in the same per-project embedding space). When a
    conversation_id is given, the prior turns are loaded and this question is
    rewritten to be self-contained before retrieval, then the new turn is saved.
    """
    chunk_count = (
        db.scalar(select(func.count()).select_from(Chunk).where(Chunk.project_id == project.id))
        or 0
    )
    memory_count = (
        db.scalar(
            select(func.count())
            .select_from(Memory)
            .where(Memory.project_id == project.id, Memory.embedding.isnot(None))
        )
        or 0
    )
    if not chunk_count and not memory_count:
        raise HTTPException(
            status_code=409,
            detail="Project has no indexed content yet - upload files (or save memories) and wait for indexing",
        )

    top_k = min(top_k_override or project.top_k, 20)
    started = time.perf_counter()

    def retrieve_fn(query: str, k: int) -> list[dict]:
        """One retrieval pass over the brain: document chunks + relevant memories.

        Memories live in the same embedding space, so they're blended per query
        and compete with chunks on similarity for grounding.
        """
        sources = retrieval.retrieve(db, project, query, k) if chunk_count else []
        if memory_count and settings.rag_memory_blend_k > 0:
            try:
                for mem, sim in memory_service.search_memories(
                    db, project, query, settings.rag_memory_blend_k
                ):
                    if sim >= settings.rag_memory_min_similarity:
                        sources.append(
                            {
                                "filename": "memory",
                                "page_number": None,
                                "chunk_index": -1,
                                "content": mem.content,
                                "similarity": sim,
                            }
                        )
            except ProviderUnavailableError:
                pass  # no embedding key for memory search - answer from docs only
            except Exception:
                # Memory blending is an enrichment - it must never take the
                # whole query down (e.g. a stale-dimension vector from before
                # a model switch aborts the transaction with a pgvector
                # "different vector dimensions" error). Roll back so the
                # session is usable again and answer from documents only.
                logger.exception(
                    "Memory blending failed for project %s; answering from "
                    "documents only",
                    project.id,
                )
                db.rollback()
        return sources

    def _llm():
        key = resolver.resolve_llm_key(db, project)
        return get_llm(project.llm_provider, project.llm_model, key)

    # Conversation memory: load prior turns and rewrite a follow-up like
    # "summarize that" into a standalone question before retrieval. Empty history
    # (or no conversation) leaves the question untouched and costs nothing.
    history = _conversations.get_history(conversation_id) if conversation_id else []

    try:
        agentic_question = (
            agentic.condense_question(
                _llm(), history, question, settings.conversation_history_turns
            )
            if history
            else question
        )

        def compute() -> agentic.AgenticResult:
            return agentic.run_agentic_query(
                question=agentic_question,
                retrieve_fn=retrieve_fn,
                plan_fn=lambda q: agentic.plan_subqueries(
                    _llm(), q, settings.agentic_max_subqueries
                ),
                generate_fn=lambda q, srcs, depth: generation.generate_answer(
                    db, project, q, srcs, depth
                ),
                clarify_fn=lambda q: agentic.request_clarification(
                    _llm(), q, settings.agentic_max_clarifying
                ),
                top_k=top_k,
                min_similarity=settings.agentic_min_similarity,
                min_strong=settings.agentic_min_strong,
                max_rounds=settings.agentic_max_rounds,
            )

        # Two cache layers, cheapest first. L1 (Redis/in-memory) hits when the
        # normalized question repeats EXACTLY. L2 (pgvector) hits when a
        # SIMILAR question was already answered - cosine similarity above the
        # threshold reuses the cached answer, below it the query runs for real.
        # Both are scoped by models + top_k + content signature, so new
        # files/memories or a model change can never serve a stale answer.
        signature = f"{chunk_count}:{memory_count}"
        semantic_vector: list[float] | None = None
        cache_layer: str | None = None
        cache_similarity: float | None = None

        def compute_and_remember() -> agentic.AgenticResult:
            fresh = compute()
            semantic_cache.store(
                db, project, agentic_question, top_k, signature, fresh, semantic_vector
            )
            return fresh

        key = (
            query_cache.cache_key(project, agentic_question, top_k, signature)
            if settings.query_cache_enabled
            else None
        )
        result = _cache.get(key) if key is not None else None
        if result is not None:
            cache_layer = "l1"
        else:
            hit, semantic_vector, cache_similarity = semantic_cache.lookup(
                db, project, agentic_question, top_k, signature
            )
            if hit is not None:
                result = hit
                cache_layer = "l2"
                if key is not None:
                    _cache.set(key, hit)  # promote to the exact-match L1
            elif key is not None:
                # single-flight: simultaneous identical asks compute once
                result = _cache.get_or_compute(key, compute_and_remember)
            else:
                result = compute_and_remember()
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    latency_ms = int((time.perf_counter() - started) * 1000)

    db.add(
        QueryLog(
            project_id=project.id,
            api_key_id=api_key_id,
            question=question,
            top_k=top_k,
            latency_ms=latency_ms,
        )
    )
    db.commit()

    answer = (
        agentic.clarification_message(result.clarification_questions)
        if result.needs_clarification
        else result.answer
    )

    # Remember this turn (the original question the user typed, plus the answer)
    # so the next follow-up has context.
    if conversation_id:
        _conversations.append_turn(conversation_id, question, answer)

    return QueryResponse(
        answer=answer,
        sources=[SourceChunk(**s) for s in result.sources],
        model=f"{project.llm_provider}/{project.llm_model}",
        latency_ms=latency_ms,
        depth=result.depth,
        sub_queries=result.sub_queries,
        needs_clarification=result.needs_clarification,
        clarification_questions=result.clarification_questions,
        conversation_id=conversation_id,
        cache_layer=cache_layer,
        cache_similarity=cache_similarity,
    )
