"""BYOK speech-to-text across every provider that offers it.

Audio ingestion prefers the uploader's OWN provider keys (project override or
account key) over the free fallback. Each factory returns a
``transcribe(data, filename) -> str | None`` callable; failures raise and the
caller moves down the chain, so a wrong guess about one vendor's API can never
break ingestion - the free Google endpoint remains the terminal fallback.

Speech-to-text support by provider:
  * openai  - Whisper via /v1/audio/transcriptions
  * gemini  - native audio understanding (generate_content with inline audio)
  * groq    - hosted whisper-large-v3, OpenAI-compatible endpoint
  * mistral - Voxtral, OpenAI-compatible endpoint
  * sarvam  - Saarika STT (own REST API, Indic languages)
Anthropic, xAI, DeepSeek, Cohere and Azure* have no usable STT surface here.
(*Azure Whisper exists but needs a user-specific deployment name we can't know.)
"""
import io
import logging
import logging
from pathlib import Path

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# Providers with a speech-to-text capability, in default preference order
# (the caller puts the project's own LLM provider first).
STT_PROVIDERS = ["openai", "gemini", "groq", "mistral", "sarvam"]

# OpenAI-compatible /audio/transcriptions vendors: (base_url, model).
_OPENAI_STYLE: dict[str, tuple[str | None, str]] = {
    "openai": (None, settings.audio_transcription_model),
    "groq": ("https://api.groq.com/openai/v1", "whisper-large-v3"),
    "mistral": ("https://api.mistral.ai/v1", "voxtral-mini-latest"),
}

DEFAULT_GEMINI_STT_MODEL = "gemini-2.5-flash"

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

_MIME = {
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".m4a": "audio/aac",  # AAC-in-MP4; closest type Gemini accepts inline
}

from .base import usage_from_gemini, usage_from_openai

logger = logging.getLogger(__name__)

def _audio_mime(filename: str) -> str:
    return _MIME.get(Path(filename).suffix.lower(), "audio/mp3")



def _record(resp, model: str) -> None:
    """Meter one transcription call. Never raises - metering must not be able
    to break an ingest that is otherwise succeeding."""
    try:
        from ..services import embedding_usage

        embedding_usage.record_llm(usage_from_openai(resp, model))
    except Exception:
        logger.debug("Could not meter a transcription", exc_info=True)


def _record_gemini(resp, model: str) -> None:
    try:
        from ..services import embedding_usage

        embedding_usage.record_llm(usage_from_gemini(resp, model))
    except Exception:
        logger.debug("Could not meter a transcription", exc_info=True)


def _openai_style_transcriber(api_key: str, base_url: str | None, model: str):
    from openai import OpenAI

    from .openai_provider import GENERATE_TIMEOUT, MAX_RETRIES

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=GENERATE_TIMEOUT,
        max_retries=MAX_RETRIES,
    )

    def transcribe(data: bytes, filename: str) -> str | None:
        resp = client.audio.transcriptions.create(
            model=model, file=(filename, io.BytesIO(data))
        )
        # whisper-1 reports no usage at all; the gpt-4o-transcribe family does.
        # Recording whatever arrives keeps the honest split: measured where the
        # vendor says so, NULL where it does not - never a fabricated zero.
        _record(resp, model)
        return (getattr(resp, "text", None) or "").strip() or None

    return transcribe


def _gemini_transcriber(api_key: str, model: str):
    def transcribe(data: bytes, filename: str) -> str | None:
        from google.genai import types

        from .gemini_provider import _client

        part = types.Part.from_bytes(data=data, mime_type=_audio_mime(filename))
        resp = _client(api_key).models.generate_content(
            model=model,
            contents=[
                part,
                "Transcribe this audio verbatim. Output only the spoken words, "
                "nothing else.",
            ],
        )
        _record_gemini(resp, model)
        return (resp.text or "").strip() or None

    return transcribe


def _sarvam_transcriber(api_key: str):
    def transcribe(data: bytes, filename: str) -> str | None:
        resp = httpx.post(
            SARVAM_STT_URL,
            headers={"api-subscription-key": api_key},
            files={"file": (filename, io.BytesIO(data), _audio_mime(filename))},
            data={"model": "saarika:v2.5", "language_code": "unknown"},
            timeout=300.0,
        )
        resp.raise_for_status()
        return (resp.json().get("transcript") or "").strip() or None

    return transcribe


def transcriber_for(
    provider: str,
    api_key: str,
    gemini_model: str = DEFAULT_GEMINI_STT_MODEL,
):
    """A ``transcribe(data, filename)`` callable for this provider, or None."""
    if provider in _OPENAI_STYLE:
        base_url, model = _OPENAI_STYLE[provider]
        return _openai_style_transcriber(api_key, base_url, model)
    if provider == "gemini":
        return _gemini_transcriber(api_key, gemini_model)
    if provider == "sarvam":
        return _sarvam_transcriber(api_key)
    return None
