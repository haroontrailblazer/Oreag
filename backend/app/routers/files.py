import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from fastapi import File as FastAPIFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from .. import crypto
from ..config import settings
from ..db import get_db
from ..models import Chunk, File, Project
from ..providers import registry
from ..schemas import FileOut, ReindexRequest
from ..services import storage
from ..services.conversion import content_type_for, is_ingestable, source_extension
from ..services.ingestion import ingest_file, recompute_project_status
from ..services.memory import reembed_project_memories
from .deps import get_owned_project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["files"])

# Matryoshka fast path: same-model dimension shrink keeps every stored vector -
# cut to the prefix and re-normalize, entirely in SQL (pgvector 0.7+).
_TRUNCATE_CHUNKS_SQL = sql_text(
    "UPDATE chunks SET embedding = l2_normalize(subvector(embedding, 1, :dims)) "
    "WHERE project_id = :project_id AND embedding IS NOT NULL"
)
_TRUNCATE_MEMORIES_SQL = sql_text(
    "UPDATE memories SET embedding = l2_normalize(subvector(embedding, 1, :dims)) "
    "WHERE project_id = :project_id AND embedding IS NOT NULL"
)
# Model switch: old-model memory vectors live in an incompatible space. They're
# nulled synchronously (search skips NULL) and re-embedded in the background.
_CLEAR_MEMORY_EMBEDDINGS_SQL = sql_text(
    "UPDATE memories SET embedding = NULL WHERE project_id = :project_id"
)


def _plan_embedding_change(
    project: Project,
    provider: str | None,
    model: str | None,
    dimensions: int | None,
) -> tuple[str, str, int, str]:
    """Resolve a requested embedding config against the project's current one.

    Returns (provider, model, dimensions, plan) where plan is "keep",
    "truncate" (same MRL model, smaller size - reuse vectors in place) or
    "reembed" (incompatible change - everything must be re-embedded).
    """
    provider = provider or project.embedding_provider
    model = model or project.embedding_model
    same_model = (provider, model) == (
        project.embedding_provider,
        project.embedding_model,
    )
    try:
        if dimensions is not None:
            dims = registry.resolve_embedding_dimensions(provider, model, dimensions)
        elif same_model:
            dims = project.embedding_dimensions
        else:
            dims = registry.embedding_dimensions(provider, model)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    plan = registry.embedding_change_plan(
        project.embedding_provider,
        project.embedding_model,
        project.embedding_dimensions,
        provider,
        model,
        dims,
    )
    return provider, model, dims, plan


def _truncate_vectors_in_place(db: Session, project: Project, dims: int) -> bool:
    """Cut chunk + memory vectors to the MRL prefix and re-normalize.

    Returns False (after rolling back) when the database lacks pgvector 0.7+
    (subvector/l2_normalize), so callers can fall back to a full re-embed.
    Must run before other pending writes in the request - the rollback on
    failure discards everything uncommitted.
    """
    try:
        params = {"dims": dims, "project_id": str(project.id)}
        db.execute(_TRUNCATE_CHUNKS_SQL, params)
        db.execute(_TRUNCATE_MEMORIES_SQL, params)
        return True
    except Exception:
        logger.exception(
            "In-place vector truncation failed for project %s; falling back to "
            "a full re-embed",
            project.id,
        )
        db.rollback()
        return False


@router.get("/files", response_model=list[FileOut])
def list_files(
    project: Project = Depends(get_owned_project), db: Session = Depends(get_db)
):
    return db.scalars(
        select(File).where(File.project_id == project.id).order_by(File.created_at)
    ).all()


@router.post("/files", response_model=list[FileOut], status_code=201)
async def upload_files(
    background_tasks: BackgroundTasks,
    uploads: list[UploadFile] = FastAPIFile(...),
    chunk_size: int | None = Form(None),
    chunk_overlap: int | None = Form(None),
    top_k: int | None = Form(None),
    embedding_provider: str | None = Form(None),
    embedding_model: str | None = Form(None),
    embedding_dimensions: int | None = Form(None),
    embedding_api_key: str | None = Form(None),
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    # validate the per-file chunking overrides (null = use project defaults)
    if chunk_size is not None and not (100 <= chunk_size <= 8000):
        raise HTTPException(422, "chunk_size must be between 100 and 8000")
    if chunk_overlap is not None and chunk_overlap < 0:
        raise HTTPException(422, "chunk_overlap must be >= 0")
    effective_size = chunk_size if chunk_size is not None else project.chunk_size
    if chunk_overlap is not None and chunk_overlap >= effective_size:
        raise HTTPException(422, "chunk_overlap must be smaller than chunk_size")

    # embedding config is project-wide (uniform vector dimension). A model
    # switch re-embeds every existing file (and memories); shrinking the same
    # Matryoshka model's dimensions truncates stored vectors in place instead.
    reindex_existing = False
    if embedding_provider or embedding_model or embedding_dimensions is not None:
        provider, model, dims, plan = _plan_embedding_change(
            project, embedding_provider, embedding_model, embedding_dimensions
        )
        if plan == "truncate" and not _truncate_vectors_in_place(db, project, dims):
            plan = "reembed"
        project.embedding_provider = provider
        project.embedding_model = model
        project.embedding_dimensions = dims
        reindex_existing = plan == "reembed"

    # top_k is a project/query setting
    if top_k is not None:
        if not (1 <= top_k <= 20):
            raise HTTPException(422, "top_k must be between 1 and 20")
        project.top_k = top_k

    pair = crypto.apply_override(embedding_api_key)
    if pair is not None:
        project.embedding_key_encrypted, project.embedding_key_last4 = pair

    created: list[File] = []
    for upload in uploads:
        filename = upload.filename or "upload"
        # Size cap BEFORE buffering/decoding - see the public route for why.
        if upload.size is not None and upload.size > settings.max_upload_bytes:
            raise HTTPException(
                413,
                f"{filename} exceeds the "
                f"{settings.max_upload_bytes // (1024 * 1024)} MB limit",
            )
        data = await upload.read()
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(
                413,
                f"{filename} exceeds the "
                f"{settings.max_upload_bytes // (1024 * 1024)} MB limit",
            )
        if not is_ingestable(filename, data):
            raise HTTPException(
                400, f"Unsupported file type: {filename} (no text could be extracted)"
            )
        file_id = uuid.uuid4()
        extension = source_extension(filename)
        content_type = content_type_for(filename, upload.content_type)
        path = f"{project.owner_id}/{project.id}/{file_id}{extension}"
        # Sync storage PUT off the event loop - this handler is async.
        await run_in_threadpool(storage.upload_file, path, data, content_type)
        record = File(
            id=file_id,
            project_id=project.id,
            filename=filename,
            storage_path=path,
            content_type=content_type,
            source_extension=extension,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            size_bytes=len(data),
        )
        db.add(record)
        created.append(record)

    # a new embedding model means every existing file (and every memory) must
    # be re-embedded - the old vectors live in an incompatible space
    existing: list[File] = []
    if reindex_existing:
        new_ids = {record.id for record in created}
        db.execute(sql_delete(Chunk).where(Chunk.project_id == project.id))
        db.execute(_CLEAR_MEMORY_EMBEDDINGS_SQL, {"project_id": str(project.id)})
        existing = [
            f
            for f in db.scalars(
                select(File).where(File.project_id == project.id)
            ).all()
            if f.id not in new_ids
        ]
        for f in existing:
            f.status = "pending"
            f.chunk_count = 0
            f.error = None
            f.conversion_error = None
            f.conversion_note = None

    project.status = "indexing"
    db.commit()

    # Background tasks run sequentially - re-embed memories FIRST (they're
    # quick) so memory search is back long before large file queues finish.
    if reindex_existing:
        background_tasks.add_task(reembed_project_memories, project.id)
    for record in created:
        background_tasks.add_task(ingest_file, record.id)
    for f in existing:
        background_tasks.add_task(ingest_file, f.id)
    return created


@router.delete("/files/{file_id}", status_code=204)
def delete_file(
    file_id: uuid.UUID,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    file = db.get(File, file_id)
    if file is None or file.project_id != project.id:
        raise HTTPException(404, "File not found")
    paths = [file.storage_path]
    if file.markdown_storage_path:
        paths.append(file.markdown_storage_path)
    db.delete(file)  # cascades to its chunks
    recompute_project_status(db, project)
    db.commit()
    storage.delete(paths)


@router.post("/files/{file_id}/retry", response_model=FileOut)
def retry_file(
    file_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    file = db.get(File, file_id)
    if file is None or file.project_id != project.id:
        raise HTTPException(404, "File not found")
    if file.status == "processing":
        raise HTTPException(409, "File is already being processed")
    file.status = "pending"
    file.error = None
    file.conversion_error = None
    file.conversion_note = None
    project.status = "indexing"
    db.commit()
    background_tasks.add_task(ingest_file, file.id)
    return file


@router.post("/reindex", response_model=list[FileOut])
def reindex_project(
    body: ReindexRequest,
    background_tasks: BackgroundTasks,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    """Update memory: apply new chunking/embedding config and re-ingest everything.

    Vector migration depends on what changed:
      * same Matryoshka model at a smaller size + unchanged chunking -> the
        stored vectors are truncated in place (instant, no re-embedding);
      * a different model (or a larger size) -> chunks are wiped and every file
        re-ingested, and memory embeddings are nulled then re-embedded with the
        new model in the background;
      * otherwise -> the classic full re-ingest.
    """
    # validate chunking up front - nothing below may run on invalid input
    effective_size = (
        body.chunk_size if body.chunk_size is not None else project.chunk_size
    )
    effective_overlap = (
        body.chunk_overlap if body.chunk_overlap is not None else project.chunk_overlap
    )
    if effective_overlap >= effective_size:
        raise HTTPException(422, "chunk_overlap must be smaller than chunk_size")
    chunking_changed = (
        effective_size != project.chunk_size
        or effective_overlap != project.chunk_overlap
    )

    provider, model, dims, plan = _plan_embedding_change(
        project, body.embedding_provider, body.embedding_model, body.embedding_dimensions
    )
    # Truncation must be the first write of the request (see helper docstring).
    if plan == "truncate" and not _truncate_vectors_in_place(db, project, dims):
        plan = "reembed"

    project.embedding_provider = provider
    project.embedding_model = model
    project.embedding_dimensions = dims
    pair = crypto.apply_override(body.embedding_api_key)
    if pair is not None:
        project.embedding_key_encrypted, project.embedding_key_last4 = pair
    project.chunk_size = effective_size
    project.chunk_overlap = effective_overlap

    files = db.scalars(select(File).where(File.project_id == project.id)).all()

    # Matryoshka fast path: vectors already migrated in place, chunks still
    # valid - nothing to re-ingest.
    if plan == "truncate" and not chunking_changed:
        db.commit()
        return files

    db.execute(sql_delete(Chunk).where(Chunk.project_id == project.id))
    if plan == "reembed":
        db.execute(_CLEAR_MEMORY_EMBEDDINGS_SQL, {"project_id": str(project.id)})
    for file in files:
        file.status = "pending"
        file.chunk_count = 0
        file.error = None
        file.conversion_error = None
        file.conversion_note = None
    project.status = "indexing" if files else "empty"
    db.commit()

    # Background tasks run sequentially - re-embed memories FIRST (they're
    # quick) so memory search is back long before large file queues finish.
    if plan == "reembed":
        background_tasks.add_task(reembed_project_memories, project.id)
    for file in files:
        background_tasks.add_task(ingest_file, file.id)
    return files
