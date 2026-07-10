"""Anthropic Claude provider (chat only - Anthropic has no embedding models)."""
from .base import ProviderUnavailableError

# Big enough for the agentic loop's long exam-style answers; small enough to
# stay well under non-streaming SDK timeouts.
MAX_TOKENS = 8192


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
    import httpx

    # Bound the SDK defaults (600s, 2 retries) so a hung upstream can't pin a
    # threadpool thread for minutes; streaming applies `read` per delta. 300s
    # read matches the SDK's own sizing for the 8192-token budget (~230s) -
    # a scalar timeout would also regress connect from 5s to the full value.
    return anthropic.Anthropic(
        api_key=api_key,
        timeout=httpx.Timeout(300.0, connect=5.0),
        max_retries=1,
    )


class AnthropicLLM:
    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.client = _client(api_key)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        # No `temperature`: it was removed on Claude Sonnet 5 / Opus 4.8 and
        # returns a 400 if sent; omitting it works on every model.
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return resp.content[0].text if resp.content else ""

    def generate_stream(self, system_prompt: str, user_prompt: str):
        """Yield answer text deltas as Claude produces them."""
        with self.client.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            yield from stream.text_stream
