import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import crypto
from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import File, Project, QueryLog
from ..providers.registry import embedding_dimensions, validate_llm
from ..schemas import ProjectCreate, ProjectOut, ProjectUpdate
from ..services import storage
from .deps import get_owned_project

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _set_key_override(project: Project, slot: str, value: str | None) -> None:
    """Apply a per-project BYOK override. slot is 'embedding' or 'llm'.
    None = leave unchanged, "" = clear, any other value = encrypt + store."""
    pair = crypto.apply_override(value)
    if pair is None:
        return
    encrypted, masked = pair
    setattr(project, f"{slot}_key_encrypted", encrypted)
    setattr(project, f"{slot}_key_last4", masked)


def _counts(
    db: Session, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int, int]]:
    """project_id -> (file_count, chunk_count, query_count)"""
    if not project_ids:
        return {}
    file_rows = db.execute(
        select(
            File.project_id,
            func.count(),
            func.coalesce(func.sum(File.chunk_count), 0),
        )
        .where(File.project_id.in_(project_ids))
        .group_by(File.project_id)
    ).all()
    files = {pid: (fc, cc) for pid, fc, cc in file_rows}
    query_rows = db.execute(
        select(QueryLog.project_id, func.count())
        .where(QueryLog.project_id.in_(project_ids))
        .group_by(QueryLog.project_id)
    ).all()
    queries = {pid: qc for pid, qc in query_rows}
    return {
        pid: (*files.get(pid, (0, 0)), queries.get(pid, 0))
        for pid in set(files) | set(queries)
    }


def _to_out(project: Project, counts: dict) -> ProjectOut:
    out = ProjectOut.model_validate(project)
    out.file_count, out.chunk_count, out.query_count = counts.get(
        project.id, (0, 0, 0)
    )
    return out


@router.get("", response_model=list[ProjectOut])
def list_projects(
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)
):
    projects = db.scalars(
        select(Project)
        .where(Project.owner_id == user_id)
        .order_by(Project.created_at.desc())
    ).all()
    counts = _counts(db, [p.id for p in projects])
    return [_to_out(p, counts) for p in projects]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate,
    user_id: uuid.UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.chunk_overlap >= body.chunk_size:
        raise HTTPException(422, "chunk_overlap must be smaller than chunk_size")
    try:
        dimensions = embedding_dimensions(body.embedding_provider, body.embedding_model)
        validate_llm(body.llm_provider, body.llm_model)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    project = Project(
        owner_id=user_id,
        name=body.name,
        description=body.description,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        embedding_provider=body.embedding_provider,
        embedding_model=body.embedding_model,
        embedding_dimensions=dimensions,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        top_k=body.top_k,
    )
    _set_key_override(project, "embedding", body.embedding_api_key)
    _set_key_override(project, "llm", body.llm_api_key)
    db.add(project)
    db.commit()
    return _to_out(project, {})


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project: Project = Depends(get_owned_project), db: Session = Depends(get_db)
):
    return _to_out(project, _counts(db, [project.id]))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    body: ProjectUpdate,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    if body.llm_provider or body.llm_model:
        provider = body.llm_provider or project.llm_provider
        model = body.llm_model or project.llm_model
        try:
            validate_llm(provider, model)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        project.llm_provider, project.llm_model = provider, model
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.top_k is not None:
        project.top_k = body.top_k
    _set_key_override(project, "embedding", body.embedding_api_key)
    _set_key_override(project, "llm", body.llm_api_key)
    db.commit()
    return _to_out(project, _counts(db, [project.id]))


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project: Project = Depends(get_owned_project), db: Session = Depends(get_db)
):
    files = db.scalars(select(File).where(File.project_id == project.id)).all()
    paths: list[str] = []
    for file in files:
        paths.append(file.storage_path)
        if file.markdown_storage_path:
            paths.append(file.markdown_storage_path)
    db.delete(project)  # cascades to files/chunks/keys/logs
    db.commit()
    storage.delete(paths)
