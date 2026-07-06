import httpx

from ..config import settings
from .base import ProviderUnavailableError


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
    # Local inference: one model instance serves the whole queue, so oversized
    # batches just stretch a single request toward the timeout on modest
    # hardware. Smaller batches keep progress (and DB commits) steady.
    batch_size = 32

    def __init__(self, model: str, dimensions: int):
        self.model = model
        self.dimensions = dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            data = _post(
                "/api/embed",
                {"model": self.model, "input": texts[i : i + self.batch_size]},
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

    def generate_stream(self, system_prompt: str, user_prompt: str):
        """Yield answer text deltas from Ollama's NDJSON chat stream."""
        import json

        payload = {
            "model": self.model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            with httpx.stream(
                "POST",
                f"{settings.ollama_base_url}/api/chat",
                json=payload,
                timeout=600,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    piece = json.loads(line).get("message", {}).get("content")
                    if piece:
                        yield piece
        except httpx.ConnectError:
            raise ProviderUnavailableError(
                f"Ollama is not reachable at {settings.ollama_base_url} - is Ollama running?"
            )
        except httpx.HTTPStatusError as exc:
            raise ProviderUnavailableError(
                f"Ollama error ({exc.response.status_code}): {exc.response.text[:300]}"
            )
