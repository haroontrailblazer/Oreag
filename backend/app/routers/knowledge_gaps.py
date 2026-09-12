import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user
from ..db import get_db
from ..knowledge_gap_schemas import GapDetail, GapReport, GapReviewInput
from ..services import knowledge_gaps as service

router = APIRouter(prefix="/api/account/knowledge-gaps", tags=["knowledge gaps"])
GapKey = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


@router.get("", response_model=GapReport)
def list_gaps(
    days: int = Query(30, ge=7, le=90), project_id: uuid.UUID | None = None,
    status: Literal["open", "resolved", "all"] = "open",
    search: str = Query("", max_length=200), recurring: bool = False,
    offset: int = Query(0, ge=0, le=5000), limit: int = Query(25, ge=1, le=100),
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db),
) -> GapReport:
    return service.report(db, user_id, days=days, project_id=project_id, status=status,
                          search=search, recurring=recurring, offset=offset, limit=limit)


@router.get("/{project_id}/{key}", response_model=GapDetail)
def get_gap(
    project_id: uuid.UUID, key: GapKey, days: int = Query(30, ge=7, le=90),
    offset: int = Query(0, ge=0, le=5000), limit: int = Query(25, ge=1, le=100),
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db),
) -> GapDetail:
    return service.detail(db, user_id, project_id, key, days=days, offset=offset, limit=limit)


@router.put("/{project_id}/{key}", response_model=GapDetail)
def update_gap(
    project_id: uuid.UUID, key: GapKey, body: GapReviewInput, days: int = Query(30, ge=7, le=90),
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db),
) -> GapDetail:
    return service.save_review(db, user_id, project_id, key, body, days=days)
