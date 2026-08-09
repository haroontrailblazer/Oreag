"""Collect embedding token usage without changing the embedder contract.

Embedding is plausibly the LARGEST token consumer in Oreag - every chunk of
every uploaded file, every memory, every query and every semantic-cache probe -
and it reported nothing at all. `usage_events` rows for `files_upload` and
`memory_create` existed with NULL tokens for exactly this reason.

WHY A CONTEXTVAR AND NOT A RETURN VALUE

`embed_texts` returns `list[list[float]]` and is called from dozens of places
(ingestion, memory, retrieval, semantic cache, re-embedding). Widening it to
return usage as well would touch all of them, and every caller would have to
thread the numbers back up by hand.

WHY NOT AN ATTRIBUTE ON THE EMBEDDER

`get_embedder` is `@lru_cache`d, so instances are SHARED across requests and
across projects. Per-request state on the instance would leak one project's
token counts into another's bill - the single most damaging bug this module
could have.

A ContextVar is scoped to the caller, so concurrent requests accumulate
independently, and an embedder used outside any scope records nothing rather
than failing.

THE THREAD BOUNDARY

ContextVars do NOT cross `ThreadPoolExecutor`, and the streaming path fans out
retrieval into one. `scope()` therefore returns the accumulator itself, and
`adopt()` lets a worker thread re-enter the caller's accumulator explicitly -
copying the context is not enough, because the child would then accumulate into
a COPY whose numbers the parent never sees.
"""
import contextvars
import logging
import threading
from contextlib import contextmanager

from ..providers.base import TokenUsage

logger = logging.getLogger(__name__)


class EmbeddingUsage:
    """Thread-safe tally of embedding tokens, per model.

    Locked because retrieval fans out across a thread pool and several threads
    can embed into the same accumulator at once.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_model: dict[str, int] = {}
        self._calls = 0
        self._unmeasured_calls = 0
        # Auxiliary LLM usage collected in the same scope: image captioning and
        # audio transcription during ingest. They belong here for exactly the
        # reason embeddings do - the call happens deep inside a pipeline whose
        # return value is markdown, not usage, so there is no way to thread the
        # numbers back up. Kept in a SEPARATE field because they are chat
        # tokens, priced by the chat table, not embedding tokens.
        self._llm = TokenUsage()

    def record(self, model: str, tokens: int | None) -> None:
        with self._lock:
            self._calls += 1
            if tokens is None:
                # The provider does not report usage (local models, and some
                # hosted ones). Counted separately so the UI can say "N calls
                # went unmeasured" rather than implying they were free.
                self._unmeasured_calls += 1
                return
            self._by_model[model] = self._by_model.get(model, 0) + tokens

    def record_llm(self, usage: TokenUsage) -> None:
        with self._lock:
            self._llm = self._llm + usage

    @property
    def llm_total(self) -> TokenUsage:
        """Chat tokens spent inside this scope (captioning, transcription)."""
        with self._lock:
            return self._llm

    @property
    def by_model(self) -> dict[str, int]:
        with self._lock:
            return dict(self._by_model)

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    @property
    def unmeasured_calls(self) -> int:
        with self._lock:
            return self._unmeasured_calls

    @property
    def total(self) -> TokenUsage:
        """Embedding tokens as a `TokenUsage`, so it prices like any other call.

        They are all INPUT tokens - an embedding produces a vector, not text -
        so `completion_tokens` is 0, a real measurement rather than None. The
        model is the one that consumed the most, which is the one that priced
        the request in every real case (mixing embedding models within a single
        request does not happen).
        """
        by_model = self.by_model
        if not by_model:
            return TokenUsage()
        model = max(by_model, key=lambda m: by_model[m])
        return TokenUsage(
            prompt_tokens=sum(by_model.values()),
            completion_tokens=0,
            model=model,
        )


_current: contextvars.ContextVar[EmbeddingUsage | None] = contextvars.ContextVar(
    "oreag_embedding_usage", default=None
)


@contextmanager
def scope():
    """Collect every embedding call made inside this block.

    Yields the accumulator so a caller can hand it to a worker thread via
    `adopt()`. Restores the previous accumulator on exit, so nesting (a query
    inside an ingest, say) does not clobber the outer tally.
    """
    acc = EmbeddingUsage()
    token = _current.set(acc)
    try:
        yield acc
    finally:
        _current.reset(token)


@contextmanager
def adopt(acc: "EmbeddingUsage | None"):
    """Re-enter an existing accumulator, for code running on another thread.

    Retrieval runs inside a `ThreadPoolExecutor`, which does not carry
    ContextVars across the boundary. Without this, every embedding call made
    during a streamed query would be silently dropped.
    """
    if acc is None:
        yield None
        return
    token = _current.set(acc)
    try:
        yield acc
    finally:
        _current.reset(token)


def current() -> EmbeddingUsage | None:
    return _current.get()


def record(model: str, tokens: int | None) -> None:
    """Called by embedders. A no-op outside any scope, and never raises -
    metering must not be able to break an embedding."""
    acc = _current.get()
    if acc is None:
        return
    try:
        acc.record(model, tokens)
    except Exception:
        logger.debug("Embedding usage record failed", exc_info=True)


def record_llm(usage: TokenUsage) -> None:
    """Called by image captioning and audio transcription during ingest.

    Same contract as `record`: a no-op outside a scope, never raises. These
    were the last unmetered spend in the product - a scanned PDF captions every
    page through a vision model, which for an image-heavy document costs more
    than embedding it.
    """
    acc = _current.get()
    if acc is None or usage is None or not usage.known:
        return
    try:
        acc.record_llm(usage)
    except Exception:
        logger.debug("LLM usage record failed", exc_info=True)
