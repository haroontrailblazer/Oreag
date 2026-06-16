import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from fastapi import File as FastAPIFile
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Chunk, File, Project
from ..providers.registry import embedding_dimensions
from ..schemas import FileOut, ReindexRequest
from ..services import storage
from ..services.conversion import content_type_for, is_supported_upload, source_extension
from ..services.ingestion import ingest_file, recompute_project_status
from .deps import get_owned_project

router = APIRouter(prefix="/api/projects/{project_id}", tags=["files"])


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

    # top_k is a project/query setting
    if top_k is not None:
        if not (1 <= top_k <= 20):
            raise HTTPException(422, "top_k must be between 1 and 20")
        project.top_k = top_k

    # embedding model is project-wide (uniform vector dimension); changing it
    # re-indexes every existing file too.
    reindex_existing = False
    if (
        embedding_provider
        and embedding_model
        and (
            embedding_provider != project.embedding_provider
            or embedding_model != project.embedding_model
        )
    ):
        try:
            dimensions = embedding_dimensions(embedding_provider, embedding_model)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        project.embedding_provider = embedding_provider
        project.embedding_model = embedding_model
        project.embedding_dimensions = dimensions
        reindex_existing = True

    created: list[File] = []
    for upload in uploads:
        filename = upload.filename or "upload"
        if not is_supported_upload(filename):
            raise HTTPException(400, f"Unsupported file type: {filename}")
        data = await upload.read()
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(
                413,
                f"{filename} exceeds the "
                f"{settings.max_upload_bytes // (1024 * 1024)} MB limit",
            )
        file_id = uuid.uuid4()
        extension = source_extension(filename)
        content_type = content_type_for(filename, upload.content_type)
        path = f"{project.owner_id}/{project.id}/{file_id}{extension}"
        storage.upload_file(path, data, content_type)
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

    # a new embedding model means every existing file must be re-embedded
    existing: list[File] = []
    if reindex_existing:
        new_ids = {record.id for record in created}
        db.execute(sql_delete(Chunk).where(Chunk.project_id == project.id))
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

    project.status = "indexing"
    db.commit()

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
    """Update memory: apply new chunking/embedding config and re-ingest everything."""
    if body.embedding_provider or body.embedding_model:
        provider = body.embedding_provider or project.embedding_provider
        model = body.embedding_model or project.embedding_model
        try:
            dimensions = embedding_dimensions(provider, model)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        project.embedding_provider = provider
        project.embedding_model = model
        project.embedding_dimensions = dimensions
    if body.chunk_size is not None:
        project.chunk_size = body.chunk_size
    if body.chunk_overlap is not None:
        project.chunk_overlap = body.chunk_overlap
    if project.chunk_overlap >= project.chunk_size:
        raise HTTPException(422, "chunk_overlap must be smaller than chunk_size")

    db.execute(sql_delete(Chunk).where(Chunk.project_id == project.id))
    files = db.scalars(select(File).where(File.project_id == project.id)).all()
    for file in files:
        file.status = "pending"
        file.chunk_count = 0
        file.error = None
        file.conversion_error = None
    project.status = "indexing" if files else "empty"
    db.commit()

    for file in files:
        background_tasks.add_task(ingest_file, file.id)
    return files
