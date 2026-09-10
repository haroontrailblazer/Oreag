"""Atomic feedback updates shared by owner and project-key APIs."""
from datetime import timezone

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ..models import QueryLog
from ..schemas import FeedbackResponse


def write_feedback(
    db: Session, query_id: int, *, scope: ColumnElement[bool], **values,
) -> FeedbackResponse:
    if not 0 < query_id <= 9_223_372_036_854_775_807:
        raise HTTPException(404, "Query not found")
    # Authorize the mutation itself; never read then update an unscoped row.
    row = db.execute(update(QueryLog).where(
        QueryLog.id == query_id, scope,
    ).values(**values).returning(
        QueryLog.id, QueryLog.feedback_rating, QueryLog.feedback_note,
        QueryLog.feedback_updated_at,
    )).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Query not found")
    updated_at = row["feedback_updated_at"]
    if updated_at is not None and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    result = FeedbackResponse(
        query_id=str(row["id"]), rating=row["feedback_rating"],
        note=row["feedback_note"], updated_at=updated_at,
    )
    db.commit()
    return result
