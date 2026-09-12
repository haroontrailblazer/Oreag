import uuid
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import OperationSnapshot
from ..services.operations import report
from ..services.request_failures import FailedRequest, FailurePage, read_failure, read_failures

router = APIRouter(prefix="/api/account/operations", tags=["operations"])


@router.get("/failures", response_model=FailurePage)
def list_failed_requests(
    hours: int = Query(default=24, ge=1, le=720),
    project_id: uuid.UUID | None = None,
    search: str = Query(default="", max_length=200),
    outcome: Literal["all", "error", "rejected", "stream_error", "disconnected"] = "all",
    status_code: int | None = Query(default=None, ge=100, le=599),
    min_latency_ms: int | None = Query(default=None, ge=0, le=3_600_000),
    before: str | None = Query(default=None, min_length=1, max_length=256),
    limit: int = Query(default=25, ge=1, le=100),
    owner_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db),
) -> FailurePage:
    return read_failures(db, owner_id, hours=hours, project_id=project_id, search=search,
        outcome=outcome, status_code=status_code, min_latency_ms=min_latency_ms, before=before, limit=limit)


@router.get("/failures/{record_id}", response_model=FailedRequest)
def failed_request_detail(record_id: int, owner_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)) -> FailedRequest:
    return read_failure(db, owner_id, record_id)


@router.get("")
def read_operations(owner_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    saved = db.get(OperationSnapshot, owner_id)
    if saved and (datetime.now(timezone.utc)-saved.checked_at.replace(tzinfo=timezone.utc)).total_seconds() < 60:
        return saved.report
    return report(db, owner_id)
