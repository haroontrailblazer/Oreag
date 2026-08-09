import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


class ProviderUnavailableError(Exception):
    """Raised when a provider is not configured or not reachable."""


def is_provider_rate_limit(exc: BaseException) -> bool:
    """True when an upstream AI provider returned 429 (quota/rate limited).

    The query paths map these to HTTP 429 + Retry-After so callers back off,
    instead of the opaque 500 they used to get. Checked lazily per SDK - a
    provider package being absent just means it can't be the source.
    """
    try:
        import openai

        # Also covers every OpenAI-compatible vendor (Groq, Mistral, xAI, ...).
        if isinstance(exc, openai.RateLimitError):
            return True
    except ImportError:  # pragma: no cover
        pass
    try:
        import anthropic

        if isinstance(exc, anthropic.RateLimitError):
            return True
    except ImportError:  # pragma: no cover
        pass
    try:
        from google.genai import errors as genai_errors

        if isinstance(exc, genai_errors.APIError) and getattr(exc, "code", None) == 429:
            return True
    except ImportError:  # pragma: no cover
        pass
    return False


def ensure_width(
    vectors: list[list[float]], expected: int, provider: str, model: str
) -> list[list[float]]:
    """Fail loudly when a provider returns vectors of the wrong width.

    A vendor that IGNORES the requested size silently returns its native width,
    and nothing downstream notices: `chunks.embedding` is an untyped `Vector`
    column, so a 1536-wide vector inserts happily into a project configured for
    512. The result is not an error but a corrupted index - similarity scores
    computed against a mismatched space, quietly wrong answers, and a re-embed
    of the entire corpus to recover.

    This is exactly what Cohere's OpenAI-compatibility endpoint did: it accepts
    the `dimensions` parameter and does nothing with it. Checked here rather
    than per provider because the failure is indistinguishable from success at
    every other layer, and the next vendor to do it should cost one clear error
    instead of another silent corpus.
    """
    for vector in vectors:
        if len(vector) != expected:
            raise ProviderUnavailableError(
                f"{provider}/{model} returned {len(vector)}-dimensional vectors "
                f"but this project is configured for {expected}. The provider "
                "ignored the requested size - pick the model's native dimension "
                "in Settings, or choose a different embedding model."
            )
    return vectors


class EmbeddingProvider(Protocol):
    dimensions: int
    # How many texts this provider comfortably embeds per request - callers
    # (ingestion) batch by this, so each batch is exactly one API call.
    batch_size: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """What one model call actually consumed.

    Every provider already receives this and has been throwing it away -
    `resp.usage` on OpenAI/Anthropic/Sarvam/compat, `resp.usage_metadata` on
    Gemini, `prompt_eval_count`/`eval_count` on Ollama - because the contract
    below returned a bare `str`. That is why `usage_events.prompt_tokens` has
    been NULL since migration 0016.

    Counts are `int | None`, never 0-as-unknown. Zero is a real answer (an empty
    completion), and collapsing the two would make "we did not measure" and "it
    cost nothing" indistinguishable in the billing table.
    """

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    model: str = ""

    @property
    def known(self) -> bool:
        return self.prompt_tokens is not None or self.completion_tokens is not None

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        """Sum across the several model calls one request can make.

        A `/query` makes up to three (condense, decompose, then clarify OR
        synthesise), and the billing row wants the total. None + int == int:
        one unmeasured call must not erase the calls that WERE measured.
        """
        def add(a: int | None, b: int | None) -> int | None:
            if a is None and b is None:
                return None
            return (a or 0) + (b or 0)

        return TokenUsage(
            prompt_tokens=add(self.prompt_tokens, other.prompt_tokens),
            completion_tokens=add(self.completion_tokens, other.completion_tokens),
            model=self.model or other.model,
        )


class LLMProvider(Protocol):
    model: str

    def generate(self, system_prompt: str, user_prompt: str) -> str: ...

    def generate_with_usage(
        self, system_prompt: str, user_prompt: str
    ) -> tuple[str, TokenUsage]: ...


def _int_or_none(value) -> int | None:
    """Coerce a vendor's token count, tolerating anything unexpected.

    Every extractor below runs on a live response object, and metering must
    never be able to break generation - the answer is the product, the token
    count is bookkeeping. A vendor that renames a field, returns a string, or
    omits usage entirely yields None, not an exception.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def usage_from_openai(resp, model: str) -> TokenUsage:
    """OpenAI's `resp.usage` shape - also used by Azure, Sarvam and every
    OpenAI-compatible vendor, which is why it lives here rather than in three
    near-identical copies."""
    usage = getattr(resp, "usage", None)
    return TokenUsage(
        prompt_tokens=_int_or_none(getattr(usage, "prompt_tokens", None)),
        completion_tokens=_int_or_none(getattr(usage, "completion_tokens", None)),
        model=model,
    )


def usage_from_anthropic(resp, model: str) -> TokenUsage:
    """Anthropic names them input_tokens / output_tokens."""
    usage = getattr(resp, "usage", None)
    return TokenUsage(
        prompt_tokens=_int_or_none(getattr(usage, "input_tokens", None)),
        completion_tokens=_int_or_none(getattr(usage, "output_tokens", None)),
        model=model,
    )


def usage_from_gemini(resp, model: str) -> TokenUsage:
    """Gemini reports on `usage_metadata`, and counts the ANSWER as
    `candidates_token_count`."""
    usage = getattr(resp, "usage_metadata", None)
    return TokenUsage(
        prompt_tokens=_int_or_none(getattr(usage, "prompt_token_count", None)),
        completion_tokens=_int_or_none(getattr(usage, "candidates_token_count", None)),
        model=model,
    )


def usage_from_ollama(data: dict, model: str) -> TokenUsage:
    """Ollama returns counts inline in the same JSON body as the message."""
    if not isinstance(data, dict):
        return TokenUsage(model=model)
    return TokenUsage(
        prompt_tokens=_int_or_none(data.get("prompt_eval_count")),
        completion_tokens=_int_or_none(data.get("eval_count")),
        model=model,
    )


def call_llm(llm, system_prompt: str, user_prompt: str) -> tuple[str, TokenUsage]:
    """Call an LLM and get back its text AND what it cost.

    Tolerant of objects that only implement `generate` - every test stub in the
    suite does, and forcing ~13 of them to grow a method they do not care about
    would be churn for nothing.

    That tolerance is exactly how a real provider could silently report no
    tokens, so it is paired with a test asserting every CONCRETE provider class
    implements `generate_with_usage` (tests/test_token_usage.py). The escape
    hatch exists for stubs, not for production.
    """
    with_usage = getattr(llm, "generate_with_usage", None)
    if with_usage is None:
        return llm.generate(system_prompt, user_prompt), TokenUsage(
            model=getattr(llm, "model", "")
        )
    return with_usage(system_prompt, user_prompt)


def stream_openai_chat(create, model: str):
    """Yield text deltas from an OpenAI-style chat stream, returning `TokenUsage`.

    Shared by OpenAI, Sarvam and every OpenAI-compatible vendor. A streamed
    response carries NO usage unless `stream_options.include_usage` is asked
    for, and when it is granted the counts arrive in a FINAL chunk that has
    usage and an EMPTY `choices` list - precisely the chunk a delta loop skips.
    Missing that detail is why a streamed answer reported nothing at all.

    `create` is a callable taking the extra kwargs so the option can be
    retried away: several OpenAI-compatible vendors reject `stream_options`
    outright with a 400. The answer matters more than the bookkeeping, so a
    rejection falls back to a plain stream and reports usage as unknown. If the
    plain call fails too the failure is real and propagates.

    The return value is delivered through `yield from`, so a caller that simply
    iterates for text is unaffected.
    """
    try:
        stream = create(stream_options={"include_usage": True})
    except Exception:
        logger.debug("Vendor rejected stream_options; streaming unmetered",
                     exc_info=True)
        stream = create()
    usage = TokenUsage(model=model)
    for chunk in stream:
        # Checked on every chunk, not just the last: vendors disagree about
        # where usage lands, and taking the newest known value is right for
        # both the final-chunk and the cumulative-per-chunk conventions.
        found = usage_from_openai(chunk, model)
        if found.known:
            usage = found
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
    return usage


def embedding_tokens_from_openai(resp) -> int | None:
    """Input tokens for one embeddings request, or None if not reported.

    OpenAI (and Azure, and most compatible vendors) put the count on
    `resp.usage.prompt_tokens`. An embedding has no completion side, so this is
    the whole cost of the call.
    """
    usage = getattr(resp, "usage", None)
    return _int_or_none(getattr(usage, "prompt_tokens", None))


def embedding_tokens_from_gemini(resp) -> int | None:
    """Gemini reports embedding usage as `usage_metadata.prompt_token_count`
    when it reports it at all - several model/version combinations omit it,
    which is why None has to be a supported answer rather than an error."""
    meta = getattr(resp, "usage_metadata", None)
    if meta is None:
        return None
    # Batched calls may return a list, one entry per input.
    if isinstance(meta, list):
        counts = [_int_or_none(getattr(m, "prompt_token_count", None)) for m in meta]
        known = [c for c in counts if c is not None]
        return sum(known) if known else None
    return _int_or_none(getattr(meta, "prompt_token_count", None))
