import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user, get_user_pending_mfa
from ..db import get_db
from ..models import File, Project
from ..services import admin, mfa, storage

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


# ── MFA recovery codes ──────────────────────────────────────────────────────


class RecoveryCodes(BaseModel):
    codes: list[str]


class RecoveryStatus(BaseModel):
    remaining: int


class ConsumeRecovery(BaseModel):
    code: str = Field(min_length=4, max_length=64)


@router.get("/recovery-codes", response_model=RecoveryStatus)
def recovery_code_status(
    user_id: uuid.UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """How many codes are left. Never the codes themselves - only hashes are
    stored, so there is nothing to return even if we wanted to."""
    return RecoveryStatus(remaining=mfa.unused_recovery_code_count(db, user_id))


@router.post("/recovery-codes", response_model=RecoveryCodes)
def create_recovery_codes(
    user_id: uuid.UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Issue a fresh set, invalidating any previous one.

    Behind ``get_current_user``, so it needs a session that has already cleared
    two-factor. That is deliberate: someone who has merely stolen a password
    must not be able to mint themselves a way around the second factor.
    """
    return RecoveryCodes(codes=mfa.generate_recovery_codes(db, user_id))


@router.post("/recovery-codes/consume", status_code=204)
def consume_recovery_code(
    body: ConsumeRecovery,
    user_id: uuid.UUID = Depends(get_user_pending_mfa),
    db: Session = Depends(get_db),
):
    """Spend a recovery code and remove the account's second factors.

    The ONE route behind ``get_user_pending_mfa``: a locked-out user is stuck at
    aal1, so anything behind the normal gate would 403 them - including this.

    It cannot grant aal2 (only Supabase issues that), so instead it removes the
    factor. The account then genuinely has none, aal1 becomes the correct level
    for it, and the gate opens on its own. The user is asked to enrol again.

    A wrong code and an already-used code return the same 400: the difference is
    only useful to somebody guessing. Attempts are bounded by the heavy per-user
    rate limit applied in the dependency.
    """
    if not mfa.consume_recovery_code(db, user_id, body.code):
        raise HTTPException(400, "That recovery code isn't valid.")
