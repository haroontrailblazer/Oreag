"""Google Gemini provider (embeddings + chat) via the unified google-genai SDK."""
import math

from .base import ProviderUnavailableError


def l2_normalize(values: list[float]) -> list[float]:
    """Scale a vector to unit length (safe no-op for the zero vector).

    Gemini's Matryoshka sizes below the native 3072 are returned UN-normalized,
    and cosine search assumes unit vectors - so we always normalize locally.
    """
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        return list(values)
    return [v / norm for v in values]


def _client(api_key: str | None):
    if not api_key:
        raise ProviderUnavailableError(
            "No Gemini API key configured. Add one in Settings → API keys "
            "or set a per-project key."
        )
    try:
        from google import genai
    except ImportError:
        raise ProviderUnavailableError(
            "google-genai is not installed. Run 'pip install -r requirements.txt'."
        )
    return genai.Client(api_key=api_key)


class GeminiEmbedder:
    # Gemini's embedding endpoint caps at 100 contents per request.
    batch_size = 100

    def __init__(self, model: str, dimensions: int, api_key: str | None = None):
        self.model = model
        self.dimensions = dimensions
        self.client = _client(api_key)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        from google.genai import types

        config = types.EmbedContentConfig(output_dimensionality=self.dimensions)
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            resp = self.client.models.embed_content(
                model=self.model,
                contents=texts[i : i + self.batch_size],
                config=config,
            )
            out.extend(l2_normalize(e.values) for e in resp.embeddings)
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class GeminiLLM:
    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.client = _client(api_key)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        from google.genai import types

        resp = self.client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0,
            ),
        )
        return resp.text or ""
