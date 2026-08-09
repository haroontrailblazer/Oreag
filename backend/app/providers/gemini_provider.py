"""Google Gemini provider (embeddings + chat) via the unified google-genai SDK."""
import math

from .base import ProviderUnavailableError, ensure_width
from .base import TokenUsage, usage_from_gemini


def l2_normalize(values: list[float]) -> list[float]:
    """Scale a vector to unit length (safe no-op for the zero vector).

    Gemini's Matryoshka sizes below the native 3072 are returned UN-normalized,
    and cosine search assumes unit vectors - so we always normalize locally.
    """
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        return list(values)
    return [v / norm for v in values]


def looks_like_api_key(api_key: str) -> bool:
    """Is this string shaped like a Google API key at all?

    Two prefixes are in circulation and BOTH are ordinary Gemini API keys:
    the legacy Standard key ("AIza...") and the newer Authorization key
    ("AQ.Ab..."), which AI Studio now issues exclusively for new keys.

    This is a credential-TYPE check, not a routing signal - see _client. Its
    only job is to tell an API key apart from the other Google credentials
    people reach for (gcloud / Gemini CLI OAuth tokens, service-account JSON),
    none of which google-genai can accept as api_key.
    """
    return api_key.startswith(("AIza", "AQ."))


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
    from google.genai import types

    # google-genai has NO default timeout: a hung upstream would pin the calling
    # thread indefinitely. Timeout is in milliseconds; 300s leaves room for a
    # full-budget non-streaming generation (the client is shared with the
    # embedder, which never gets near it).
    http_options = types.HttpOptions(timeout=300_000)
    # ONE backend for every API key.
    #
    # There used to be a branch here sending "AQ."-prefixed keys to Vertex, on
    # the theory that the prefix marked a Vertex express key. It does not.
    # Google AI Studio now issues "AQ." Authorization keys EXCLUSIVELY for new
    # keys, so that rule misrouted the ordinary key of every newly-onboarded
    # user to Vertex - where it 403s with SERVICE_DISABLED unless that user
    # happens to have aiplatform.googleapis.com enabled in the backing GCP
    # project. The symptom was "my valid Gemini key does not work", with an
    # error naming a Google Cloud service the user had never heard of.
    #
    # Measured against the live API with a real AQ. key: it lists 42 models
    # here, embeds successfully, and hits FREE-TIER 429s - which a Vertex key
    # would not have. The old docstring's claim that such a key 401s with
    # ACCESS_TOKEN_TYPE_UNSUPPORTED described a transitional Google-side
    # provisioning bug, not a key type.
    #
    # google-genai itself does no prefix inspection anywhere in its 30 modules;
    # it treats keys as opaque and picks the backend purely from the vertexai
    # flag. Credentials are opaque - do not pattern-match them for routing.
    return genai.Client(api_key=api_key, http_options=http_options)


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
        return ensure_width(out, self.dimensions, "Gemini", self.model)

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class GeminiLLM:
    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.client = _client(api_key)

    def _config(self, system_prompt: str):
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0,
        )

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return self.generate_with_usage(system_prompt, user_prompt)[0]

    def generate_with_usage(
        self, system_prompt: str, user_prompt: str
    ) -> tuple[str, TokenUsage]:
        resp = self.client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=self._config(system_prompt),
        )
        return resp.text or "", usage_from_gemini(resp, self.model)

    def generate_stream(self, system_prompt: str, user_prompt: str):
        """Yield answer text deltas as Gemini produces them."""
        for chunk in self.client.models.generate_content_stream(
            model=self.model,
            contents=user_prompt,
            config=self._config(system_prompt),
        ):
            if chunk.text:
                yield chunk.text
