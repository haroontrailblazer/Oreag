"""Generic provider for OpenAI-compatible APIs.

xAI (Grok), Groq, Mistral, DeepSeek, Cohere and LM Studio all expose the
OpenAI chat-completions/embeddings wire format, so one implementation - the
OpenAI SDK pointed at each vendor's base URL - serves them all. Vendor
specifics (base URL, key requirements, batch size) are injected by the
registry.
"""
import httpx
from openai import OpenAI

from ..config import settings
from .base import ProviderUnavailableError


def _client(api_key: str | None, base_url: str, provider_label: str) -> OpenAI:
    if not api_key:
        raise ProviderUnavailableError(
            f"No {provider_label} API key configured. Add one in Settings → "
            "API keys or set a per-project key."
        )
    return OpenAI(api_key=api_key, base_url=base_url)


# Azure OpenAI needs a per-user resource endpoint alongside the key. Both are
# stored as ONE encrypted credential ("endpoint|key") so the whole key
# resolution chain (account keys, per-project overrides) works unchanged.
def join_azure_credential(endpoint: str, key: str) -> str:
    return f"{endpoint.rstrip('/')}|{key}"


def split_azure_credential(credential: str | None) -> tuple[str, str]:
    if not credential or "|" not in credential:
        raise ProviderUnavailableError(
            "Azure OpenAI needs a resource endpoint and a key. Re-add the "
            "Azure key in Settings → API keys (for a per-project override, "
            "paste 'https://<resource>.openai.azure.com|<key>')."
        )
    endpoint, _, key = credential.partition("|")
    return endpoint.rstrip("/"), key


def azure_base_url(endpoint: str) -> str:
    """Azure's OpenAI-v1-compatible surface lives under /openai/v1."""
    return f"{endpoint.rstrip('/')}/openai/v1"


def lmstudio_is_available() -> bool:
    """Probe the local LM Studio server (mirrors the Ollama probe)."""
    try:
        httpx.get(f"{settings.lmstudio_base_url}/models", timeout=2).raise_for_status()
        return True
    except httpx.HTTPError:
        return False


class CompatLLM:
    def __init__(
        self,
        model: str,
        api_key: str | None,
        base_url: str,
        provider_label: str,
    ):
        self.model = model
        self.client = _client(api_key, base_url, provider_label)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        # No temperature: several of these vendors serve reasoning models that
        # reject sampling params, and each vendor's default is sane.
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return resp.choices[0].message.content or ""

    def generate_stream(self, system_prompt: str, user_prompt: str):
        """Yield answer text deltas as the model produces them."""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


class CompatEmbedder:
    def __init__(
        self,
        model: str,
        dimensions: int,
        api_key: str | None,
        base_url: str,
        provider_label: str,
        send_dimensions: bool = False,
        batch_size: int = 64,
    ):
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        # Only Matryoshka-capable models accept a dimensions param; sending it
        # to others is a 400 on most vendors.
        self._send_dimensions = send_dimensions
        self.client = _client(api_key, base_url, provider_label)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        params: dict = {"dimensions": self.dimensions} if self._send_dimensions else {}
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            resp = self.client.embeddings.create(
                model=self.model, input=texts[i : i + self.batch_size], **params
            )
            out.extend(item.embedding for item in resp.data)
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]
