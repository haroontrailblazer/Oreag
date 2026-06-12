from .base import EmbeddingProvider, LLMProvider

# Single source of truth for what the wizard offers and what the backend accepts.
CATALOG: dict = {
    "embedding": {
        "openai": [
            {"model": "text-embedding-3-small", "dimensions": 1536},
            {"model": "text-embedding-3-large", "dimensions": 3072},
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
        "openai": ["gpt-4o-mini", "gpt-4o"],
        "ollama": ["llama3.1", "mistral", "qwen2.5"],
    },
}


def embedding_dimensions(provider: str, model: str) -> int:
    """Validates the provider/model pair and returns its dimensions."""
    for entry in CATALOG["embedding"].get(provider, []):
        if entry["model"] == model:
            return entry["dimensions"]
    raise ValueError(f"Unknown embedding model: {provider}/{model}")


def validate_llm(provider: str, model: str) -> None:
    if model not in CATALOG["llm"].get(provider, []):
        raise ValueError(f"Unknown LLM: {provider}/{model}")


def get_embedder(provider: str, model: str) -> EmbeddingProvider:
    dimensions = embedding_dimensions(provider, model)
    if provider == "openai":
        from .openai_provider import OpenAIEmbedder

        return OpenAIEmbedder(model, dimensions)
    if provider == "ollama":
        from .ollama_provider import OllamaEmbedder

        return OllamaEmbedder(model, dimensions)
    if provider == "sentence_transformers":
        from .st_provider import SentenceTransformersEmbedder

        return SentenceTransformersEmbedder(model, dimensions)
    raise ValueError(f"Unknown embedding provider: {provider}")


def get_llm(provider: str, model: str) -> LLMProvider:
    validate_llm(provider, model)
    if provider == "openai":
        from .openai_provider import OpenAILLM

        return OpenAILLM(model)
    if provider == "ollama":
        from .ollama_provider import OllamaLLM

        return OllamaLLM(model)
    raise ValueError(f"Unknown LLM provider: {provider}")
