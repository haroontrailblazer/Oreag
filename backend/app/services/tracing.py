"""Langfuse tracing. Optional, fail-open, and never able to break a request.

THE ONE RULE: observability must not take the product down. Every public
function here swallows its own exceptions and degrades to a no-op. A trace that
fails to record is an inconvenience; a `/query` that 500s because the tracing
backend had a bad minute is an outage caused by the thing meant to prevent them.

DISABLED BY DEFAULT. With `langfuse_enabled` false or the keys empty, `client()`
returns None and every helper below short-circuits, so a deploy without
credentials behaves exactly as it did before this module existed.

CONTENT SAMPLING, and why it is a mask rather than `sample_rate`:
Langfuse's own `sample_rate` drops whole traces - you lose the tokens and cost
too, which are the numbers billing and the usage page need on 100% of traffic.
What we actually want is "always record the metadata, record the TEXT only
sometimes", because one Oreag query emits 6-8 observations and the free tier is
~6-7k queries/month. So every trace is kept and a `mask` callable redacts
input/output on the unsampled majority. Errors are never redacted - a failure
you cannot read is a failure you cannot fix.
"""
import logging
import os
import random
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Any

from ..config import settings

logger = logging.getLogger(__name__)

# Whether THIS trace keeps its content. Read by the mask callback, which the SDK
# invokes on every field it is about to send.
#
# A ContextVar deliberately, not a thread local: it follows async tasks. It does
# NOT cross the ThreadPoolExecutor that services/query.py uses for the streaming
# path, so content there falls back to redacted - the safe direction, and worth
# knowing before someone reports "streaming traces have no text".
_keep_content: ContextVar[bool] = ContextVar("langfuse_keep_content", default=False)

REDACTED = "[redacted: outside the content sample]"


def _mask(data: Any) -> Any:
    """Redact input/output unless this trace was sampled for content.

    Signature is dictated by the SDK (it passes `data=`). Returning the value
    unchanged is the "keep it" path.

    Never raises: an exception in here would surface inside the SDK's export
    path, and the whole point of this module is that it cannot do that.
    """
    try:
        if _keep_content.get():
            return data
        return REDACTED
    except Exception:  # pragma: no cover - defensive
        return REDACTED


@lru_cache(maxsize=1)
def client():
    """The process-wide Langfuse client, or None when tracing is off.

    Cached because constructing it starts an exporter thread; called on every
    request, so it must be cheap after the first.

    Returns None - rather than raising - on a missing SDK or a bad config, so
    that a broken observability setup can never be the reason the API is down.
    """
    if not settings.langfuse_enabled:
        return None
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.warning(
            "LANGFUSE_ENABLED is true but the keys are empty - tracing is off."
        )
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
            # Keeps local experiments out of the production dashboards.
            environment=_environment(),
            mask=_mask,
        )
    except Exception:
        logger.warning(
            "Could not start Langfuse; continuing without tracing", exc_info=True
        )
        return None


def _environment() -> str:
    """Which Langfuse environment these traces belong to.

    Detected from the PLATFORM, not from the database URL. The first attempt
    keyed on `database_url` containing "localhost" and was wrong on this
    project: dev and prod share one Supabase pooler host, so a laptop reported
    "production" and would have polluted the dashboard the field exists to keep
    clean - silently, which is the worst kind of wrong.

    Render injects RENDER=true into every service it runs. Absent it, assume a
    developer machine: the safe direction, because a mislabelled dev trace is
    noise in a dev dashboard, while a mislabelled prod trace corrupts the
    numbers someone makes decisions from.

    `LANGFUSE_ENVIRONMENT` overrides both, for staging or a container Render
    does not run.
    """
    explicit = (settings.langfuse_environment or "").strip()
    if explicit:
        return explicit
    return "production" if os.environ.get("RENDER") else "development"


def roll_content_sample() -> bool:
    """Decide whether this trace keeps its text, and remember it for the mask.

    Called once per request at the root span. Errors and low-scoring traces are
    force-kept by callers via `keep_content()` regardless of this roll.
    """
    keep = random.random() < max(0.0, min(1.0, settings.langfuse_content_sample_rate))
    _keep_content.set(keep)
    return keep


def keep_content() -> None:
    """Force this trace to keep its content - used on the error path.

    A redacted failure is a failure nobody can diagnose, which defeats the
    reason for tracing at all.
    """
    _keep_content.set(True)


def flush() -> None:
    """Push buffered spans. Called at shutdown, where the exporter thread would
    otherwise be killed with events still queued."""
    lf = client()
    if lf is None:
        return
    try:
        lf.flush()
    except Exception:
        logger.debug("Langfuse flush failed", exc_info=True)


def shutdown() -> None:
    lf = client()
    if lf is None:
        return
    try:
        lf.shutdown()
    except Exception:
        logger.debug("Langfuse shutdown failed", exc_info=True)


def _usage_fields(usage, metadata: dict | None) -> dict:
    """The `usage_details` / `cost_details` half of a generation update.

    WHY COST IS SENT AND NOT LEFT TO LANGFUSE. Given a model name and token
    counts, Langfuse prices the call itself, from a model table it maintains.
    That is a SECOND pricing authority, and the two disagree in two measurable
    ways - checked against this project's live Langfuse, 182 model definitions:

      * 13 of our 29 priced model ids match nothing there at all (grok-4, both
        deepseek-v4, both groq llamas, gpt-oss-120b, both cohere, both
        together, both fireworks, anthropic/claude-sonnet-4.5). Those calls
        showed real dollars on the Usage page and a BLANK in Langfuse.
      * `claude-sonnet-5` matched at $2/$10 against our $3/$15 - a 50% split on
        the same call.

    Sending `cost_details` makes Oreag the single source of truth FOR EVERY
    MODEL IT PRICES: Langfuse stores what it is given rather than re-deriving
    it, so those two numbers cannot drift no matter what either table says
    next.

    It is not a guarantee about everything. `cost_breakdown` returns None for
    any id absent from the table - 27 of the catalog's LLM ids, and all but
    three embedders - and for those we still send tokens and a model name with
    no cost, so Langfuse prices them from its own table while `usage_events`
    stores NULL. A model named in the `unpriced_models` caveat can therefore
    show dollars in Langfuse and nothing here. The only lever on that is
    registry coverage; withholding the tokens too would break the one thing the
    two ledgers already agree on.

    The gate is `priceable`, not `known`. See TokenUsage.priceable - `known` is
    an OR, and a half-measured call used to be sent as `output: 0`, which
    Langfuse happily priced while `cost_for` stored NULL.
    """
    from ..providers.registry import cost_breakdown

    if not usage.priceable:
        # Two different failures, and saying "the provider reported nothing"
        # about a call that reported 1500 prompt tokens is a statement this
        # code knows to be false. The half-measured case keeps its number - as
        # metadata, so Langfuse still cannot turn it into a price.
        note = (
            "not reported by this provider"
            if not usage.known
            else "partial - only one side of the call was reported"
        )
        extra = {"token_usage": note}
        if usage.known:
            extra["reported_input_tokens"] = usage.prompt_tokens
            extra["reported_output_tokens"] = usage.completion_tokens
        return {"metadata": {**(metadata or {}), **extra}}

    prompt = usage.prompt_tokens or 0
    completion = usage.completion_tokens or 0
    update: dict = {
        "usage_details": {
            "input": prompt,
            "output": completion,
            "total": prompt + completion,
        }
    }
    cost = cost_breakdown(usage.model, usage,
                          provider=getattr(usage, "provider", None))
    if cost is not None:
        update["cost_details"] = cost
    if usage.reasoning_tokens is not None:
        # Deliberately metadata, NOT a usage key. It is a SUBSET of `output`
        # and already paid for there; sending it as `output_reasoning_tokens`
        # would add it to the token counts Langfuse displays and derives, and
        # token counts are the one thing the two ledgers already agree on.
        #
        # The trade-off is real and worth stating: metadata goes through the
        # same content mask as input/output, so on a trace outside the content
        # sample this split is redacted. The COST is unaffected - the thinking
        # tokens are inside `output` and inside `cost_details` either way -
        # so what is lost is visibility, not accuracy.
        update["metadata"] = {
            **(metadata or {}),
            "reasoning_tokens": usage.reasoning_tokens,
        }
    return update


def _has_live_span() -> bool:
    """Whether an OpenTelemetry span is currently recording.

    The question is "is there a trace to inherit", and only OTel can answer it -
    `client()` being non-None says tracing is configured, not that a span is
    open. Any failure answers True, because inheriting is the safe direction:
    the worst case is an observation nested under the wrong parent, where the
    alternative rewrites a live trace's tags.
    """
    try:
        from opentelemetry import trace

        return trace.get_current_span().is_recording()
    except Exception:  # pragma: no cover - defensive
        return True


def record_embedding_spend(
    by_model: dict[str, int],
    *,
    owner_id=None,
    project_id=None,
    api_key_id=None,
) -> None:
    """Emit one observation per embedding model whose tokens we just billed.

    WHY THIS EXISTS. Langfuse held no embedding observation of any kind, while
    the Usage page adds embedding dollars into its headline total. So the two
    numbers were summing DIFFERENT SETS OF CALLS - measured on this account,
    $0.005371 of the app's spend had no counterpart in Langfuse at all. That is
    most of the gap a user sees when they put the two side by side, and no
    amount of price-table agreement could ever have closed it.

    WHY IT CARRIES ITS OWN ATTRIBUTION, AND ONLY SOMETIMES. This is called from
    `record_usage`, which on the BUFFERED routes runs after `query_trace` has
    closed - and on `/files`, `/memory` and background ingest there was never a
    trace at all. An observation opened with no active span becomes a new root
    trace, and the SDK is explicit that Langfuse's aggregations "only include
    observations that have the attribute set", so such a trace would land in
    the account-wide total while vanishing from cost-per-project and
    cost-per-key - the two questions `query_trace` exists to answer - and would
    be invisible to `forget_user`, which finds traces by userId.

    But the STREAMED routes call `record_usage` while the trace is still open
    (rag_v1.py and playground.py both do it in a `finally` inside the `with`).
    Re-entering `propagate_attributes` there does not create a scope - it
    merges onto whatever span is current, so it wrote `embedding` into the
    ROOT span's tags and stamped this function's metadata over the query's.
    A streamed query and a buffered one then produced structurally different
    traces for the same product event, which is the very thing this change set
    out to stop.

    So: inherit when there is a live span, re-establish only when there is not.

    One observation per model per call, not per `embed_texts`: an ingest embeds
    hundreds of chunks, and the tally is what the bill is made of.

    Never raises - tracing is not allowed to break the request it describes.
    """
    if not by_model:
        return
    lf = client()
    if lf is None:
        return
    from ..providers.registry import embedding_cost_for

    try:
        from langfuse import propagate_attributes
    except Exception:  # pragma: no cover - defensive
        return

    def _emit() -> None:
        for model, tokens in by_model.items():
            with lf.start_as_current_observation(
                as_type="generation", name="embed", model=model
            ) as span:
                # An embedding has no completion side, so `input` and `total`
                # are the same number. Langfuse prices several embedders off a
                # `total` key rather than `input`, so both are sent.
                update: dict = {"usage_details": {"input": tokens, "total": tokens}}
                cost = embedding_cost_for(model, tokens)
                if cost is not None:
                    update["cost_details"] = {"input": cost, "total": cost}
                span.update(**update)

    try:
        if owner_id is None or _has_live_span():
            # Inherit. A live span already carries the trace's user/project
            # attribution, and the observation nests under it as a child.
            _emit()
            return
        # None-valued entries are dropped rather than sent: the SDK coerces
        # metadata values with str(), so `None` arrives as the four-character
        # string "None" and a Langfuse filter on api_key_id matches it.
        attribution = {
            key: str(value)
            for key, value in (
                ("project_id", project_id),
                ("api_key_id", api_key_id),
            )
            if value is not None
        }
        with propagate_attributes(
            user_id=str(owner_id), tags=["embedding"], metadata=attribution
        ):
            _emit()
    except Exception:
        # WARNING, not debug: this is the branch production always takes, and
        # at debug level a failure here is silent in every real deployment.
        logger.warning("Could not record embedding spend", exc_info=True)


def observed_generate(llm, system_prompt: str, user_prompt: str, *, name: str,
                      metadata: dict | None = None):
    """Call an LLM and record it as a Langfuse `generation`.

    Returns `(text, TokenUsage)` exactly as `providers.base.call_llm` does, so a
    caller that ignores tracing entirely still gets its answer and its tokens.

    `generation` is the right observation type rather than a plain span:
    Langfuse only computes cost for generations, and it does so from the model
    name plus the token counts - which is why `usage_details` uses its
    "input"/"output" keys rather than our column names.

    If ANYTHING here fails - no client, a bad key, an SDK change - the model
    call still happens and its result is still returned. Tracing is never
    allowed to be the reason an answer does not arrive.
    """
    from ..providers.base import call_llm

    lf = client()
    if lf is None:
        return call_llm(llm, system_prompt, user_prompt)

    model = getattr(llm, "model", "") or ""
    try:
        observation = lf.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            metadata=metadata or {},
        )
    except Exception:
        logger.debug("Could not open a generation span", exc_info=True)
        return call_llm(llm, system_prompt, user_prompt)

    with observation as span:
        text, usage = call_llm(llm, system_prompt, user_prompt)
        try:
            # Usage and cost are omitted entirely unless BOTH counts exist,
            # rather than sent as zeros: a zero is indistinguishable from a
            # real empty completion and would make Langfuse price a call that
            # actually cost money at $0.
            update: dict = {"output": text, **_usage_fields(usage, metadata)}
            span.update(**update)
        except Exception:
            logger.debug("Could not annotate a generation span", exc_info=True)
    return text, usage


@contextmanager
def query_trace(*, project, question: str, api_key_id=None, conversation_id=None):
    """One trace per /query, with the attribution Langfuse needs to group by.

    WITHOUT THIS every generation is its own orphan trace: the up-to-three model
    calls of one request appear as three unrelated rows, and nothing carries the
    project, the key or the conversation - so Langfuse cannot answer "cost per
    project" or "cost per API key" at all, which is the entire reason to send it
    anything.

    session_id is the conversation, so a multi-turn thread reads as one session.
    user_id is the PROJECT OWNER rather than the end user: Oreag never sees the
    caller's identity - a project API key is not a person - and putting the key
    id there would silently create a distinct "user" per key on one account.
    The key travels as its own metadata field instead.

    Yields the root span, or None when tracing is off. Never raises: a failure
    here would take down the request it is only meant to describe.
    """
    lf = client()
    if lf is None:
        yield None
        return

    roll_content_sample()
    try:
        from langfuse import propagate_attributes
    except Exception:  # pragma: no cover - defensive
        yield None
        return

    try:
        with propagate_attributes(
            user_id=str(getattr(project, "owner_id", "") or ""),
            session_id=str(conversation_id) if conversation_id else None,
            tags=["query"],
            metadata={
                "project_id": str(getattr(project, "id", "")),
                "project_name": getattr(project, "name", None),
                # Which key paid for this. The Usage page groups by it, and a
                # trace that cannot be attributed to a key cannot be reconciled
                # against the usage_events row it should match.
                "api_key_id": str(api_key_id) if api_key_id else None,
                "llm": f"{getattr(project, 'llm_provider', '')}/"
                f"{getattr(project, 'llm_model', '')}",
                "embedding": f"{getattr(project, 'embedding_provider', '')}/"
                f"{getattr(project, 'embedding_model', '')}",
            },
        ):
            with lf.start_as_current_observation(
                as_type="span", name="answer-question", input={"question": question}
            ) as root:
                yield root
    except Exception:
        logger.debug("Could not open the query trace", exc_info=True)
        yield None


def observed_stream(llm, streamer, system_prompt: str, user_prompt: str, *,
                    name: str, metadata: dict | None = None):
    """Record a STREAMED generation, yielding deltas and returning `TokenUsage`.

    A streamed call cannot use `observed_generate`: there is no single moment
    that produces the whole answer. The span has to stay open for as long as
    the client keeps reading, and it must be closed even when the client
    disconnects mid-answer - hence the `finally`, which runs on `GeneratorExit`
    too. Without it an abandoned stream would leak an unfinished span and its
    tokens would never be recorded.

    Usage arrives via the streamer's return value, so this is a `yield from`
    delegate rather than a wrapper: text flows straight through to the caller.
    """
    lf = client()
    model = getattr(llm, "model", "") or ""
    if lf is None:
        return (yield from streamer(system_prompt, user_prompt))
    try:
        observation = lf.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            metadata=metadata or {},
        )
    except Exception:
        logger.debug("Could not open a streamed generation span", exc_info=True)
        return (yield from streamer(system_prompt, user_prompt))

    from ..providers.base import TokenUsage

    usage = TokenUsage(model=model)
    chunks: list[str] = []
    with observation as span:
        try:
            gen = streamer(system_prompt, user_prompt)
            while True:
                try:
                    delta = next(gen)
                except StopIteration as stop:
                    if isinstance(stop.value, TokenUsage):
                        usage = stop.value
                    break
                chunks.append(delta)
                yield delta
        finally:
            try:
                update: dict = {
                    "output": "".join(chunks),
                    **_usage_fields(usage, metadata),
                }
                span.update(**update)
            except Exception:
                logger.debug("Could not annotate a streamed span", exc_info=True)
    return usage


def register_user(user_id, *, email: str | None = None) -> None:
    """Make an Oreag account visible in Langfuse's Users view immediately.

    Langfuse has NO user-creation API - probed and confirmed, POST
    /api/public/users is a 404. A "user" there is derived: it exists because
    some observation carried that `userId`. So the only way to make an account
    appear at signup, rather than on its first query, is to emit one
    observation for it.

    That is what this does - a single tiny event, not a fabricated query. It
    carries no question and no answer, so it cannot be mistaken for real
    traffic in any of the RAG dashboards.

    Never raises: a failure here must not be able to break a signup.
    """
    lf = client()
    if lf is None:
        return
    try:
        from langfuse import propagate_attributes
    except Exception:  # pragma: no cover - defensive
        return
    try:
        # propagate_attributes, exactly as query_trace does - NOT
        # update_current_trace. The latter did not attach user_id here and the
        # account never appeared, which is the whole point of the call.
        with propagate_attributes(
            user_id=str(user_id),
            tags=["lifecycle"],
            metadata={"lifecycle": "signup", "email": email},
        ):
            with lf.start_as_current_observation(
                as_type="span",
                name="account-created",
                input={"event": "signup"},
            ):
                pass
        lf.flush()
    except Exception:
        logger.debug("Could not register the user in Langfuse", exc_info=True)


# A hard stop, so a paging bug can never become an unbounded loop against a
# third-party API. 100 pages x 100 traces is far beyond any real account.
_MAX_TRACE_PAGES = 100


def forget_user(user_id) -> int:
    """Delete everything Langfuse holds for one account. Returns traces removed.

    The counterpart to `register_user`: deleting an Oreag account must not
    leave its questions and answers sitting in an observability backend. There
    is no "delete user" endpoint either, for the same reason there is no create
    one - a user IS its traces, so removing them removes the user.

    Paged deliberately: an active account can have far more traces than one
    response returns, and stopping at the first page would silently leave data
    behind while reporting success.

    Best-effort, like everything else in this module - but the caller logs the
    count, because "we deleted your data" is a claim that should be checkable.
    """
    lf = client()
    if lf is None:
        return 0
    import httpx

    from ..config import settings

    base = (settings.langfuse_base_url or "").rstrip("/")
    auth = (settings.langfuse_public_key or "", settings.langfuse_secret_key or "")
    if not base or not all(auth):
        return 0

    # COLLECT every id first, then delete - never delete-then-requery.
    #
    # Deletion in Langfuse is asynchronous: a trace stays readable for a while
    # after a successful DELETE. A loop that re-queries page 1 after each
    # delete therefore sees the same ids again, "deletes" them again, and
    # counts them again - the first version of this reported 7 removals for a
    # single trace and rate-limited itself into a 429 doing it.
    ids: list[str] = []
    seen: set[str] = set()
    try:
        with httpx.Client(base_url=base, auth=auth, timeout=30) as http:
            page = 1
            while page <= _MAX_TRACE_PAGES:
                resp = http.get(
                    "/api/public/traces",
                    params={"userId": str(user_id), "page": page, "limit": 100},
                )
                if resp.status_code == 429:
                    logger.warning(
                        "Langfuse rate limited the cleanup for %s; "
                        "%d traces collected so far", user_id, len(ids)
                    )
                    break
                resp.raise_for_status()
                batch = resp.json().get("data", [])
                if not batch:
                    break
                # Dedup across pages: paging a list that is being written to
                # can repeat an entry, and a repeat must not become a second
                # delete request.
                fresh = [t["id"] for t in batch if t["id"] not in seen]
                seen.update(fresh)
                ids.extend(fresh)
                if len(batch) < 100:
                    break
                page += 1

            for i in range(0, len(ids), 100):
                chunk = ids[i : i + 100]
                deleted = http.request(
                    "DELETE", "/api/public/traces", json={"traceIds": chunk}
                )
                if deleted.status_code == 429:
                    logger.warning(
                        "Langfuse rate limited the delete for %s after %d",
                        user_id, i
                    )
                    return i
                deleted.raise_for_status()
    except Exception:
        logger.warning("Langfuse cleanup failed for user %s", user_id, exc_info=True)
        return 0
    return len(ids)


def current_trace_id() -> str | None:
    """The id of the trace currently in scope, or None.

    Must be called while the root span is still open: once its context manager
    exits there is no current trace, and a judge or score attached afterwards
    would have nowhere to land.
    """
    lf = client()
    if lf is None:
        return None
    try:
        return lf.get_current_trace_id()
    except Exception:
        logger.debug("Could not read the current trace id", exc_info=True)
        return None
