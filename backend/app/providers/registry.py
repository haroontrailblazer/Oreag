from .base import EmbeddingProvider, LLMProvider

# Single source of truth for what the wizard offers and what the backend accepts.
# "dimensions" is the model's default; "dimension_options" lists the sizes a
# Matryoshka-trained (MRL) model supports - its vectors can be truncated to any
# listed prefix and re-normalized without re-embedding. Models without options
# have exactly one valid size.
CATALOG: dict = {
    "embedding": {
        "openai": [
            {
                "model": "text-embedding-3-small",
                "dimensions": 1536,
                "dimension_options": [512, 1536],
            },
            {
                "model": "text-embedding-3-large",
                "dimensions": 3072,
                "dimension_options": [256, 1024, 3072],
            },
        ],
        "gemini": [
            {"model": "text-embedding-004", "dimensions": 768},
            {
                "model": "gemini-embedding-001",
                "dimensions": 3072,
                "dimension_options": [768, 1536, 3072],
            },
        ],
        "ollama": [
            {"model": "nomic-embed-text", "dimensions": 768},
            {"model": "mxbai-embed-large", "dimensions": 1024},
        ],
        "sentence_transformers": [
            {"model": "all-MiniLM-L6-v2", "dimensions": 384},
        ],
    },
    "llm": {
        # Current GPT-5.x lineup (cheap default → flagship); the legacy 4o pair
        # is still served by OpenAI and stored on existing projects.
        "openai": ["gpt-5.4-mini", "gpt-5.4", "gpt-5.5", "gpt-4o-mini", "gpt-4o"],
        # Google retires models fast (gemini-1.5-*, gemini-2.0-flash, and even
        # 3.x previews all 404 now). Offer live-verified stable models plus the
        # rolling -latest aliases (always point at the newest served model);
        # never pin previews.
        "gemini": [
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-flash-latest",
            "gemini-pro-latest",
        ],
        # Current Sonnet 5 + most-capable Opus 4.8, plus the still-active
        # previous generation. The dated haiku id stays because existing
        # projects may have it stored (validate_llm runs on every query).
        "anthropic": [
            "claude-sonnet-5",
            "claude-opus-4-8",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ],
        "sarvam": ["sarvam-30b", "sarvam-105b"],
        # Local tags never 404; headline current models. llama3.1 stays (most
        # pulled, only current-quality 8B Llama); qwen2.5 → successor qwen3.
        "ollama": ["llama3.3", "llama3.1", "qwen3", "gemma4", "deepseek-r1", "mistral"],
    },
}


def _embedding_entry(provider: str, model: str) -> dict:
    for entry in CATALOG["embedding"].get(provider, []):
        if entry["model"] == model:
            return entry
    raise ValueError(f"Unknown embedding model: {provider}/{model}")


def embedding_dimensions(provider: str, model: str) -> int:
    """Validates the provider/model pair and returns its default dimensions."""
    return _embedding_entry(provider, model)["dimensions"]


def embedding_dimension_options(provider: str, model: str) -> list[int]:
    """Every vector size this model can produce (MRL prefixes + the default)."""
    entry = _embedding_entry(provider, model)
    return list(entry.get("dimension_options", [entry["dimensions"]]))


def resolve_embedding_dimensions(
    provider: str, model: str, requested: int | None = None
) -> int:
    """Validate a requested vector size (None means the model default)."""
    entry = _embedding_entry(provider, model)
    if requested is None:
        return entry["dimensions"]
    options = entry.get("dimension_options", [entry["dimensions"]])
    if requested not in options:
        raise ValueError(
            f"{provider}/{model} supports dimensions {options}, not {requested}"
        )
    return requested


def embedding_change_plan(
    current_provider: str,
    current_model: str,
    current_dimensions: int,
    provider: str,
    model: str,
    dimensions: int,
) -> str:
    """How to migrate a project's vectors to a new embedding config.

    - "keep":     nothing about the vector space changed.
    - "truncate": same MRL model at a smaller size - existing vectors can be
                  cut to the prefix and re-normalized in place, no API calls.
    - "reembed":  a different model (incompatible space) or a larger size (the
                  extra numbers were never stored) - everything must be
                  re-embedded from the text.
    """
    if (provider, model) != (current_provider, current_model):
        return "reembed"
    if dimensions == current_dimensions:
        return "keep"
    if dimensions < current_dimensions and dimensions in embedding_dimension_options(
        provider, model
    ):
        return "truncate"
    return "reembed"


def validate_llm(provider: str, model: str) -> None:
    if model not in CATALOG["llm"].get(provider, []):
        raise ValueError(f"Unknown LLM: {provider}/{model}")


def get_embedder(
    provider: str,
    model: str,
    api_key: str | None = None,
    dimensions: int | None = None,
) -> EmbeddingProvider:
    dimensions = resolve_embedding_dimensions(provider, model, dimensions)
    if provider == "openai":
        from .openai_provider import OpenAIEmbedder

        return OpenAIEmbedder(model, dimensions, api_key)
    if provider == "gemini":
        from .gemini_provider import GeminiEmbedder

        return GeminiEmbedder(model, dimensions, api_key)
    if provider == "ollama":
        from .ollama_provider import OllamaEmbedder

        return OllamaEmbedder(model, dimensions)
    if provider == "sentence_transformers":
        from .st_provider import SentenceTransformersEmbedder

        return SentenceTransformersEmbedder(model, dimensions)
    raise ValueError(f"Unknown embedding provider: {provider}")


def get_llm(provider: str, model: str, api_key: str | None = None) -> LLMProvider:
    validate_llm(provider, model)
    if provider == "openai":
        from .openai_provider import OpenAILLM

        return OpenAILLM(model, api_key)
    if provider == "gemini":
        from .gemini_provider import GeminiLLM

        return GeminiLLM(model, api_key)
    if provider == "anthropic":
        from .anthropic_provider import AnthropicLLM

        return AnthropicLLM(model, api_key)
    if provider == "sarvam":
        from .sarvam_provider import SarvamLLM

        return SarvamLLM(model, api_key)
    if provider == "ollama":
        from .ollama_provider import OllamaLLM

        return OllamaLLM(model)
    raise ValueError(f"Unknown LLM provider: {provider}")
