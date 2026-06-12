import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import File, Project
from ..providers.registry import embedding_dimensions, validate_llm
from ..schemas import ProjectCreate, ProjectOut, ProjectUpdate
from ..services import storage
from .deps import get_owned_project

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _counts(db: Session, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    if not project_ids:
        return {}
    rows = db.execute(
        select(
            File.project_id,
            func.count(),
            func.coalesce(func.sum(File.chunk_count), 0),
        )
        .where(File.project_id.in_(project_ids))
        .group_by(File.project_id)
    ).all()
    return {pid: (fc, cc) for pid, fc, cc in rows}


def _to_out(project: Project, counts: dict) -> ProjectOut:
    out = ProjectOut.model_validate(project)
    out.file_count, out.chunk_count = counts.get(project.id, (0, 0))
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
    db.commit()
    return _to_out(project, _counts(db, [project.id]))


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project: Project = Depends(get_owned_project), db: Session = Depends(get_db)
):
    paths = db.scalars(
        select(File.storage_path).where(File.project_id == project.id)
    ).all()
    db.delete(project)  # cascades to files/chunks/keys/logs
    db.commit()
    storage.delete(list(paths))
