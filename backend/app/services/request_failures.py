"""Read retained request failures without reconstructing private request bodies."""
import base64
import binascii
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Project, RequestMetric

Outcome = Literal["error", "rejected", "stream_error", "disconnected"]
OUTCOMES = ("error", "rejected", "stream_error", "disconnected")
MAX_ID = 9_223_372_036_854_775_807


class FailedRequest(BaseModel):
    id: str
    project_id: uuid.UUID | None
    project_name: str | None
    endpoint: str
    status_code: int
    outcome: Outcome
    latency_ms: float | None
    first_token_ms: float | None
    created_at: datetime


class FailurePage(BaseModel):
    items: list[FailedRequest]
    next_cursor: str | None
    as_of: datetime
    window_hours: int
    retention_days: int


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _statement(owner):
    # Both the historical owner and the current project owner must match. Never
    # reveal another project's name through a stale or inconsistent metric.
    return select(RequestMetric, Project.name).outerjoin(Project, Project.id == RequestMetric.project_id).where(
        RequestMetric.owner_id == owner,
        or_(RequestMetric.project_id.is_(None), Project.owner_id == owner),
        RequestMetric.outcome.in_(OUTCOMES),
    )


def _record(row):
    metric, name = row
    return FailedRequest(id=str(metric.id), project_id=metric.project_id, project_name=name,
        endpoint=metric.endpoint, status_code=metric.status_code, outcome=metric.outcome,
        latency_ms=metric.latency_ms, first_token_ms=metric.first_token_ms, created_at=_utc(metric.created_at))


def _decode_cursor(value, now):
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        stamp, raw_id, snapshot = json.loads(raw)
        stamp, snapshot = datetime.fromisoformat(stamp), datetime.fromisoformat(snapshot)
        if not isinstance(raw_id, str) or not raw_id.isdecimal():
            raise ValueError
        ident = int(raw_id)
        if not stamp.tzinfo or not snapshot.tzinfo or not 0 < ident <= MAX_ID or stamp > snapshot or snapshot > now:
            raise ValueError
        return _utc(stamp), ident, _utc(snapshot)
    except (ValueError, TypeError, OverflowError, binascii.Error, UnicodeError):
        raise HTTPException(422, "Invalid page cursor. Refresh the failed requests list.") from None


def read_failures(db: Session, owner: uuid.UUID, *, hours=24, project_id=None, search="",
                  outcome="all", status_code=None, min_latency_ms=None, before=None, limit=25):
    if hours not in (1, 24, 168, 720):
        raise HTTPException(422, "Choose the last hour, 24 hours, 7 days, or 30 days")
    now = datetime.now(timezone.utc)
    snapshot = now
    statement = _statement(owner)
    if before:
        stamp, ident, snapshot = _decode_cursor(before, now)
        statement = statement.where(or_(RequestMetric.created_at < stamp,
            and_(RequestMetric.created_at == stamp, RequestMetric.id < ident)))
    statement = statement.where(RequestMetric.created_at >= snapshot - timedelta(hours=hours), RequestMetric.created_at <= snapshot)
    if project_id:
        statement = statement.where(RequestMetric.project_id == project_id)
    if search.strip():
        statement = statement.where(RequestMetric.endpoint.icontains(search.strip(), autoescape=True))
    if outcome != "all":
        statement = statement.where(RequestMetric.outcome == outcome)
    if status_code is not None:
        statement = statement.where(RequestMetric.status_code == status_code)
    if min_latency_ms is not None:
        statement = statement.where(RequestMetric.latency_ms >= min_latency_ms)
    rows = db.execute(statement.order_by(RequestMetric.created_at.desc(), RequestMetric.id.desc()).limit(limit + 1)).all()
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1][0]
        next_cursor = base64.urlsafe_b64encode(json.dumps([_utc(last.created_at).isoformat(), str(last.id), snapshot.isoformat()]).encode()).decode().rstrip("=")
    return FailurePage(items=[_record(row) for row in rows[:limit]], next_cursor=next_cursor,
        as_of=snapshot, window_hours=hours, retention_days=settings.log_retention_days)


def read_failure(db: Session, owner: uuid.UUID, record_id: int):
    if not 0 < record_id <= MAX_ID:
        raise HTTPException(404, "Request record not found")
    row = db.execute(_statement(owner).where(RequestMetric.id == record_id)).first()
    if row is None:
        raise HTTPException(404, "Request record not found")
    return _record(row)
