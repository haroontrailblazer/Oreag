"""Anthropic Claude provider (chat only — Anthropic has no embedding models)."""
from .base import ProviderUnavailableError

MAX_TOKENS = 1024


def _client(api_key: str | None):
    if not api_key:
        raise ProviderUnavailableError(
            "No Anthropic API key configured. Add one in Settings → API keys "
            "or set a per-project key."
        )
    try:
        import anthropic
    except ImportError:
        raise ProviderUnavailableError(
            "anthropic is not installed. Run 'pip install -r requirements.txt'."
        )
    return anthropic.Anthropic(api_key=api_key)


class AnthropicLLM:
    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.client = _client(api_key)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return resp.content[0].text if resp.content else ""
