import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.api_keys import generate_api_key
from ..db import get_db
from ..models import ApiKey, Project
from ..schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut, ApiKeyUpdate
from .deps import get_owned_project

router = APIRouter(prefix="/api/projects/{project_id}/keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyOut])
def list_keys(
    project: Project = Depends(get_owned_project), db: Session = Depends(get_db)
):
    return db.scalars(
        select(ApiKey)
        .where(ApiKey.project_id == project.id)
        .order_by(ApiKey.created_at.desc())
    ).all()


@router.post("", response_model=ApiKeyCreated, status_code=201)
def create_key(
    body: ApiKeyCreate,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    full_key, key_hash, key_prefix = generate_api_key()
    api_key = ApiKey(
        project_id=project.id,
        name=body.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        can_upload=body.can_upload,
    )
    db.add(api_key)
    db.commit()
    # the full key is shown exactly once; only its hash is stored
    return ApiKeyCreated(
        **ApiKeyOut.model_validate(api_key).model_dump(), key=full_key
    )


@router.patch("/{key_id}", response_model=ApiKeyOut)
def update_key(
    key_id: uuid.UUID,
    body: ApiKeyUpdate,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    api_key = db.get(ApiKey, key_id)
    if api_key is None or api_key.project_id != project.id:
        raise HTTPException(404, "API key not found")
    if body.can_upload is not None:
        api_key.can_upload = body.can_upload
    db.commit()
    return api_key


@router.delete("/{key_id}", response_model=ApiKeyOut)
def revoke_key(
    key_id: uuid.UUID,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    api_key = db.get(ApiKey, key_id)
    if api_key is None or api_key.project_id != project.id:
        raise HTTPException(404, "API key not found")
    if api_key.revoked_at is None:
        api_key.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return api_key


@router.delete("/{key_id}/purge", status_code=204)
def delete_key(
    key_id: uuid.UUID,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    """Permanently delete a key from the database (hard delete, not a revoke)."""
    api_key = db.get(ApiKey, key_id)
    if api_key is None or api_key.project_id != project.id:
        raise HTTPException(404, "API key not found")
    db.delete(api_key)
    db.commit()
