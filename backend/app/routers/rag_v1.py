import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi import File as FastAPIFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.api_keys import require_api_key
from ..config import settings
from ..db import get_db
from ..models import ApiKey, File, Project
from ..providers.base import ProviderUnavailableError
from ..schemas import (
    BrainExploreRequest,
    BrainExploreResponse,
    FileOut,
    ProjectInfo,
    QueryRequest,
    QueryResponse,
    RetrieveRequest,
    SourceChunk,
)
from ..sse import sse_response
from ..services import explore, retrieval, storage
from ..services.conversion import content_type_for, is_supported_upload, source_extension
from ..services.ingestion import ingest_file
from ..services.query import run_query, run_query_stream

router = APIRouter(prefix="/v1/projects/{project_id}", tags=["public-api"])


def _get_project(db: Session, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


@router.post("/query", response_model=QueryResponse)
def public_query(
    project_id: uuid.UUID,
    body: QueryRequest,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    return run_query(
        db,
        project,
        body.question,
        body.top_k,
        api_key_id=api_key.id,
        conversation_id=body.conversation_id,
    )


@router.post("/query/stream")
def public_query_stream(
    project_id: uuid.UUID,
    body: QueryRequest,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Same as /query, streamed token by token over Server-Sent Events.

    Emits `data: {"type":"token","text":...}` frames as the answer is produced,
    a final `data: {"type":"done","response":{...}}` frame with the full payload
    (sources, model, latency, cache info), and `{"type":"error"}` on failure.
    """
    project = _get_project(db, project_id)
    return sse_response(
        run_query_stream(
            db,
            project,
            body.question,
            body.top_k,
            api_key_id=api_key.id,
            conversation_id=body.conversation_id,
        )
    )


@router.post("/retrieve", response_model=list[SourceChunk])
def retrieve_docs(
    project_id: uuid.UUID,
    body: RetrieveRequest,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Retrieval-only over the project's documents (no LLM call)."""
    project = _get_project(db, project_id)
    try:
        sources = retrieval.retrieve(db, project, body.query, body.top_k or 5)
    except ProviderUnavailableError as exc:
        raise HTTPException(503, str(exc))
    return [SourceChunk(**s) for s in sources]


@router.post("/files", response_model=list[FileOut], status_code=201)
async def public_upload_files(
    project_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    uploads: list[UploadFile] = FastAPIFile(...),
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Ingest documents with an API key, using the project's default chunking and
    embedding settings.

    Guarded: requires a key created with upload permission (read-only keys get
    403), an allowlisted file type, a per-file size cap, a per-request file-count
    cap, a per-project total-file quota, and a per-project ingest rate limit.
    """
    if not api_key.can_upload:
        raise HTTPException(
            403, "This API key is read-only - create a key with upload permission to ingest."
        )
    project = _get_project(db, project_id)

    if not uploads:
        raise HTTPException(422, "No files provided")
    if len(uploads) > settings.max_files_per_upload:
        raise HTTPException(
            413, f"Too many files in one request (max {settings.max_files_per_upload})"
        )

    total = (
        db.scalar(select(func.count()).select_from(File).where(File.project_id == project.id))
        or 0
    )
    if total + len(uploads) > settings.max_files_per_project:
        raise HTTPException(
            413, f"Project file limit reached (max {settings.max_files_per_project})"
        )

    recent = (
        db.scalar(
            select(func.count())
            .select_from(File)
            .where(
                File.project_id == project.id,
                File.created_at >= datetime.now(timezone.utc) - timedelta(seconds=60),
            )
        )
        or 0
    )
    if recent + len(uploads) > settings.upload_rate_per_minute:
        raise HTTPException(429, "Upload rate limit exceeded - try again shortly.")

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
            size_bytes=len(data),
        )
        db.add(record)
        created.append(record)

    project.status = "indexing"
    db.commit()
    for record in created:
        background_tasks.add_task(ingest_file, record.id)
    return created


@router.post("/explore", response_model=BrainExploreResponse)
def explore_brain(
    project_id: uuid.UUID,
    body: BrainExploreRequest,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Agentic retrieval: seed on the query's nearest document chunks AND saved
    memories, expand `hops` steps along their related links, and return a
    connected subgraph (nodes carry their text) to reason over - richer than flat
    top-k. This is the agentic-RAG entry point; /query is the simple chat one.
    """
    project = _get_project(db, project_id)
    try:
        seeds, nodes, edges = explore.explore_brain(db, project, body.query, body.hops)
    except ProviderUnavailableError as exc:
        raise HTTPException(503, str(exc))
    return BrainExploreResponse(query=body.query, seeds=seeds, nodes=nodes, edges=edges)


@router.get("", response_model=ProjectInfo)
def project_info(
    project_id: uuid.UUID,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    file_count = db.scalar(
        select(func.count()).select_from(File).where(File.project_id == project.id)
    )
    return ProjectInfo(
        id=project.id, name=project.name, status=project.status, file_count=file_count
    )
