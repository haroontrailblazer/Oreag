import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import File, Project
from ..services import admin, storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/account", tags=["account"])


@router.delete("", status_code=204)
def delete_account(
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Permanently delete the signed-in user and everything they own.

    Deleting the auth user cascades all DB rows (projects → files/chunks/
    api_keys/query_logs, and provider_keys). Storage objects are not covered by
    the DB cascade, so collect their paths first and clean them up afterwards.
    """
    project_ids = db.scalars(
        select(Project.id).where(Project.owner_id == user_id)
    ).all()
    paths: list[str] = []
    if project_ids:
        files = db.scalars(
            select(File).where(File.project_id.in_(project_ids))
        ).all()
        for f in files:
            paths.append(f.storage_path)
            if f.markdown_storage_path:
                paths.append(f.markdown_storage_path)

    # Cascades all of the user's DB rows.
    admin.delete_auth_user(str(user_id))

    # Best-effort storage cleanup (not part of the DB cascade).
    if paths:
        try:
            storage.delete(paths)
        except Exception:
            logger.exception("Storage cleanup failed during account deletion")
