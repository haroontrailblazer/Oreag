from openai import OpenAI

from ..config import settings
from .base import ProviderUnavailableError

EMBED_BATCH_SIZE = 100


def _client() -> OpenAI:
    if not settings.openai_api_key:
        raise ProviderUnavailableError(
            "OPENAI_API_KEY is not configured on the server"
        )
    return OpenAI(api_key=settings.openai_api_key)


class OpenAIEmbedder:
    def __init__(self, model: str, dimensions: int):
        self.model = model
        self.dimensions = dimensions
        self.client = _client()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            resp = self.client.embeddings.create(
                model=self.model, input=texts[i : i + EMBED_BATCH_SIZE]
            )
            out.extend(item.embedding for item in resp.data)
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class OpenAILLM:
    def __init__(self, model: str):
        self.model = model
        self.client = _client()

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return resp.choices[0].message.content or ""
