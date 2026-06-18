import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.api_keys import require_api_key
from ..db import get_db
from ..models import ApiKey, File, Project
from ..providers.base import ProviderUnavailableError
from ..schemas import (
    ProjectInfo,
    QueryRequest,
    QueryResponse,
    RetrieveRequest,
    SourceChunk,
)
from ..services import retrieval
from ..services.query import run_query

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
    return run_query(db, project, body.question, body.top_k, api_key_id=api_key.id)


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
