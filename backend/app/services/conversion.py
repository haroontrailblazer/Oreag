import mimetypes
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf


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


def source_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def is_supported_upload(filename: str) -> bool:
    return source_extension(filename) in SUPPORTED_UPLOAD_EXTENSIONS


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


def convert_to_markdown(data: bytes, filename: str) -> ConvertedDocument:
    """Convert local upload bytes to Markdown with MarkItDown.

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
        raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp.write(data)
            temp_path = temp.name

        result = MarkItDown(enable_plugins=False).convert(temp_path)
        markdown = getattr(result, "text_content", None) or str(result)
        markdown = markdown.strip()
        if not markdown:
            raise ValueError("No extractable text found in this file")
        return ConvertedDocument(
            markdown=markdown,
            page_count=count_pdf_pages(data, filename),
        )
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
