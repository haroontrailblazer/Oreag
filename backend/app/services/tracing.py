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
            update: dict = {"output": text}
            # Omitted entirely when the provider reported nothing, rather than
            # sent as zeros. Zeros would be indistinguishable from a real empty
            # completion and would make Langfuse compute a cost of $0 for a call
            # that actually cost money.
            if usage.known:
                update["usage_details"] = {
                    "input": usage.prompt_tokens or 0,
                    "output": usage.completion_tokens or 0,
                }
            else:
                update.setdefault("metadata", {})
                update["metadata"] = {
                    **(metadata or {}),
                    "token_usage": "not reported by this provider",
                }
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
                update: dict = {"output": "".join(chunks)}
                if usage.known:
                    update["usage_details"] = {
                        "input": usage.prompt_tokens or 0,
                        "output": usage.completion_tokens or 0,
                    }
                else:
                    update["metadata"] = {
                        **(metadata or {}),
                        "token_usage": "not reported for this streamed call",
                    }
                span.update(**update)
            except Exception:
                logger.debug("Could not annotate a streamed span", exc_info=True)
    return usage
