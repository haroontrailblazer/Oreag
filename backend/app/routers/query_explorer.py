"""Owner-scoped query history and answer feedback.

Use keyset pagination and fetch full questions only on selection. Answers and
sources are not persisted in QueryLog and must not be reconstructed from caches.
"""
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import Project, QueryLog
from ..schemas import FeedbackInput
from ..services.feedback import write_feedback
from ..services.query_history import QueryPage, QueryRecord, read_queries, read_query

router = APIRouter(prefix="/api/account/queries", tags=["query explorer"])


@router.get("", response_model=QueryPage)
def list_queries(
    days: int = Query(default=30, ge=7, le=90),
    project_id: uuid.UUID | None = None,
    search: str = Query(default="", max_length=200),
    cache: Literal["all", "fresh", "l1", "l2"] = "all",
    feedback: Literal["all", "helpful", "not_helpful", "unrated"] = "all",
    min_latency_ms: int | None = Query(default=None, ge=0, le=3_600_000),
    before: int | None = Query(default=None, gt=0, le=9_223_372_036_854_775_807),
    limit: int = Query(default=25, ge=1, le=100),
    user_id: uuid.UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QueryPage:
    return read_queries(
        db, scope=Project.owner_id == user_id, days=days, project_id=project_id,
        search=search, cache=cache, feedback=feedback, min_latency_ms=min_latency_ms,
        before=before, limit=limit,
    )


@router.get("/{query_id}", response_model=QueryRecord)
def query_detail(
    query_id: int,
    user_id: uuid.UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QueryRecord:
    return read_query(db, query_id, scope=Project.owner_id == user_id)


@router.put("/{query_id}/feedback", response_model=QueryRecord)
def save_feedback(
    query_id: int, body: FeedbackInput,
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db),
) -> QueryRecord:
    write_feedback(
        db, query_id, scope=QueryLog.project_id.in_(
            select(Project.id).where(Project.owner_id == user_id)),
        feedback_rating=body.rating, feedback_note=body.note or None,
        feedback_updated_at=datetime.now(timezone.utc),
    )
    return query_detail(query_id, user_id, db)


@router.delete("/{query_id}/feedback", status_code=204)
def clear_feedback(
    query_id: int,
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db),
):
    write_feedback(
        db, query_id, scope=QueryLog.project_id.in_(
            select(Project.id).where(Project.owner_id == user_id)),
        feedback_rating=None, feedback_note=None, feedback_updated_at=None,
    )
