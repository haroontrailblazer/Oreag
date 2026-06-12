import uuid

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import Project


def get_owned_project(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    project = db.get(Project, project_id)
    # 404 (not 403) so project ids are not enumerable across tenants
    if project is None or project.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
