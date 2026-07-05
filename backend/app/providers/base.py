from typing import Protocol


class ProviderUnavailableError(Exception):
    """Raised when a provider is not configured or not reachable."""


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
