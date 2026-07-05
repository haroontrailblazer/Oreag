import logging
import uuid
from datetime import datetime, timezone

import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import delete as sql_delete
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Chunk, File, Project
from ..providers import resolver
from ..providers.registry import get_embedder
from . import storage
from .conversion import convert_to_markdown, markdown_path_for

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 64


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
        project = db.get(Project, file.project_id)
        if project is not None:
            recompute_project_status(db, project)
        db.commit()
    except Exception:
        logger.exception("Could not mark file %s as failed", file_id)
        db.rollback()


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

        source_bytes = storage.download(file.storage_path)
        converted = convert_to_markdown(source_bytes, file.filename)

        # The user may have deleted the file while we were converting - bail
        # before uploading markdown / paying for embeddings on a ghost.
        if not _file_still_exists(db, file.id):
            logger.info("File %s deleted during conversion - aborting", file_id)
            return

        file.page_count = converted.page_count
        file.conversion_error = None

        markdown_path = file.markdown_storage_path or markdown_path_for(file.storage_path)
        storage.upload_file(
            markdown_path,
            converted.markdown.encode("utf-8"),
            "text/markdown; charset=utf-8",
            upsert=True,
        )
        file.markdown_storage_path = markdown_path

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
        embedder = get_embedder(
            project.embedding_provider,
            project.embedding_model,
            api_key,
            dimensions=project.embedding_dimensions,
        )

        # idempotent re-runs: drop anything from a previous attempt
        db.execute(sql_delete(Chunk).where(Chunk.file_id == file.id))
        db.commit()

        for i in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[i : i + EMBED_BATCH_SIZE]
            vectors = embedder.embed_texts([content for _, _, content in batch])
            db.execute(
                insert(Chunk),
                [
                    {
                        "project_id": project.id,
                        "file_id": file.id,
                        "chunk_index": idx,
                        "page_number": page_number,
                        "content": content,
                        "embedding": vector,
                    }
                    for (idx, page_number, content), vector in zip(batch, vectors)
                ],
            )
            db.commit()

        file.status = "indexed"
        file.chunk_count = len(chunks)
        file.indexed_at = datetime.now(timezone.utc)
        recompute_project_status(db, project)
        db.commit()
        logger.info("Indexed file %s (%d chunks)", file.filename, len(chunks))
    except Exception as exc:
        logger.exception("Ingestion failed for file %s", file_id)
        mark_file_failed(db, file_id, str(exc))
    finally:
        db.close()


def fail_stale_jobs() -> None:
    """Startup hook: jobs interrupted by a server restart can never finish."""
    db = SessionLocal()
    try:
        stale = db.scalars(
            select(File).where(File.status.in_(["pending", "processing"]))
        ).all()
        if not stale:
            return
        for file in stale:
            file.status = "failed"
            file.error = "Interrupted by server restart - retry from the Files tab"
        for project_id in {f.project_id for f in stale}:
            project = db.get(Project, project_id)
            if project is not None:
                recompute_project_status(db, project)
        db.commit()
        logger.warning("Marked %d interrupted file(s) as failed", len(stale))
    finally:
        db.close()
