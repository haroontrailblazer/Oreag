"""Read-only, owner-scoped access to the existing query log.

Use keyset pagination and fetch full questions only on selection. Answers and
sources are not persisted in QueryLog and must not be reconstructed from caches.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import Project, QueryLog

router = APIRouter(prefix="/api/account/queries", tags=["query explorer"])


class QueryRecord(BaseModel):
    id: str  # PostgreSQL bigint can exceed JavaScript's safe integer range.
    project_id: uuid.UUID
    project_name: str
    question: str
    created_at: datetime
    latency_ms: int | None
    top_k: int | None
    cache_layer: str | None
    retrieval_similarity: float | None
    cache_similarity: float | None


class QueryPage(BaseModel):
    items: list[QueryRecord]
    next_cursor: str | None


def _statement(user_id: uuid.UUID, *, preview: bool):
    question = func.substr(QueryLog.question, 1, 320) if preview else QueryLog.question
    return select(
        QueryLog.id, QueryLog.project_id, Project.name.label("project_name"),
        question.label("question"), QueryLog.created_at, QueryLog.latency_ms,
        QueryLog.top_k, QueryLog.cache_layer, QueryLog.retrieval_similarity,
        QueryLog.cache_similarity,
    ).join(Project, Project.id == QueryLog.project_id).where(Project.owner_id == user_id)


def _record(row) -> QueryRecord:
    values = dict(row)
    values["id"] = str(values["id"])
    # SQLite test timestamps are naive; production stores timestamptz in UTC.
    if values["created_at"].tzinfo is None:
        values["created_at"] = values["created_at"].replace(tzinfo=timezone.utc)
    return QueryRecord(**values)


@router.get("", response_model=QueryPage)
def list_queries(
    days: int = Query(default=30, ge=7, le=90),
    project_id: uuid.UUID | None = None,
    search: str = Query(default="", max_length=200),
    cache: Literal["all", "fresh", "l1", "l2"] = "all",
    min_latency_ms: int | None = Query(default=None, ge=0, le=3_600_000),
    before: int | None = Query(default=None, gt=0, le=9_223_372_036_854_775_807),
    limit: int = Query(default=25, ge=1, le=100),
    user_id: uuid.UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QueryPage:
    if days not in (7, 30, 90):
        raise HTTPException(422, "Time range must be 7, 30, or 90 days")
    statement = _statement(user_id, preview=True).where(
        QueryLog.created_at >= datetime.now(timezone.utc) - timedelta(days=days)
    )
    if project_id is not None:
        statement = statement.where(QueryLog.project_id == project_id)
    if search.strip():
        statement = statement.where(QueryLog.question.icontains(search.strip(), autoescape=True))
    if cache == "fresh":
        statement = statement.where(QueryLog.cache_layer.is_(None))
    elif cache != "all":
        statement = statement.where(QueryLog.cache_layer == cache)
    if min_latency_ms is not None:
        statement = statement.where(QueryLog.latency_ms >= min_latency_ms)
    if before is not None:
        statement = statement.where(QueryLog.id < before)
    rows = db.execute(statement.order_by(QueryLog.id.desc()).limit(limit + 1)).mappings().all()
    items = [_record(row) for row in rows[:limit]]
    return QueryPage(
        items=items,
        next_cursor=items[-1].id if len(rows) > limit else None,
    )


@router.get("/{query_id}", response_model=QueryRecord)
def query_detail(
    query_id: int,
    user_id: uuid.UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QueryRecord:
    if not 0 < query_id <= 9_223_372_036_854_775_807:
        raise HTTPException(404, "Query not found")
    row = db.execute(
        _statement(user_id, preview=False).where(QueryLog.id == query_id)
    ).mappings().first()
    if row is None:
        raise HTTPException(404, "Query not found")
    return _record(row)
