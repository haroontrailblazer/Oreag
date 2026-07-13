import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi import File as FastAPIFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from ..auth.api_keys import require_api_key
from ..config import settings
from ..db import get_db
from ..models import ApiKey, File, Project, SuspendedAccount, SuspendedAccount
from ..providers.base import ProviderUnavailableError, is_provider_rate_limit
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
from ..services.conversion import content_type_for, is_ingestable, source_extension
from ..services.query import run_query, run_query_stream
from ..services.rate_limit import enforce_rate_limit
from ..services.usage import record_usage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/projects/{project_id}", tags=["public-api"])


def _get_project(db: Session, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    if project.suspended:
        raise HTTPException(
            403,
            "This project is suspended. The owner can resume it from the dashboard.",
        )
    # Operator kill switch: one row in suspended_accounts cuts off ALL of an
    # account's projects at once (per-project suspension is owner-controlled
    # and 50 projects would mean 50 toggles).
    if db.scalar(
        select(SuspendedAccount.owner_id).where(
            SuspendedAccount.owner_id == project.owner_id
        )
    ):
        raise HTTPException(403, "This account is suspended. Contact support.")
    return project


@router.post("/query", response_model=QueryResponse)
def public_query(
    project_id: uuid.UUID,
    body: QueryRequest,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    enforce_rate_limit(api_key.id, project.id)
    response = run_query(
        db,
        project,
        body.question,
        body.top_k,
        api_key_id=api_key.id,
        conversation_id=body.conversation_id,
    )
    record_usage(
        db,
        project=project,
        api_key_id=api_key.id,
        endpoint="query",
        latency_ms=response.latency_ms,
    )
    return response


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
    enforce_rate_limit(api_key.id, project.id)
    # Recorded up-front (no latency): the stream body runs after this returns.
    record_usage(db, project=project, api_key_id=api_key.id, endpoint="query_stream")
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
    enforce_rate_limit(api_key.id, project.id)
    started = time.perf_counter()
    try:
        sources = retrieval.retrieve(db, project, body.query, body.top_k or 5)
    except ProviderUnavailableError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        if is_provider_rate_limit(exc):
            raise HTTPException(
                429,
                "The AI provider is rate limiting this project's key - retry shortly.",
                headers={"Retry-After": "10"},
            )
        raise
    record_usage(
        db,
        project=project,
        api_key_id=api_key.id,
        endpoint="retrieve",
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return [SourceChunk(**s) for s in sources]


@router.post("/files", response_model=list[FileOut], status_code=201)
async def public_upload_files(
    project_id: uuid.UUID,
    uploads: list[UploadFile] = FastAPIFile(...),
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Ingest documents with an API key, using the project's default chunking and
    embedding settings.

    Any file text can be extracted from is accepted: rich formats (PDF, Office,
    images, audio, ...) convert via MarkItDown, everything else ingests as plain
    text - only opaque binary is rejected. Client content types are optional.

    Guarded: requires a key created with upload permission (read-only keys get
    403), a per-file size cap, a per-request file-count cap, a per-project
    total-file quota, and a per-project ingest rate limit.
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

    # Phase 1 - validate EVERYTHING before touching storage or counting
    # quotas: a mid-batch rejection can then never strand already-uploaded
    # objects, and the quota transaction below stays fast.
    validated: list[tuple[str, bytes, str, str]] = []  # (filename, data, ext, mime)
    for upload in uploads:
        filename = upload.filename or "upload"
        # Enforce the size cap BEFORE buffering/decoding: the multipart parser
        # reports the part size, so an oversized file 413s without loading
        # ~50MB into RAM or text-sniffing it first.
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
        validated.append(
            (
                filename,
                data,
                source_extension(filename),
                content_type_for(filename, upload.content_type),
            )
        )

    # Phase 2 - quotas inside a per-project advisory lock. Without it these
    # were check-then-insert: N concurrent uploads (a project's keys live in
    # different apps) all read the same counts, all passed, and overshot both
    # the total quota and the rate limit. The xact lock serializes count+insert
    # per project and releases at commit.
    db.execute(
        sql_text("SELECT pg_advisory_xact_lock(hashtextextended(:pid, 0))"),
        {"pid": str(project.id)},
    )
    total = (
        db.scalar(select(func.count()).select_from(File).where(File.project_id == project.id))
        or 0
    )
    if total + len(validated) > settings.max_files_per_project:
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
    if recent + len(validated) > settings.upload_rate_per_minute:
        raise HTTPException(429, "Upload rate limit exceeded - try again shortly.")

    created: list[File] = []
    payloads: list[bytes] = []
    for filename, data, extension, content_type in validated:
        file_id = uuid.uuid4()
        record = File(
            id=file_id,
            project_id=project.id,
            filename=filename,
            storage_path=f"{project.owner_id}/{project.id}/{file_id}{extension}",
            content_type=content_type,
            source_extension=extension,
            size_bytes=len(data),
        )
        db.add(record)
        created.append(record)
        payloads.append(data)
    project.status = "indexing"
    db.commit()  # releases the advisory lock

    # Phase 3 - storage PUTs after the fast transaction (holding the lock
    # through multi-second uploads would serialize every uploader). A failed
    # PUT marks just that file failed - visible in the Files tab - instead of
    # silently leaking objects like the old inverse ordering did.
    for record, data in zip(created, payloads):
        try:
            # supabase-py's storage call is synchronous: run it in the
            # threadpool so a multi-second 50MB PUT doesn't freeze the event
            # loop (this handler is async).
            await run_in_threadpool(
                storage.upload_file, record.storage_path, data, record.content_type
            )
        except Exception:
            logger.exception("Storage upload failed for %s", record.filename)
            record.status = "failed"
            record.error = "Upload to storage failed - retry from the Files tab"
    db.commit()
    record_usage(db, project=project, api_key_id=api_key.id, endpoint="files_upload")
    # No task scheduling: rows sit in status='pending' and the durable queue
    # workers claim them - the queue survives restarts and deploys.
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
    # The most expensive request in the API: each hop multiplies exact vector
    # scans over the project's whole chunk set - heavy budget + hop clamp.
    enforce_rate_limit(api_key.id, project.id, heavy=True)
    hops = min(body.hops, settings.explore_max_hops_api)
    started = time.perf_counter()
    try:
        seeds, nodes, edges = explore.explore_brain(db, project, body.query, hops)
    except ProviderUnavailableError as exc:
        raise HTTPException(503, str(exc))
    record_usage(
        db,
        project=project,
        api_key_id=api_key.id,
        endpoint="explore",
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return BrainExploreResponse(query=body.query, seeds=seeds, nodes=nodes, edges=edges)


@router.get("", response_model=ProjectInfo)
def project_info(
    project_id: uuid.UUID,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    enforce_rate_limit(api_key.id, project.id)
    file_count = db.scalar(
        select(func.count()).select_from(File).where(File.project_id == project.id)
    )
    return ProjectInfo(
        id=project.id, name=project.name, status=project.status, file_count=file_count
    )
