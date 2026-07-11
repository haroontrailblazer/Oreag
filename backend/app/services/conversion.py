import logging
import mimetypes
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)


# MarkItDown's ImageConverter handles exactly these; it extracts embedded
# metadata (needs exiftool) and, when a vision LLM client is wired in, an AI
# caption. Images carry no machine-readable text otherwise, so without a
# caption they convert to nothing.
IMAGE_CAPTION_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# The caption becomes the document's searchable text, so ask for verbatim
# transcription too - screenshots are mostly uploaded FOR the text in them.
IMAGE_CAPTION_PROMPT = (
    "Describe this image in detail. If the image contains any text, transcribe "
    "all of it verbatim - names, numbers, labels, table contents and captions "
    "exactly as written. Then describe any charts, diagrams or notable visual "
    "elements and what they convey."
)

# BYOK transcription handles these through the uploader's own provider keys
# (OpenAI/Gemini/Groq/Mistral/Sarvam - see providers/transcription.py); only
# when no key-backed transcriber succeeds do they fall through to MarkItDown's
# free Google Web Speech endpoint, which suits only short clear clips.
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a"}

SUPPORTED_UPLOAD_EXTENSIONS = {
    ".bmp",
    ".csv",
    ".docx",
    ".eml",
    ".epub",
    ".gif",
    ".htm",
    ".html",
    ".jpeg",
    ".jpg",
    ".json",
    ".m4a",
    ".md",
    ".mp3",
    ".odp",
    ".ods",
    ".odt",
    ".pdf",
    ".png",
    ".pptx",
    ".rtf",
    ".tif",
    ".tiff",
    ".txt",
    ".wav",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
}


@dataclass(frozen=True)
class ConvertedDocument:
    markdown: str
    page_count: int | None
    # Non-fatal caveat the uploader should see (e.g. audio used the free
    # fallback endpoint) - surfaced on the file row and toasted by the UI.
    note: str | None = None


def source_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def is_supported_upload(filename: str) -> bool:
    return source_extension(filename) in SUPPORTED_UPLOAD_EXTENSIONS


def try_decode_text(data: bytes) -> str | None:
    """Best-effort text decode for files outside the MarkItDown allowlist.

    NUL bytes in the head mark the file as binary (the git heuristic); text
    without them decodes as UTF-8 or, failing that, cp1252 so single-byte
    legacy files still ingest.
    """
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def is_ingestable(filename: str, data: bytes) -> bool:
    """Anything convertible is ingestable: allowlisted formats via MarkItDown,
    every other extension (or none) as plain text - only opaque binary fails."""
    return is_supported_upload(filename) or try_decode_text(data) is not None


def content_type_for(filename: str, fallback: str | None = None) -> str:
    return fallback or mimetypes.guess_type(filename)[0] or "application/octet-stream"


def markdown_path_for(storage_path: str) -> str:
    return f"{storage_path}.md"


def count_pdf_pages(data: bytes, filename: str) -> int | None:
    if source_extension(filename) != ".pdf":
        return None
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        return doc.page_count
    finally:
        doc.close()


def _transcribe_with_byok(transcribers, data: bytes, filename: str) -> str | None:
    """Transcribe audio through the uploader's own provider keys, in order.

    ``transcribers`` is a list of (provider_name, transcribe_fn) built from
    whichever STT-capable keys the uploader has. Each is tried in turn; any
    failure (no audio access on the key, file too large for that vendor, a
    brief outage) just moves to the next. Returns None when the whole chain is
    exhausted so the caller falls back to MarkItDown's free Google endpoint -
    a degraded transcription beats a failed ingestion.
    """
    for provider, transcribe in transcribers:
        try:
            text = transcribe(data, filename)
        except Exception:
            logger.warning(
                "%s transcription failed for %s - trying the next provider",
                provider,
                filename,
                exc_info=True,
            )
            continue
        if text:
            logger.info("Transcribed %s with the uploader's %s key", filename, provider)
            return text
        logger.warning("%s transcription returned no text for %s", provider, filename)
    return None


def convert_to_markdown(
    data: bytes,
    filename: str,
    llm_client=None,
    llm_model: str | None = None,
    transcribers=None,
) -> ConvertedDocument:
    """Convert local upload bytes to Markdown with MarkItDown.

    ``llm_client``/``llm_model`` (an OpenAI-compatible SDK client and a
    vision-capable model) enable MarkItDown's AI image captioning: the caption
    - including verbatim transcription of any text in the image - becomes the
    document text. Without them, images yield only embedded metadata, which
    for photos/screenshots is usually nothing.

    ``transcribers`` (ordered (provider, fn) pairs from the uploader's own
    STT-capable keys) routes audio through BYOK transcription; the free Google
    Web Speech endpoint runs only when the whole chain yields nothing.

    URLs and remote paths are intentionally unsupported: callers pass already
    uploaded bytes, which keeps conversion scoped to project-owned files.
    """
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise RuntimeError(
            "MarkItDown is not installed. Install backend requirements again."
        ) from exc

    suffix = source_extension(filename)
    if suffix not in SUPPORTED_UPLOAD_EXTENSIONS:
        # Everything else ingests as plain text (code, configs, logs, files
        # without an extension) so questions can search every uploaded file.
        text = try_decode_text(data)
        if text is None:
            raise ValueError(f"Unsupported binary file type: {suffix or 'unknown'}")
        text = text.strip()
        if not text:
            raise ValueError("No extractable text found in this file")
        return ConvertedDocument(markdown=text, page_count=None)

    # Audio: BYOK transcription first; the free Google endpoint is the
    # fallback - and when it runs, the file carries a note saying so, because
    # the uploader should know their keys weren't used (quality + privacy).
    audio_note = None
    if suffix in AUDIO_EXTENSIONS:
        if transcribers:
            transcript = _transcribe_with_byok(transcribers, data, filename)
            if transcript:
                return ConvertedDocument(markdown=transcript, page_count=None)
            audio_note = (
                "Transcribed with the free Google speech endpoint: your "
                f"provider key{'s' if len(transcribers) > 1 else ''} "
                f"({', '.join(name for name, _ in transcribers)}) could not "
                "transcribe this file."
            )
        else:
            audio_note = (
                "Transcribed with the free Google speech endpoint: none of "
                "your API keys support speech-to-text. Add an OpenAI, Gemini, "
                "Groq, Mistral or Sarvam key for reliable transcription."
            )

    md_kwargs: dict = {"enable_plugins": False}
    if llm_client is not None and llm_model:
        md_kwargs.update(
            llm_client=llm_client,
            llm_model=llm_model,
            llm_prompt=IMAGE_CAPTION_PROMPT,
        )

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp.write(data)
            temp_path = temp.name

        result = MarkItDown(**md_kwargs).convert(temp_path)
        markdown = getattr(result, "text_content", None) or str(result)
        markdown = markdown.strip()
        if not markdown:
            if suffix in IMAGE_CAPTION_EXTENSIONS:
                # The image itself is just pixels; text comes from AI
                # captioning, which needs a vision-capable answer model.
                raise ValueError(
                    "No text could be extracted from this image. AI image "
                    "captioning needs the project's answer model to be an "
                    "OpenAI or Gemini model with a usable key."
                )
            raise ValueError("No extractable text found in this file")
        return ConvertedDocument(
            markdown=markdown,
            page_count=count_pdf_pages(data, filename),
            note=audio_note,
        )
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
