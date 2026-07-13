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
