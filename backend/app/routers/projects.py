import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import crypto
from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import File, Project, QueryLog
from ..providers.registry import resolve_embedding_dimensions, validate_llm
from ..schemas import ProjectCreate, ProjectOut, ProjectUpdate
from ..services import storage
from .deps import ensure_valid_provider_key, get_owned_project

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _set_key_override(project: Project, slot: str, value: str | None) -> None:
    """Apply a per-project BYOK override. slot is 'embedding' or 'llm'.
    None = leave unchanged, "" = clear, any other value = encrypt + store."""
    pair = crypto.apply_override(value)
    if pair is None:
        return
    # Validated against the provider the key will actually be used with, which
    # callers have already set on the project by this point - so switching
    # provider and pasting its key in one request checks the pair, not the old
    # provider. A rejected key 422s before either column is written.
    ensure_valid_provider_key(getattr(project, f"{slot}_provider"), value)
    encrypted, masked = pair
    setattr(project, f"{slot}_key_encrypted", encrypted)
    setattr(project, f"{slot}_key_last4", masked)


def _name_taken(
    db: Session, owner_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
) -> bool:
    """True if this account already has a project with the same name
    (case-insensitive). Project names are unique per account."""
    stmt = select(Project.id).where(
        Project.owner_id == owner_id,
        func.lower(Project.name) == name.strip().lower(),
    )
    if exclude_id is not None:
        stmt = stmt.where(Project.id != exclude_id)
    return db.scalar(stmt) is not None


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
        dimensions = resolve_embedding_dimensions(
            body.embedding_provider, body.embedding_model, body.embedding_dimensions
        )
        validate_llm(body.llm_provider, body.llm_model)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    if _name_taken(db, user_id, body.name):
        raise HTTPException(
            409, f'A project named "{body.name.strip()}" already exists.'
        )

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
    if body.name is not None and body.name != project.name:
        if _name_taken(db, project.owner_id, body.name, exclude_id=project.id):
            raise HTTPException(
                409, f'A project named "{body.name.strip()}" already exists.'
            )
        project.name = body.name
    if body.description is not None:
        # Blank collapses to NULL so "no description" has exactly one
        # representation in the column, matching what create stores. Callers
        # clear the field by sending "" - null means "leave it alone", so it
        # cannot double as the clear signal.
        project.description = body.description.strip() or None
    if body.top_k is not None:
        project.top_k = body.top_k
    # Answer policy. `is not None` and NOT `or`: 0.0 and 0 are meaningful here
    # ("never abstain"), and `or` would discard them for the current value.
    if body.min_similarity is not None:
        project.min_similarity = body.min_similarity
    if body.min_strong is not None:
        project.min_strong = body.min_strong
    # Blank collapses to NULL so "unset" has one representation, matching
    # description above.
    if body.answer_language is not None:
        project.answer_language = body.answer_language.strip() or None
    if body.answer_disclaimer is not None:
        project.answer_disclaimer = body.answer_disclaimer.strip() or None
    # Document versions (0034). Like the answer-policy fields above, this
    # deliberately does NOT bump content_version: it changes nothing already
    # indexed. Turning it OFF only stops new uploads being held for review -
    # every requeue guard keys on files.in_force_to, never on this flag, so
    # already-superseded editions stay superseded.
    if body.version_tracking is not None:
        project.version_tracking = body.version_tracking
    _set_key_override(project, "embedding", body.embedding_api_key)
    _set_key_override(project, "llm", body.llm_api_key)
    db.commit()
    return _to_out(project, _counts(db, [project.id]))


@router.post("/{project_id}/suspend", response_model=ProjectOut)
def suspend_project(
    project: Project = Depends(get_owned_project), db: Session = Depends(get_db)
):
    """Pause a project: its keys and the public /v1 API + MCP stop working (403)
    until resumed. Nothing is deleted."""
    project.suspended = True
    db.commit()
    return _to_out(project, _counts(db, [project.id]))


@router.post("/{project_id}/resume", response_model=ProjectOut)
def resume_project(
    project: Project = Depends(get_owned_project), db: Session = Depends(get_db)
):
    """Reactivate a suspended project - keys and external access work again."""
    project.suspended = False
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
