import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import OperationSnapshot
from ..services.operations import report

router = APIRouter(prefix="/api/account/operations", tags=["operations"])


@router.get("")
def read_operations(owner_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    saved = db.get(OperationSnapshot, owner_id)
    if saved and (datetime.now(timezone.utc)-saved.checked_at.replace(tzinfo=timezone.utc)).total_seconds() < 60:
        return saved.report
    return report(db, owner_id)
