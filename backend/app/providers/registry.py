from functools import lru_cache

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
        # Azure OpenAI: the "model" is the DEPLOYMENT name. Oreag expects
        # deployments named after the underlying model (the common default).
        "azure": [
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
            {"model": "text-embedding-ada-002", "dimensions": 1536},
        ],
        "mistral": [
            {"model": "mistral-embed", "dimensions": 1024},
        ],
        "voyage": [
            {"model": "voyage-3.5", "dimensions": 1024},
            {"model": "voyage-3.5-lite", "dimensions": 1024},
            {"model": "voyage-3-large", "dimensions": 1024},
        ],
        "jina": [
            # jina-embeddings-v3 is Matryoshka-trained and takes the standard
            # `dimensions` parameter.
            {
                "model": "jina-embeddings-v3",
                "dimensions": 1024,
                "dimension_options": [256, 512, 1024],
            },
        ],
        "together": [
            {"model": "BAAI/bge-large-en-v1.5", "dimensions": 1024},
        ],
        "fireworks": [
            {"model": "nomic-ai/nomic-embed-text-v1.5", "dimensions": 768},
        ],
        "cohere": [
            # embed-v4.0 is Matryoshka-trained; Cohere's OpenAI-compatible
            # endpoint accepts the standard `dimensions` parameter for it.
            {
                "model": "embed-v4.0",
                "dimensions": 1536,
                "dimension_options": [256, 512, 1024, 1536],
            },
            {"model": "embed-multilingual-v3.0", "dimensions": 1024},
        ],
        "ollama": [
            {"model": "nomic-embed-text", "dimensions": 768},
            {"model": "mxbai-embed-large", "dimensions": 1024},
        ],
        "lmstudio": [
            {"model": "text-embedding-nomic-embed-text-v1.5", "dimensions": 768},
            {"model": "text-embedding-all-minilm-l6-v2", "dimensions": 384},
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
        # Azure OpenAI deployments (named after the model) - the full OpenAI
        # lineup Azure serves, current GPT-5.x through the still-common 4o pair.
        "azure": [
            "gpt-5.4-mini",
            "gpt-5.4",
            "gpt-5.5",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4o",
            "gpt-4o-mini",
        ],
        # OpenAI-compatible cloud vendors: stable aliases only, never previews.
        "xai": [
            "grok-4",
            "grok-4-fast-reasoning",
            "grok-4-fast-non-reasoning",
            "grok-3-mini",
        ],
        "groq": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
        ],
        "mistral": [
            "mistral-large-latest",
            "mistral-medium-latest",
            "mistral-small-latest",
        ],
        "deepseek": ["deepseek-chat", "deepseek-reasoner"],
        "cohere": ["command-a-03-2025", "command-r-plus-08-2024"],
        "together": [
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
            "deepseek-ai/DeepSeek-V3",
        ],
        "fireworks": [
            "accounts/fireworks/models/llama-v3p3-70b-instruct",
            "accounts/fireworks/models/deepseek-v3",
        ],
        # OpenRouter is an aggregator - one key, many upstream models.
        "openrouter": [
            "openai/gpt-4o-mini",
            "anthropic/claude-sonnet-4.5",
            "google/gemini-2.5-flash",
            "meta-llama/llama-3.3-70b-instruct",
            "deepseek/deepseek-chat",
        ],
        "perplexity": ["sonar", "sonar-pro", "sonar-reasoning"],
        # Local tags never 404; headline current models. llama3.1 stays (most
        # pulled, only current-quality 8B Llama); qwen2.5 → successor qwen3.
        "ollama": ["llama3.3", "llama3.1", "qwen3", "gemma4", "deepseek-r1", "mistral"],
        # LM Studio community catalog ids for its most-downloaded models.
        "lmstudio": ["openai/gpt-oss-20b", "qwen/qwen3-8b", "google/gemma-3-12b"],
    },
}

# OpenAI-compatible vendors served by the shared compat provider. LM Studio
# (local base URL, keyless) and Azure (per-user endpoint inside the stored
# credential) are handled separately.
COMPAT_BASE_URLS = {
    "xai": "https://api.x.ai/v1",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "cohere": "https://api.cohere.ai/compatibility/v1",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "perplexity": "https://api.perplexity.ai",
    "voyage": "https://api.voyageai.com/v1",
    "jina": "https://api.jina.ai/v1",
}

_PROVIDER_LABELS = {
    "xai": "xAI",
    "groq": "Groq",
    "mistral": "Mistral",
    "deepseek": "DeepSeek",
    "cohere": "Cohere",
    "together": "Together AI",
    "fireworks": "Fireworks AI",
    "openrouter": "OpenRouter",
    "perplexity": "Perplexity",
    "voyage": "Voyage AI",
    "jina": "Jina AI",
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


# Providers are stateless wrappers around thread-safe SDK clients, so instances
# are memoized per (provider, model, key, dims): the underlying httpx connection
# pools get reused across requests instead of paying a fresh TLS handshake per
# call (and sentence-transformers keeps its model loaded). Errors (e.g. missing
# key) are never cached - lru_cache only stores successful returns.
@lru_cache(maxsize=128)
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
    if provider == "azure":
        from .openai_compat import CompatEmbedder, azure_base_url, split_azure_credential

        endpoint, key = split_azure_credential(api_key)
        return CompatEmbedder(
            model,
            dimensions,
            key,
            base_url=azure_base_url(endpoint),
            provider_label="Azure OpenAI",
            send_dimensions=len(embedding_dimension_options(provider, model)) > 1,
        )
    if provider in COMPAT_BASE_URLS:
        from .openai_compat import CompatEmbedder

        return CompatEmbedder(
            model,
            dimensions,
            api_key,
            base_url=COMPAT_BASE_URLS[provider],
            provider_label=_PROVIDER_LABELS[provider],
            # MRL models take the standard `dimensions` param; others 400 on it.
            send_dimensions=len(embedding_dimension_options(provider, model)) > 1,
        )
    if provider == "lmstudio":
        from ..config import settings
        from .openai_compat import CompatEmbedder

        return CompatEmbedder(
            model,
            dimensions,
            api_key="lm-studio",  # local server ignores the key but the SDK wants one
            base_url=settings.lmstudio_base_url,
            provider_label="LM Studio",
            batch_size=32,  # local inference - same reasoning as Ollama
        )
    if provider == "ollama":
        from .ollama_provider import OllamaEmbedder

        return OllamaEmbedder(model, dimensions)
    if provider == "sentence_transformers":
        from .st_provider import SentenceTransformersEmbedder

        return SentenceTransformersEmbedder(model, dimensions)
    raise ValueError(f"Unknown embedding provider: {provider}")


@lru_cache(maxsize=128)
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
    if provider == "azure":
        from .openai_compat import CompatLLM, azure_base_url, split_azure_credential

        endpoint, key = split_azure_credential(api_key)
        return CompatLLM(
            model,
            key,
            base_url=azure_base_url(endpoint),
            provider_label="Azure OpenAI",
        )
    if provider in COMPAT_BASE_URLS:
        from .openai_compat import CompatLLM

        return CompatLLM(
            model,
            api_key,
            base_url=COMPAT_BASE_URLS[provider],
            provider_label=_PROVIDER_LABELS[provider],
        )
    if provider == "lmstudio":
        from ..config import settings
        from .openai_compat import CompatLLM

        return CompatLLM(
            model,
            api_key="lm-studio",  # local server ignores the key but the SDK wants one
            base_url=settings.lmstudio_base_url,
            provider_label="LM Studio",
        )
    if provider == "ollama":
        from .ollama_provider import OllamaLLM

        return OllamaLLM(model)
    raise ValueError(f"Unknown LLM provider: {provider}")
