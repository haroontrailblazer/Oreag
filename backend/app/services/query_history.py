"""Shared, explicitly scoped query history reads for owner and project APIs."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func, literal, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from ..models import Project, QueryLog


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
    feedback_rating: Literal["helpful", "not_helpful"] | None = None
    feedback_note: str | None = None
    feedback_updated_at: datetime | None = None
    timeline: dict | None = None


class QueryPage(BaseModel):
    items: list[QueryRecord]
    next_cursor: str | None


def _statement(scope: ColumnElement[bool], *, preview: bool):
    question = func.substr(QueryLog.question, 1, 320) if preview else QueryLog.question
    return select(
        QueryLog.id, QueryLog.project_id, Project.name.label("project_name"),
        question.label("question"), QueryLog.created_at, QueryLog.latency_ms,
        QueryLog.top_k, QueryLog.cache_layer, QueryLog.retrieval_similarity,
        QueryLog.cache_similarity,
        QueryLog.feedback_rating, QueryLog.feedback_updated_at,
        (literal(None) if preview else QueryLog.feedback_note).label("feedback_note"),
        (literal(None) if preview else QueryLog.timeline).label("timeline"),
    ).join(Project, Project.id == QueryLog.project_id).where(scope)


def _record(row) -> QueryRecord:
    values = dict(row)
    values["id"] = str(values["id"])
    # SQLite test timestamps are naive; production stores timestamptz in UTC.
    if values["created_at"].tzinfo is None:
        values["created_at"] = values["created_at"].replace(tzinfo=timezone.utc)
    if values["feedback_updated_at"] is not None and values["feedback_updated_at"].tzinfo is None:
        values["feedback_updated_at"] = values["feedback_updated_at"].replace(tzinfo=timezone.utc)
    return QueryRecord(**values)


def read_queries(
    db: Session, *, scope: ColumnElement[bool], days: int = 30,
    project_id: uuid.UUID | None = None, search: str = "", cache: str = "all",
    feedback: str = "all", min_latency_ms: int | None = None,
    before: int | None = None, limit: int = 25,
) -> QueryPage:
    if days not in (7, 30, 90):
        raise HTTPException(422, "Time range must be 7, 30, or 90 days")
    statement = _statement(scope, preview=True).where(
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
    if feedback == "unrated":
        statement = statement.where(QueryLog.feedback_rating.is_(None))
    elif feedback != "all":
        statement = statement.where(QueryLog.feedback_rating == feedback)
    if before is not None:
        statement = statement.where(QueryLog.id < before)
    rows = db.execute(statement.order_by(QueryLog.id.desc()).limit(limit + 1)).mappings().all()
    items = [_record(row) for row in rows[:limit]]
    return QueryPage(
        items=items,
        next_cursor=items[-1].id if len(rows) > limit else None,
    )


def read_query(db: Session, query_id: int, *, scope: ColumnElement[bool]) -> QueryRecord:
    if not 0 < query_id <= 9_223_372_036_854_775_807:
        raise HTTPException(404, "Query not found")
    row = db.execute(
        _statement(scope, preview=False).where(QueryLog.id == query_id)
    ).mappings().first()
    if row is None:
        raise HTTPException(404, "Query not found")
    return _record(row)
