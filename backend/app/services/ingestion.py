import logging
import math
import uuid
from datetime import datetime, timezone

import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import delete as sql_delete
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Chunk, File, Project
from ..providers import registry, resolver
from ..providers.registry import (
    embed_batch_size,
    get_embedder,
    prefix_normalize,
)
from . import storage
from .content_version import bump_content_version
from .conversion import (
    AUDIO_EXTENSIONS,
    CONVERSION_VERSION,
    IMAGE_CAPTION_EXTENSIONS,
    ConvertedDocument,
    convert_to_markdown,
    markdown_path_for,
    source_extension,
)

logger = logging.getLogger(__name__)

# Gemini's OpenAI-compatible surface - lets MarkItDown's captioning (which
# speaks the OpenAI chat-completions format) run on Gemini keys too.
GEMINI_OPENAI_COMPAT_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def vision_llm_for(project: Project, api_key: str | None):
    """(client, model) for MarkItDown image captioning, or (None, None).

    Reuses the project's ANSWER model: OpenAI chat models and all Gemini
    models are vision-capable and both speak the OpenAI wire format MarkItDown
    expects. Other providers (Anthropic, local, compat vendors) don't fit that
    slot, so their projects skip captioning and image ingestion fails with a
    clear message instead of a provider 400.
    """
    if not api_key:
        return None, None
    if project.llm_provider == "openai":
        from ..providers.openai_provider import GENERATE_TIMEOUT, MAX_RETRIES

        from openai import OpenAI

        client = OpenAI(api_key=api_key, timeout=GENERATE_TIMEOUT, max_retries=MAX_RETRIES)
        return client, project.llm_model
    if project.llm_provider == "gemini":
        # No key-prefix skip here. "AQ." keys used to be refused captioning
        # outright on the belief they were Vertex-only; they are ordinary AI
        # Studio keys and authenticate fine against this endpoint, so the skip
        # was a pure false negative - it silently disabled image captioning
        # for every user with a modern Gemini key, and conversion.py then
        # reported "No text could be extracted".
        from ..providers.openai_provider import GENERATE_TIMEOUT, MAX_RETRIES

        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=GEMINI_OPENAI_COMPAT_URL,
            timeout=GENERATE_TIMEOUT,
            max_retries=MAX_RETRIES,
        )
        return client, project.llm_model
    return None, None


def audio_transcribers_for(db: Session, project: Project) -> list[tuple[str, object]]:
    """Ordered BYOK transcription chain from the uploader's own keys.

    Every STT-capable provider the uploader holds a key for (project override
    or account key) gets a slot, the project's own answer-model provider
    first - so a Gemini project transcribes with the user's Gemini key, a
    Sarvam project with Saarika, and so on. An empty chain (or every entry
    failing) means conversion falls back to the free Google endpoint.
    """
    from ..providers import transcription

    chain: list[tuple[str, object]] = []
    ordered = [project.llm_provider] + [
        p for p in transcription.STT_PROVIDERS if p != project.llm_provider
    ]
    for provider in ordered:
        if provider not in transcription.STT_PROVIDERS:
            continue
        api_key = resolver.resolve_key_for_provider(db, project, provider)
        if not api_key:
            continue
        gemini_model = (
            project.llm_model
            if provider == "gemini" and project.llm_provider == "gemini"
            else transcription.DEFAULT_GEMINI_STT_MODEL
        )
        transcriber = transcription.transcriber_for(
            provider, api_key, gemini_model=gemini_model
        )
        if transcriber is not None:
            chain.append((provider, transcriber))
    return chain


def parse_pdf(data: bytes) -> list[tuple[int, str]]:
    """Returns (1-based page number, text) for every page with text."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                pages.append((i + 1, text))
        return pages
    finally:
        doc.close()


def recompute_project_status(db: Session, project: Project) -> None:
    # the session runs with autoflush=False, so flush pending file status
    # changes/deletes first - otherwise this SELECT reads stale rows.
    db.flush()
    statuses = set(
        db.scalars(select(File.status).where(File.project_id == project.id)).all()
    )
    if not statuses:
        project.status = "empty"
    elif statuses & {"pending", "processing"}:
        project.status = "indexing"
    elif "failed" in statuses:
        project.status = "error"
    else:
        project.status = "ready"


def _file_still_exists(db: Session, file_id: uuid.UUID) -> bool:
    """Fresh SELECT (bypasses the identity map): the user may delete the file
    from another session while ingestion is mid-flight."""
    return db.scalar(select(File.id).where(File.id == file_id)) is not None


def mark_file_failed(db: Session, file_id: uuid.UUID, message: str) -> None:
    """Best-effort failure marking that NEVER raises.

    The file may have been deleted mid-ingestion; after a rollback, db.get()
    would happily return the stale identity-map object and the follow-up
    commit would explode inside the error handler. An exception escaping this
    background task aborts every queued ingestion behind it - the "delete a
    waiting file and the backend dies" bug.
    """
    try:
        db.rollback()
        db.expunge_all()  # drop stale identity-map entries so get() hits the DB
        file = db.get(File, file_id)
        if file is None:
            logger.info("File %s was deleted during ingestion - skipping", file_id)
            return
        file.status = "failed"
        file.error = message[:500]
        file.conversion_error = message[:500]
        file.conversion_note = None  # a failed file's caveat would only confuse
        # A failed ingest may have committed some chunk batches before dying -
        # drop them so retrieval never serves half-indexed content.
        db.execute(sql_delete(Chunk).where(Chunk.file_id == file.id))
        bump_content_version(db, file.project_id)
        project = db.get(Project, file.project_id)
        if project is not None:
            recompute_project_status(db, project)
        db.commit()
    except Exception:
        logger.exception("Could not mark file %s as failed", file_id)
        db.rollback()


def _reuse_converted_markdown(file: File) -> str | None:
    """Previously converted markdown for this file, or None to convert again.

    Returns None - meaning "just convert it" - for every uncertain case:
      * no markdown was ever stored,
      * it was written by a DIFFERENT conversion pipeline (see
        CONVERSION_VERSION), so it may carry a bug that has since been fixed,
      * the column does not exist yet because migration 0023 has not run,
      * the blob is missing, unreadable, or decodes to nothing.

    Fails open on purpose. This is an optimisation; the correct behaviour when
    anything is unclear is the slower path that definitely works, never a
    failed ingest. An empty result is treated as absent rather than as "this
    file has no text", which would wrongly mark it indexed with zero chunks.
    """
    if not file.markdown_storage_path:
        return None
    try:
        if file.conversion_version != CONVERSION_VERSION:
            return None
    except Exception:  # column missing - migration 0023 not applied
        return None
    try:
        markdown = storage.download(file.markdown_storage_path).decode("utf-8")
    except Exception:
        logger.info(
            "Stored markdown for file %s is unreadable - converting again",
            file.id,
        )
        return None
    return markdown.strip() or None


def ingest_file(file_id: uuid.UUID) -> None:
    """Background task: parse -> chunk -> embed -> store, with status updates.

    Runs in Starlette's threadpool (sync def), so it owns its DB session.
    """
    db = SessionLocal()
    try:
        file = db.get(File, file_id)
        if file is None:
            return
        project = db.get(Project, file.project_id)
        file.status = "processing"
        file.error = None
        project.status = "indexing"
        db.commit()

        # Reuse the markdown from a previous pass when this file has already
        # been converted by THIS pipeline. A re-embed (model switch, or growing
        # a Matryoshka dimension) has to recompute vectors, but the conversion
        # that produced the text is unchanged - and for images and audio that
        # step costs real money on the user's own keys, so repeating it is a
        # second bill for the same work.
        #
        # Only when the version matches: markdown written by an older pipeline
        # may carry a bug that has since been fixed (the 0x00 bytes strip_nul
        # now removes, for one), and silently re-serving it would undo the fix.
        cached_markdown = _reuse_converted_markdown(file)
        if cached_markdown is not None:
            converted = ConvertedDocument(
                markdown=cached_markdown,
                # Both already live on the row from the original conversion;
                # re-deriving them is exactly the work being skipped.
                page_count=file.page_count,
                note=file.conversion_note,
            )
            logger.info("Reusing converted markdown for file %s", file_id)
            source_bytes = None
        else:
            source_bytes = storage.download(file.storage_path)
        # Rich-media conversion runs on the uploader's own keys (BYOK):
        #   images -> AI caption via the project's answer model (OpenAI/Gemini
        #            speak the OpenAI format MarkItDown's captioner expects);
        #   audio  -> speech-to-text through whichever STT-capable provider
        #            keys the uploader holds (own provider first); the free
        #            Google endpoint runs only when the whole chain fails.
        # This whole block is what the markdown reuse above skips - it is the
        # part that spends money.
        if source_bytes is not None:
            extension = source_extension(file.filename)
            llm_client = llm_model = None
            transcribers: list = []
            if extension in IMAGE_CAPTION_EXTENSIONS:
                llm_client, llm_model = vision_llm_for(
                    project, resolver.resolve_llm_key(db, project)
                )
            elif extension in AUDIO_EXTENSIONS:
                transcribers = audio_transcribers_for(db, project)
            converted = convert_to_markdown(
                source_bytes,
                file.filename,
                llm_client=llm_client,
                llm_model=llm_model,
                transcribers=transcribers,
            )

        # The user may have deleted the file while we were converting - bail
        # before uploading markdown / paying for embeddings on a ghost.
        if not _file_still_exists(db, file.id):
            logger.info("File %s deleted during conversion - aborting", file_id)
            return

        file.page_count = converted.page_count
        file.conversion_error = None
        # e.g. "audio used the free fallback endpoint" - shown on the file row
        # and toasted by the Files tab when indexing completes.
        file.conversion_note = converted.note

        # Nothing to write back when the markdown came FROM storage - the blob
        # is already there and byte-identical, so re-uploading it is the other
        # half of the same waste.
        if cached_markdown is None:
            markdown_path = (
                file.markdown_storage_path or markdown_path_for(file.storage_path)
            )
            storage.upload_file(
                markdown_path,
                converted.markdown.encode("utf-8"),
                "text/markdown; charset=utf-8",
                upsert=True,
            )
            file.markdown_storage_path = markdown_path
            # Stamp AFTER a successful write, so a crash between the two never
            # leaves a row claiming markdown that was never stored.
            file.conversion_version = CONVERSION_VERSION

        # per-file overrides fall back to the project defaults
        chunk_size = file.chunk_size or project.chunk_size
        chunk_overlap = (
            file.chunk_overlap if file.chunk_overlap is not None else project.chunk_overlap
        )
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        chunks: list[tuple[int, int | None, str]] = []  # (chunk_index, page_number, content)
        for piece in splitter.split_text(converted.markdown):
            chunks.append((len(chunks), None, piece))
        if not chunks:
            raise ValueError("Document produced no chunks")

        api_key = resolver.resolve_embedding_key(db, project)
        # While a project is SHRUNK, embed at the width its vectors were
        # originally computed at and bank that alongside the active prefix.
        #
        # This is what removes the mixed-state problem rather than handling it:
        # without it, a file uploaded at 1536 has no 3072 numbers, so growing
        # back would leave some chunks restorable and some not - and retrieval
        # compares with <=>, which RAISES on a width mismatch, so a half-restored
        # project breaks search outright rather than degrading.
        #
        # It is free. Embedding APIs bill per TOKEN, not per dimension, so
        # asking for 3072 costs exactly what asking for 1536 costs.
        active_dims = project.embedding_dimensions
        # Via the registry, not read straight off the project: a model switch
        # can leave embedding_native_dimensions at a width the current model
        # rejects, and get_embedder RAISES on that - which would fail EVERY
        # file ingest for the project until someone shrank or grew it again.
        native_dims = registry.usable_native_dimensions(
            project.embedding_provider,
            project.embedding_model,
            project.embedding_native_dimensions,
            active_dims,
        )
        archiving = native_dims > active_dims
        embedder = get_embedder(
            project.embedding_provider,
            project.embedding_model,
            api_key,
            dimensions=native_dims,
        )

        # idempotent re-runs: drop anything from a previous attempt
        db.execute(sql_delete(Chunk).where(Chunk.file_id == file.id))
        db.commit()

        batch_size = embed_batch_size(embedder)
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            vectors = embedder.embed_texts([content for _, _, content in batch])
            rows = [
                {
                    "project_id": project.id,
                    "file_id": file.id,
                    "chunk_index": idx,
                    "page_number": page_number,
                    "content": content,
                    # Active width in `embedding` - it is what search reads, and
                    # what the partial HNSW index is built on. The wider
                    # original goes to the archive, never to `embedding`.
                    "embedding": (
                        prefix_normalize(vector, active_dims) if archiving else vector
                    ),
                }
                for (idx, page_number, content), vector in zip(batch, vectors)
            ]
            if archiving:
                # OMITTED, not set to None, when there is nothing to archive.
                # A key present in the dict makes SQLAlchemy name that column in
                # the INSERT - so carrying "embedding_full": None would reference
                # a column that does not exist until migration 0024 runs, and
                # break EVERY file upload on a database that has not had it
                # applied yet. Absent means the column is never mentioned.
                for row, vector in zip(rows, vectors):
                    row["embedding_full"] = vector
            db.execute(insert(Chunk), rows)
            db.commit()

        file.status = "indexed"
        file.chunk_count = len(chunks)
        file.indexed_at = datetime.now(timezone.utc)
        recompute_project_status(db, project)
        # One atomic invalidation when the file's content becomes searchable -
        # cached answers keep serving the OLD content until this lands.
        bump_content_version(db, project.id)
        db.commit()
        logger.info("Indexed file %s (%d chunks)", file.filename, len(chunks))
    except Exception as exc:
        logger.exception("Ingestion failed for file %s", file_id)
        mark_file_failed(db, file_id, str(exc))
    finally:
        db.close()


# fail_stale_jobs is gone: restarts no longer bulk-fail in-flight work. The
# durable queue (services/ingest_queue.py) re-claims pending rows immediately
# and interrupted (leased) rows when their lease expires.
