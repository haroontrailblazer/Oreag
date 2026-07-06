from openai import OpenAI

from .base import ProviderUnavailableError


def _client(api_key: str | None) -> OpenAI:
    if not api_key:
        raise ProviderUnavailableError(
            "No OpenAI API key configured. Add one in Settings → API keys "
            "or set a per-project key."
        )
    return OpenAI(api_key=api_key)


class OpenAIEmbedder:
    # OpenAI accepts up to 2048 inputs per embeddings request; 100 keeps each
    # request fast and the blast radius of a failed call small.
    batch_size = 100

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
        for i in range(0, len(texts), self.batch_size):
            resp = self.client.embeddings.create(
                model=self.model, input=texts[i : i + self.batch_size], **params
            )
            out.extend(item.embedding for item in resp.data)
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class OpenAILLM:
    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.client = _client(api_key)

    def _params(self) -> dict:
        # GPT-5.x reasoning models reject `temperature` unless reasoning_effort
        # is "none" (gpt-5.5 defaults to "medium"). Pin effort to "none" for
        # fast, RAG-suited answers and skip temperature there; legacy 4o-era
        # models don't accept reasoning_effort, so they keep temperature=0.
        if self.model.startswith("gpt-5"):
            return {"reasoning_effort": "none"}
        return {"temperature": 0}

    def _messages(self, system_prompt: str, user_prompt: str) -> list[dict]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=self._messages(system_prompt, user_prompt),
            **self._params(),
        )
        return resp.choices[0].message.content or ""

    def generate_stream(self, system_prompt: str, user_prompt: str):
        """Yield answer text deltas as the model produces them."""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=self._messages(system_prompt, user_prompt),
            stream=True,
            **self._params(),
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
