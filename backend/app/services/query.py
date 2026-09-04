import dataclasses
import hashlib
import json
import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Chunk, Memory, Project, QueryLog
from ..providers import resolver
from . import embedding_usage
from ..providers.base import (
    ProviderUnavailableError,
    TokenUsage,
    is_provider_rate_limit,
)
from ..providers.registry import get_embedder, get_llm
from ..schemas import QueryResponse, SourceChunk
from . import agentic
from . import cross_lingual
from . import generation
from . import memory as memory_service
from . import query_cache
from . import retrieval
from . import semantic_cache
from .tracing import observed_generate

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

# Server-side conversation memory, keyed by (project_id, conversation_id).
_conversations = query_cache.ConversationStore(
    _conv_backend,
    ttl_seconds=settings.conversation_ttl_seconds,
    max_turns=settings.conversation_max_turns,
)


def _request_helpers(db: Session, project: Project):
    """Per-request memoization for provider work.

    One uncached query used to re-resolve keys (a provider_keys SELECT each
    time) and re-embed the same strings up to 3x (L2 lookup, chunk retrieval,
    memory search - all in the same embedding space), each a blocking provider
    round-trip. Returns:

      * ``embed_memo`` - {query string: vector}; seed it with vectors already
        computed elsewhere (e.g. the semantic-cache lookup).
      * ``embed_query`` - embeds through the memo, resolving the embedding key
        and building the embedder at most once.
      * ``llm`` - the project's LLM, key resolved at most once.
    """
    embed_memo: dict[str, list[float]] = {}
    _embedder: list = []
    _llm_instance: list = []

    def embed_query(query: str) -> list[float]:
        vector = embed_memo.get(query)
        if vector is None:
            if not _embedder:
                key = resolver.resolve_embedding_key(db, project)
                _embedder.append(
                    get_embedder(
                        project.embedding_provider,
                        project.embedding_model,
                        key,
                        dimensions=project.embedding_dimensions,
                    )
                )
            vector = _embedder[0].embed_query(query)
            embed_memo[query] = vector
        return vector

    def llm():
        if not _llm_instance:
            key = resolver.resolve_llm_key(db, project)
            _llm_instance.append(get_llm(project.llm_provider, project.llm_model, key))
        return _llm_instance[0]

    return embed_memo, embed_query, llm


def _llm_step(db: Session, llm_fn, call):
    """Run a step that is nothing but a provider round-trip, holding no
    connection while it waits.

    ``llm_fn`` resolves the project's LLM key first (one SELECT, memoized per
    request); after that condense / plan / clarify only talk to the provider.
    The connection goes back to the pool in between and the session checks a
    fresh one out on its next statement - see ``generation.release_connection``
    for the measured semantics.
    """
    llm = llm_fn()
    generation.release_connection(db)
    return call(llm)


class _UsageAccumulator:
    """Sums the TokenUsage of every LLM call made while serving one request.

    Pure metering, so it must never be able to fail the request: add() eats its
    own exceptions, and a broken accumulator just means a NULL token count. The
    running total keeps TokenUsage.__add__ semantics - an unmeasured call never
    erases a measured one, and nothing measured stays None, never 0.
    """

    __slots__ = ("total",)

    def __init__(self) -> None:
        self.total = TokenUsage()

    def add(self, usage) -> None:
        try:
            if usage is not None:
                self.total = self.total + usage
        except Exception:  # pragma: no cover - defensive
            logger.debug("Token usage accumulation failed", exc_info=True)


class _FanoutUsage:
    """One .add() fanned out to several accumulators.

    The compute phase feeds two totals at once: the REQUEST total (what this
    request spent, condense included) and the per-result subtotal (what a
    future cache hit will have saved, which travels with the cached answer).
    """

    __slots__ = ("_accs",)

    def __init__(self, *accs: _UsageAccumulator) -> None:
        self._accs = accs

    def add(self, usage) -> None:
        for acc in self._accs:
            acc.add(usage)


class _TrackedLLM:
    """Wraps a provider so plain ``.generate()`` calls report their tokens.

    agentic.condense/plan/clarify call ``llm.generate(...)`` and expect a str -
    that contract stays. The wrapper routes the call through observed_generate
    (a Langfuse generation span + TokenUsage, both fail-open) and feeds the
    usage to the request's accumulator, so all up-to-3 LLM calls of one query
    sum into a single billing figure instead of only the final generation.
    """

    __slots__ = ("_inner", "_name", "_acc")

    def __init__(self, inner, name: str, acc) -> None:
        self._inner = inner
        self._name = name
        self._acc = acc

    @property
    def model(self) -> str:
        return getattr(self._inner, "model", "") or ""

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        text, usage = observed_generate(
            self._inner, system_prompt, user_prompt, name=self._name
        )
        self._acc.add(usage)
        return text


def _mean_similarity(sources) -> float | None:
    """Mean similarity of the sources an answer actually used, or None.

    None - not 0 - when there are no sources (e.g. a clarification): "nothing
    was retrieved" is a different fact from "retrieval matched at 0.0".
    """
    values = [
        s.get("similarity")
        for s in (sources or [])
        if isinstance(s.get("similarity"), (int, float))
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


_CITE_RE = re.compile(r"\[(\d{1,3})\]")


def _grounding_policy(project) -> tuple[float, int]:
    """This project's (min_similarity, min_strong), falling back to the globals.

    Reads defensively rather than as ``project.min_similarity`` for a reason
    that outlives the tests: during a rolling deploy new code runs against a
    database that has not had migration 0032 applied yet, so the attribute is
    absent or None on a row loaded in that window. Falling back to the config
    default there reproduces exactly the pre-0032 behaviour instead of raising
    on every query until the migration lands.

    ``is not None`` and NOT ``or``: 0.0 and 0 are meaningful ("never abstain"),
    and ``or`` would silently swap them for the global default.
    """
    sim = getattr(project, "min_similarity", None)
    strong = getattr(project, "min_strong", None)
    return (
        sim if sim is not None else settings.agentic_min_similarity,
        strong if strong is not None else settings.agentic_min_strong,
    )


def _answer_signature(project, db=None, question: str | None = None) -> str:
    """Everything that changes the ANSWER but not the CONTENT.

    The cache key already covers models, top_k and content_version. The answer
    policy from migration 0032 does not appear there, so without this a project
    that tightens its grounding floor or sets a disclaimer keeps being served
    the answer computed under the old policy - for up to the L2 TTL of 24h.

    Rendered as a compact string rather than new columns: both cache layers
    already compare this one signature for equality, so extending it costs
    nothing and needs no migration on a high-churn table.
    """
    parts = [f"v{project.content_version}"]
    # getattr keeps this working for the lightweight project stand-ins used in
    # tests, which do not carry the 0032 columns.
    sim = getattr(project, "min_similarity", None)
    strong = getattr(project, "min_strong", None)
    lang = getattr(project, "answer_language", None)
    disc = getattr(project, "answer_disclaimer", None)
    if sim is not None:
        parts.append(f"s{sim}")
    if strong is not None:
        parts.append(f"n{strong}")
    if lang:
        parts.append(f"l{lang}")
    if disc:
        # Hashed, not inlined: a 500-char disclaimer would otherwise dominate
        # the key, and only its identity matters here.
        parts.append("d" + hashlib.sha256(disc.encode("utf-8")).hexdigest()[:12])
    # A cross-lingual question is retrieved from a TRANSLATION of itself, so an
    # answer cached before that existed was built from different sources.
    # Marked per-question rather than globally on purpose: a flag on every
    # signature would orphan every project's cache the moment this deployed,
    # trading a stale answer for a stampede. Only the questions whose retrieval
    # actually changes get a new key. `is_active` costs a cached read and no
    # LLM call, and both arguments are optional so the lightweight project
    # stand-ins in tests keep working.
    if db is not None and question:
        try:
            if cross_lingual.is_active(db, project, question):
                parts.append("x1")
        except Exception:  # pragma: no cover - a cache key must never raise
            logger.debug("Cross-lingual cache signature check failed", exc_info=True)
    return "|".join(parts)


def _mark_cited(answer: str | None, sources: list[dict]) -> list[dict]:
    """Flag the sources the answer actually cited as [n].

    ``sources`` is everything the loop retrieved, which is deliberately wider
    than what the answer used. Reporting all of it as "sources" without saying
    which were cited lets a reader assume every one supported the claim.

    Best effort by design: the markers come from model output, so an answer
    that cites nothing simply leaves every flag False - which is itself the
    honest signal, not an error.
    """
    if not sources:
        return sources
    cited: set[int] = set()
    for match in _CITE_RE.finditer(answer or ""):
        idx = int(match.group(1)) - 1  # blocks are numbered from 1
        if 0 <= idx < len(sources):
            cited.add(idx)
    return [{**s, "cited": i in cited} for i, s in enumerate(sources)]


def _fill_usage_out(
    usage_out: dict | None,
    request_usage: _UsageAccumulator,
    cache_layer: str | None,
    result,
    latency_ms: int | None,
) -> None:
    """Expose what this request spent (and what a cache hit saved) to the
    caller, out of band of the public response shape - routers/rag_v1.py
    threads it into record_usage().

    "saved" is only ever the counts persisted WITH the cached answer when it
    was first computed - never an estimate. When the original run was not
    measured (a streamed generation reports nothing), the hit's saving stays
    unreported rather than invented.
    """
    if usage_out is None:
        return
    usage_out["usage"] = request_usage.total
    usage_out["cache_layer"] = cache_layer
    usage_out["latency_ms"] = latency_ms
    if cache_layer is not None and result is not None:
        saved = TokenUsage(
            prompt_tokens=result.gen_prompt_tokens,
            completion_tokens=result.gen_completion_tokens,
            # Carries the model so record_usage can price the saving exactly.
            # getattr, not attribute access: entries cached before this field
            # existed deserialize without it.
            model=getattr(result, "gen_model", None) or "",
        )
        if saved.known:
            usage_out["saved"] = saved



def _in_embedding_scope(acc, fn):
    """Run `fn` on another thread inside the caller's embedding accumulator.

    See services/embedding_usage.adopt - the accumulator has to be re-entered
    explicitly, because a copied context would tally into a copy the request
    thread never reads.
    """
    def wrapper(*args, **kwargs):
        with embedding_usage.adopt(acc):
            return fn(*args, **kwargs)

    return wrapper


def run_query(
    db: Session,
    project: Project,
    question: str,
    top_k_override: int | None,
    api_key_id: uuid.UUID | None,
    conversation_id: str | None = None,
    usage_out: dict | None = None,
) -> QueryResponse:
    """Shared by the dashboard playground and the public /v1 endpoint.

    Answers from the project's "brain": document chunks plus any relevant agent
    memories (both live in the same per-project embedding space). When a
    conversation_id is given, the prior turns are loaded and this question is
    rewritten to be self-contained before retrieval, then the new turn is saved.
    """
    # Existence checks only (LIMIT 1 index probes) - the cache signature no
    # longer needs counts, it rides on project.content_version.
    has_chunks = bool(
        db.scalar(select(Chunk.id).where(Chunk.project_id == project.id).limit(1))
    )
    has_memories = bool(
        db.scalar(
            select(Memory.id)
            .where(Memory.project_id == project.id, Memory.embedding.isnot(None))
            .limit(1)
        )
    )
    if not has_chunks and not has_memories:
        raise HTTPException(
            status_code=409,
            detail="Project has no indexed content yet - upload files (or save memories) and wait for indexing",
        )

    top_k = min(top_k_override or project.top_k, 20)
    started = time.perf_counter()
    # Everything the tail reads off the Project, read NOW while it is certainly
    # loaded - same hazard as the streaming twin: retrieve_fn's memory-blend
    # recovery rolls back, and a rollback expires every persistent instance
    # regardless of expire_on_commit=False (pinned in TestReleaseSemantics).
    # An expired read down in the tail would emit a refresh SELECT, i.e. a pool
    # checkout that can time out after the answer is already paid for, losing a
    # finished answer to a 500.
    project_id = project.id
    project_key = str(project_id)
    model = f"{project.llm_provider}/{project.llm_model}"

    embed_memo, embed_query, _llm = _request_helpers(db, project)
    # Everything this request spends on LLM calls, summed for metering.
    request_usage = _UsageAccumulator()

    def retrieve_fn(query: str, k: int) -> list[dict]:
        """One retrieval pass over the brain: document chunks + relevant memories.

        Memories live in the same embedding space, so they're blended per query
        and compete with chunks on similarity for grounding - one shared query
        vector (via the per-request memo) serves both searches.
        """
        sources = (
            retrieval.retrieve(
                db,
                project,
                query,
                k,
                embed_fn=embed_query,
                # A cross-lingual question is translated before it is
                # embedded; that is an LLM call, so it rides the request's
                # own client and lands in the request's token total like
                # every other call. Passing neither would still work and
                # would silently stop metering it.
                llm=_llm,
                on_usage=request_usage.add,
            )
            if has_chunks
            else []
        )
        if has_memories and settings.rag_memory_blend_k > 0:
            try:
                for mem, sim in memory_service.search_memories(
                    db,
                    project,
                    query,
                    settings.rag_memory_blend_k,
                    embed_fn=embed_query,
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
                    project_id,
                )
                db.rollback()
        return sources

    # Conversation memory: load prior turns and rewrite a follow-up like
    # "summarize that" into a standalone question before retrieval. Empty history
    # (or no conversation) leaves the question untouched and costs nothing.
    history = (
        _conversations.get_history(project_key, conversation_id)
        if conversation_id
        else []
    )

    try:
        agentic_question = (
            _llm_step(
                db,
                _llm,
                lambda llm: agentic.condense_question(
                    _TrackedLLM(llm, "condense-question", request_usage),
                    history,
                    question,
                    settings.conversation_history_turns,
                ),
            )
            if history
            else question
        )

        def compute() -> agentic.AgenticResult:
            # The compute phase gets its own subtotal alongside the request
            # total: these are the tokens a future cache hit will have SAVED,
            # so they travel with the result into both caches. Condense is
            # deliberately outside - it runs before the caches and is spent
            # again on every follow-up, hit or not.
            fresh_usage = _UsageAccumulator()
            compute_usage = _FanoutUsage(request_usage, fresh_usage)
            result = agentic.run_agentic_query(
                question=agentic_question,
                retrieve_fn=retrieve_fn,
                plan_fn=lambda q: _llm_step(
                    db,
                    _llm,
                    lambda llm: agentic.plan_subqueries(
                        _TrackedLLM(llm, "plan-subqueries", compute_usage),
                        q,
                        settings.agentic_max_subqueries,
                    ),
                ),
                generate_fn=lambda q, srcs, depth: generation.generate_answer(
                    db, project, q, srcs, depth, llm_fn=_llm, usage_acc=compute_usage
                ),
                clarify_fn=lambda q: _llm_step(
                    db,
                    _llm,
                    lambda llm: agentic.request_clarification(
                        _TrackedLLM(llm, "request-clarification", compute_usage),
                        q,
                        settings.agentic_max_clarifying,
                    ),
                ),
                top_k=top_k,
                min_similarity=_grounding_policy(project)[0],
                min_strong=_grounding_policy(project)[1],
                max_rounds=settings.agentic_max_rounds,
            )
            return dataclasses.replace(
                result,
                gen_prompt_tokens=fresh_usage.total.prompt_tokens,
                gen_completion_tokens=fresh_usage.total.completion_tokens,
                gen_model=fresh_usage.total.model or None,
            )

        # Two cache layers, cheapest first. L1 (Redis/in-memory) hits when the
        # normalized question repeats EXACTLY. L2 (pgvector) hits when a
        # SIMILAR question was already answered - cosine similarity above the
        # threshold reuses the cached answer, below it the query runs for real.
        # Both are scoped by models + top_k + content_version, so ANY content
        # write (including in-place edits) instantly orphans stale answers.
        signature = _answer_signature(project, db, question)
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
                db, project, agentic_question, top_k, signature, embed_fn=embed_query
            )
            if semantic_vector is not None:
                # The lookup embedded through the memo, but seed defensively in
                # case a caller monkeypatches lookup - retrieval must never
                # re-embed the same string.
                embed_memo[agentic_question] = semantic_vector
            if hit is not None:
                result = hit
                cache_layer = "l2"
                if key is not None:
                    _cache.set(key, hit)  # promote to the exact-match L1
            elif key is not None:
                # single-flight: simultaneous identical asks compute once.
                # A follower blocks in here for the cache's whole flight wait,
                # on the LEADER's provider I/O, so give the connection back
                # before queueing - waiting on someone else's LLM call is no
                # reason to sit on a pool slot.
                generation.release_connection(db)
                result = _cache.get_or_compute(key, compute_and_remember)
            else:
                result = compute_and_remember()
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        # Upstream 429s become OUR 429 so callers back off instead of seeing
        # an opaque 500 (the SDKs already retried once by then).
        if is_provider_rate_limit(exc):
            raise HTTPException(
                status_code=429,
                detail="The AI provider is rate limiting this project's key - retry shortly.",
                headers={"Retry-After": "10"},
            )
        raise
    latency_ms = int((time.perf_counter() - started) * 1000)
    _fill_usage_out(usage_out, request_usage, cache_layer, result, latency_ms)

    # Guarded exactly like the streaming twin, and for the same reason: the
    # answer is generated and already paid for by here, and this commit is a
    # pool CHECKOUT - generation.generate_answer released the connection before
    # the LLM call, so the session holds none and has to take one back under
    # db_pool_timeout. Losing an analytics row is the cheap failure; turning a
    # finished answer into a 503 from main.py's PoolTimeoutError handler is not.
    try:
        db.add(
            QueryLog(
                project_id=project_id,
                api_key_id=api_key_id,
                question=question,
                top_k=top_k,
                latency_ms=latency_ms,
                cache_layer=cache_layer,
                retrieval_similarity=_mean_similarity(result.sources),
                cache_similarity=cache_similarity,
            )
        )
        db.commit()
    except Exception:
        logger.warning(
            "Query log write failed for project %s - the answer is still served",
            project_id,
        )
        db.rollback()

    answer = (
        agentic.clarification_message(result.clarification_questions)
        if result.needs_clarification
        else result.answer
    )

    # Remember this turn (the original question the user typed, plus the answer)
    # so the next follow-up has context.
    if conversation_id:
        _conversations.append_turn(project_key, conversation_id, question, answer)

    return QueryResponse(
        answer=answer,
        sources=[SourceChunk(**s) for s in _mark_cited(answer, result.sources)],
        model=model,
        latency_ms=latency_ms,
        depth=result.depth,
        sub_queries=result.sub_queries,
        needs_clarification=result.needs_clarification,
        clarification_questions=result.clarification_questions,
        conversation_id=conversation_id,
        cache_layer=cache_layer,
        cache_similarity=cache_similarity,
        retrieval_similarity=_mean_similarity(result.sources),
    )


def _slice_text(text: str, size: int = 18):
    """Break already-known text (a cache hit or a clarification) into small
    pieces so it streams to the client the same way a live answer does."""
    for i in range(0, len(text), size):
        yield text[i : i + size]


def run_query_stream(
    db: Session,
    project: Project,
    question: str,
    top_k_override: int | None,
    api_key_id: uuid.UUID | None = None,
    conversation_id: str | None = None,
    usage_out: dict | None = None,
):
    """Streaming twin of ``run_query``: yields event dicts as the answer is
    produced. Same brain, caches and agentic loop - only the final generation
    is streamed token by token.

    Events:
      * ``{"type": "token", "text": ...}``  - one answer delta (repeated)
      * ``{"type": "done", "response": {...}}`` - final QueryResponse-shaped payload
      * ``{"type": "error", "detail": ...}`` - a failure the client should show

    Errors are yielded (not raised): a streaming response has already sent its
    headers, so mid-stream failures cannot become HTTP status codes. That
    applies from the FIRST statement on - sse_response builds this generator
    lazily, so Starlette has emitted 200 + text/event-stream before anything
    below runs, and an escaping exception reaches the client as a truncated
    body, which an EventSource retries against the same broken dependency.
    """
    started = time.perf_counter()
    # Everything the tail reads off the Project, read NOW while it is certainly
    # loaded. The tail runs AFTER the query-log write, and that write's failure
    # branch rolls back - which expires every persistent instance regardless of
    # expire_on_commit=False (pinned in TestReleaseSemantics). retrieve_fn's
    # memory-blend recovery rolls back too. An expired attribute read down there
    # would emit a refresh SELECT, i.e. a pool checkout that can time out after
    # a complete answer has already been streamed, turning a good answer into a
    # failure. Guarding the tail would still lose the done frame, so the values
    # are captured instead and the tail touches no ORM attribute at all.
    # The capture itself is inside the guard: on a Session whose instances are
    # already expired, reading ANY mapped attribute is the refresh SELECT this
    # is protecting against, project.id included.
    project_id = None
    try:
        project_id = project.id
        project_key = str(project_id)
        model = f"{project.llm_provider}/{project.llm_model}"
        signature = _answer_signature(project, db, question)
        top_k = min(top_k_override or project.top_k, 20)
        has_chunks = bool(
            db.scalar(select(Chunk.id).where(Chunk.project_id == project.id).limit(1))
        )
        has_memories = bool(
            db.scalar(
                select(Memory.id)
                .where(Memory.project_id == project.id, Memory.embedding.isnot(None))
                .limit(1)
            )
        )
    except PoolTimeoutError:
        # Headers are already sent (200): a raised pool-checkout timeout would
        # abort the stream mid-air - emit a proper error frame instead.
        yield {
            "type": "error",
            "detail": "Server is at capacity - please retry shortly",
        }
        return
    except Exception:
        # PoolTimeoutError is only ONE of the ways this can fail: a failed
        # CONNECT raises OperationalError (see app/db.py), which is exactly what
        # pool_pre_ping produces when the pooler restarts under us - and the ORM
        # reads above can emit a refresh SELECT of their own. None of it may
        # escape past the headers, so everything the pre-flight touches is
        # covered, not just the checkout.
        logger.exception("Streaming query pre-flight failed for project %s", project_id)
        yield {"type": "error", "detail": "The query failed. Please try again."}
        return
    if not has_chunks and not has_memories:
        yield {
            "type": "error",
            "detail": "Project has no indexed content yet - upload files (or save memories) and wait for indexing",
        }
        return

    embed_memo, embed_query, _llm = _request_helpers(db, project)
    # Everything this request spends on LLM calls, summed for metering.
    request_usage = _UsageAccumulator()

    def retrieve_fn(query: str, k: int) -> list[dict]:
        sources = (
            retrieval.retrieve(
                db,
                project,
                query,
                k,
                embed_fn=embed_query,
                # A cross-lingual question is translated before it is
                # embedded; that is an LLM call, so it rides the request's
                # own client and lands in the request's token total like
                # every other call. Passing neither would still work and
                # would silently stop metering it.
                llm=_llm,
                on_usage=request_usage.add,
            )
            if has_chunks
            else []
        )
        if has_memories and settings.rag_memory_blend_k > 0:
            try:
                for mem, sim in memory_service.search_memories(
                    db,
                    project,
                    query,
                    settings.rag_memory_blend_k,
                    embed_fn=embed_query,
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
                pass
            except Exception:
                logger.exception(
                    "Memory blending failed for project %s; answering from "
                    "documents only",
                    project_id,
                )
                db.rollback()
        return sources

    history = (
        _conversations.get_history(project_key, conversation_id)
        if conversation_id
        else []
    )
    # signature was captured with the other Project reads in the guarded
    # pre-flight above - nothing between here and there writes content_version.
    cache_layer: str | None = None
    cache_similarity: float | None = None
    semantic_vector: list[float] | None = None
    # Compute-phase subtotal (what a future cache hit will have saved) - see
    # the non-streaming twin's compute() for why condense stays outside it.
    fresh_usage = _UsageAccumulator()
    compute_usage = _FanoutUsage(request_usage, fresh_usage)

    try:
        agentic_question = (
            _llm_step(
                db,
                _llm,
                lambda llm: agentic.condense_question(
                    _TrackedLLM(llm, "condense-question", request_usage),
                    history,
                    question,
                    settings.conversation_history_turns,
                ),
            )
            if history
            else question
        )

        # Same two-layer cache as run_query. A hit streams the stored text in
        # slices (so the UX is identical); a miss gathers context, then streams
        # the live generation and stores the finished answer back.
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
                db, project, agentic_question, top_k, signature, embed_fn=embed_query
            )
            if semantic_vector is not None:
                # Seed the memo with the lookup's vector - see run_query.
                embed_memo[agentic_question] = semantic_vector
            if hit is not None:
                result = hit
                cache_layer = "l2"
                if key is not None:
                    _cache.set(key, hit)

        # Single-flight: N simultaneous identical questions used to each run
        # the full retrieval + LLM pipeline on this path (only the
        # non-streaming path deduplicated). The first asker leads; followers
        # wait (bounded) and stream the leader's cached answer in slices.
        lead_lock = None
        if result is None and key is not None:
            flight = _cache.flight_lock(key)
            if flight.acquire(blocking=False):
                # NOTHING between this line and the try below: acquiring the
                # flight is the last statement outside the finally that releases
                # it, so no failure in between can leak the FLEET-WIDE lock.
                # (The re-read that used to sit here is the first thing inside.)
                lead_lock = flight
            else:
                # Follower: this waits on the leader's provider I/O for up to
                # two minutes. Hand the connection back first - see run_query.
                generation.release_connection(db)
                if flight.acquire(timeout=120.0):
                    flight.release()
                refreshed = _cache.get(key)
                if refreshed is not None:
                    result = refreshed
                    cache_layer = "l1"
                # else: the leader failed or timed out - compute ourselves,
                # unlocked (correctness over dedup in the degraded case).

        try:
            if lead_lock is not None:
                refreshed = _cache.get(key)  # leader may have JUST finished
                if refreshed is not None:
                    result = refreshed
                    cache_layer = "l1"
            if result is not None:
                text = (
                    agentic.clarification_message(result.clarification_questions)
                    if result.needs_clarification
                    else (result.answer or "")
                )
                for piece in _slice_text(text):
                    yield {"type": "token", "text": piece}
                final = result
            else:
                # Context gathering is the silent phase (no tokens yet) - run
                # it on a helper thread and emit keep-alive pings so proxies
                # don't kill the idle stream. The request thread only WAITS
                # while the helper uses the db session, so access stays
                # sequential.
                executor = ThreadPoolExecutor(max_workers=1)
                # Retrieval embeds the question on the HELPER thread, and
                # ContextVars do not cross a ThreadPoolExecutor. Without
                # re-entering the request's accumulator there, every embedding
                # token a STREAMED query spends would go unrecorded - the
                # non-streaming path would meter and this one silently would
                # not, which is the worst kind of gap because it looks like a
                # real difference in cost between the two.
                _emb = embedding_usage.current()
                try:
                    future = executor.submit(
                        _in_embedding_scope(_emb, agentic.gather_context),
                        question=agentic_question,
                        retrieve_fn=retrieve_fn,
                        plan_fn=lambda q: _llm_step(
                            db,
                            _llm,
                            lambda llm: agentic.plan_subqueries(
                                _TrackedLLM(llm, "plan-subqueries", compute_usage),
                                q,
                                settings.agentic_max_subqueries,
                            ),
                        ),
                        clarify_fn=lambda q: _llm_step(
                            db,
                            _llm,
                            lambda llm: agentic.request_clarification(
                                _TrackedLLM(
                                    llm, "request-clarification", compute_usage
                                ),
                                q,
                                settings.agentic_max_clarifying,
                            ),
                        ),
                        top_k=top_k,
                        min_similarity=_grounding_policy(project)[0],
                        min_strong=_grounding_policy(project)[1],
                        max_rounds=settings.agentic_max_rounds,
                    )
                    while True:
                        try:
                            ctx = future.result(timeout=10.0)
                            break
                        except FuturesTimeout:
                            yield {"type": "ping"}
                finally:
                    executor.shutdown(wait=False)
                if ctx.needs_clarification:
                    text = agentic.clarification_message(ctx.clarification_questions)
                    for piece in _slice_text(text):
                        yield {"type": "token", "text": piece}
                    final = agentic.AgenticResult(
                        answer=None,
                        sources=ctx.sources,
                        depth=ctx.depth,
                        sub_queries=ctx.sub_queries,
                        rounds=ctx.rounds,
                        needs_clarification=True,
                        clarification_questions=ctx.clarification_questions,
                        gen_prompt_tokens=fresh_usage.total.prompt_tokens,
                        gen_completion_tokens=fresh_usage.total.completion_tokens,
                        gen_model=fresh_usage.total.model or None,
                    )
                else:
                    acc: list[str] = []
                    for tok in generation.generate_answer_stream(
                        db,
                        project,
                        agentic_question,
                        ctx.sources,
                        ctx.depth,
                        llm_fn=_llm,
                        usage_acc=compute_usage,
                    ):
                        acc.append(tok)
                        yield {"type": "token", "text": tok}
                    final = agentic.AgenticResult(
                        answer="".join(acc),
                        sources=ctx.sources,
                        depth=ctx.depth,
                        sub_queries=ctx.sub_queries,
                        rounds=ctx.rounds,
                        needs_clarification=False,
                        gen_prompt_tokens=fresh_usage.total.prompt_tokens,
                        gen_completion_tokens=fresh_usage.total.completion_tokens,
                        gen_model=fresh_usage.total.model or None,
                    )
                    if key is not None:
                        _cache.set(key, final)
                    semantic_cache.store(
                        db, project, agentic_question, top_k, signature, final, semantic_vector
                    )
        finally:
            if lead_lock is not None:
                lead_lock.release()
    except ProviderUnavailableError as exc:
        _fill_usage_out(usage_out, request_usage, cache_layer, None, None)
        yield {"type": "error", "detail": str(exc)}
        return
    except Exception as exc:
        _fill_usage_out(usage_out, request_usage, cache_layer, None, None)
        if is_provider_rate_limit(exc):
            yield {
                "type": "error",
                "detail": "The AI provider is rate limiting this project's key - retry shortly.",
                "code": 429,
            }
            return
        logger.exception("Streaming query failed for project %s", project_id)
        yield {"type": "error", "detail": "The query failed. Please try again."}
        return

    latency_ms = int((time.perf_counter() - started) * 1000)
    _fill_usage_out(usage_out, request_usage, cache_layer, final, latency_ms)
    try:
        db.add(
            QueryLog(
                project_id=project_id,
                api_key_id=api_key_id,
                question=question,
                top_k=top_k,
                latency_ms=latency_ms,
                cache_layer=cache_layer,
                retrieval_similarity=_mean_similarity(final.sources),
                cache_similarity=cache_similarity,
            )
        )
        db.commit()
    except Exception:
        logger.warning(
            "Query log write failed for project %s - the answer is still streamed",
            project_id,
        )
        db.rollback()

    answer = (
        agentic.clarification_message(final.clarification_questions)
        if final.needs_clarification
        else final.answer
    )
    if conversation_id:
        _conversations.append_turn(project_key, conversation_id, question, answer)

    yield {
        "type": "done",
        "response": {
            "answer": answer,
            "sources": [dict(s) for s in _mark_cited(answer, final.sources)],
            "model": model,
            "latency_ms": latency_ms,
            "depth": final.depth,
            "sub_queries": final.sub_queries,
            "needs_clarification": final.needs_clarification,
            "clarification_questions": final.clarification_questions,
            "conversation_id": conversation_id,
            "cache_layer": cache_layer,
            "cache_similarity": cache_similarity,
            "retrieval_similarity": _mean_similarity(final.sources),
        },
    }
