from typing import Protocol


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


class LLMProvider(Protocol):
    model: str

    def generate(self, system_prompt: str, user_prompt: str) -> str: ...
