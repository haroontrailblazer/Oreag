"""Google Gemini provider (embeddings + chat) via the unified google-genai SDK."""
from .base import ProviderUnavailableError

EMBED_BATCH_SIZE = 100


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
    def __init__(self, model: str, dimensions: int, api_key: str | None = None):
        self.model = model
        self.dimensions = dimensions
        self.client = _client(api_key)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            resp = self.client.models.embed_content(
                model=self.model, contents=texts[i : i + EMBED_BATCH_SIZE]
            )
            out.extend(e.values for e in resp.embeddings)
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
