from openai import OpenAI

from .base import ProviderUnavailableError

EMBED_BATCH_SIZE = 100


def _client(api_key: str | None) -> OpenAI:
    if not api_key:
        raise ProviderUnavailableError(
            "No OpenAI API key configured. Add one in Settings → API keys "
            "or set a per-project key."
        )
    return OpenAI(api_key=api_key)


class OpenAIEmbedder:
    def __init__(self, model: str, dimensions: int, api_key: str | None = None):
        self.model = model
        self.dimensions = dimensions
        self.client = _client(api_key)
        # text-embedding-3-* are Matryoshka models: the API can return any
        # requested prefix size. Older models reject the parameter.
        self._sized = model.startswith("text-embedding-3")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        params: dict = {"dimensions": self.dimensions} if self._sized else {}
        out: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            resp = self.client.embeddings.create(
                model=self.model, input=texts[i : i + EMBED_BATCH_SIZE], **params
            )
            out.extend(item.embedding for item in resp.data)
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class OpenAILLM:
    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.client = _client(api_key)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        # GPT-5.x reasoning models reject `temperature` unless reasoning_effort
        # is "none" (gpt-5.5 defaults to "medium"). Pin effort to "none" for
        # fast, RAG-suited answers and skip temperature there; legacy 4o-era
        # models don't accept reasoning_effort, so they keep temperature=0.
        params: dict = {}
        if self.model.startswith("gpt-5"):
            params["reasoning_effort"] = "none"
        else:
            params["temperature"] = 0
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **params,
        )
        return resp.choices[0].message.content or ""
