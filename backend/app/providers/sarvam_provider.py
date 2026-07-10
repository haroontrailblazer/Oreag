"""Sarvam AI provider (chat only). Sarvam exposes an OpenAI-compatible
chat-completions API, so we reuse the OpenAI SDK pointed at Sarvam's base URL."""
import httpx
from openai import OpenAI

from .base import ProviderUnavailableError

SARVAM_BASE_URL = "https://api.sarvam.ai/v1"


def _client(api_key: str | None) -> OpenAI:
    if not api_key:
        raise ProviderUnavailableError(
            "No Sarvam AI API key configured. Add one in Settings → API keys "
            "or set a per-project key."
        )
    # Bound the SDK defaults (600s, 2 retries) - see openai_provider.
    return OpenAI(
        api_key=api_key,
        base_url=SARVAM_BASE_URL,
        timeout=httpx.Timeout(300.0, connect=5.0),
        max_retries=1,
    )


class SarvamLLM:
    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.client = _client(api_key)

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

    def generate_stream(self, system_prompt: str, user_prompt: str):
        """Yield answer text deltas as they arrive (Sarvam is OpenAI-compatible)."""
        stream = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            stream=True,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
