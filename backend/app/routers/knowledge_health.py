"""Owner-scoped knowledge diagnostics using the shared report service."""
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import Project
from ..services.knowledge_health import KnowledgeHealth, read_health
from ..services.quality_trends import EvaluationTrends, QualityTrends, read_evaluation_trends, read_trends
from ..services.document_insights import DocumentInsights, ReviewInput, read_document_insights, review_document

router = APIRouter(prefix="/api/account/knowledge-health", tags=["knowledge health"])


@router.get("/documents", response_model=DocumentInsights)
def document_insights(
    project_id: uuid.UUID, days: int = 30, search: str = "", offset: int = 0,
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db),
) -> DocumentInsights:
    return read_document_insights(db, user_id, project_id, days=days, search=search, offset=offset)


@router.put("/documents/{file_id}/review")
def mark_document_reviewed(
    file_id: uuid.UUID, body: ReviewInput,
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db),
):
    return review_document(db, user_id, file_id, body)


@router.get("", response_model=KnowledgeHealth)
def knowledge_health(
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db),
) -> KnowledgeHealth:
    return read_health(db, scope=Project.owner_id == user_id)


@router.get("/trends", response_model=QualityTrends)
def quality_trends(
    days: int = 30, project_id: uuid.UUID | None = None,
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db),
) -> QualityTrends:
    return read_trends(db, user_id, days=days, project_id=project_id)


@router.get("/evaluation-trends", response_model=EvaluationTrends)
def evaluation_trends(
    project_id: uuid.UUID, days: int = 30,
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db),
) -> EvaluationTrends:
    return read_evaluation_trends(db, user_id, days=days, project_id=project_id)
