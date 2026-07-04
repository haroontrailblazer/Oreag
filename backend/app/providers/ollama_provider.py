import httpx

from ..config import settings
from .base import ProviderUnavailableError

EMBED_BATCH_SIZE = 64


def _post(path: str, payload: dict, timeout: float) -> dict:
    try:
        resp = httpx.post(
            f"{settings.ollama_base_url}{path}", json=payload, timeout=timeout
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        raise ProviderUnavailableError(
            f"Ollama is not reachable at {settings.ollama_base_url} - is Ollama running?"
        )
    except httpx.HTTPStatusError as exc:
        raise ProviderUnavailableError(
            f"Ollama error ({exc.response.status_code}): {exc.response.text[:300]}"
        )


def is_available() -> bool:
    try:
        httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=2).raise_for_status()
        return True
    except httpx.HTTPError:
        return False


class OllamaEmbedder:
    def __init__(self, model: str, dimensions: int):
        self.model = model
        self.dimensions = dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            data = _post(
                "/api/embed",
                {"model": self.model, "input": texts[i : i + EMBED_BATCH_SIZE]},
                timeout=300,
            )
            out.extend(data["embeddings"])
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class OllamaLLM:
    def __init__(self, model: str):
        self.model = model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        data = _post(
            "/api/chat",
            {
                "model": self.model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=600,
        )
        return data["message"]["content"]
