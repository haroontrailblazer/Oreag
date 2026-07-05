from .base import ProviderUnavailableError

# loaded models are cached per process - sentence-transformers model load is slow
_model_cache: dict[str, object] = {}


def is_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401

        return True
    except ImportError:
        return False


def _load_model(model_name: str):
    if model_name not in _model_cache:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ProviderUnavailableError(
                "sentence-transformers is not installed. Run "
                "'pip install -r requirements-local.txt' (downloads PyTorch, ~2.5 GB)."
            )
        _model_cache[model_name] = SentenceTransformer(model_name)
    return _model_cache[model_name]


class SentenceTransformersEmbedder:
    # In-process encoding (sentence-transformers mini-batches internally); this
    # only sets how many chunks are embedded + committed per ingestion round.
    batch_size = 64

    def __init__(self, model: str, dimensions: int):
        self.model = model
        self.dimensions = dimensions
        self._st = _load_model(model)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._st.encode(texts, normalize_embeddings=True).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]
