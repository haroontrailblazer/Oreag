"""Account-owned, validated query filter presets. No query contents are copied."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import Project, SavedQueryView

router = APIRouter(prefix="/api/account/query-views", tags=["saved views"])


class SaveView(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: uuid.UUID
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["queries", "failures"]
    filters: dict[str, str]

    @model_validator(mode="after")
    def valid_filters(self):
        options = {"project": None, "search": None, "latency": {"", "1000", "3000", "10000"}}
        options.update({"days": {"7", "30", "90"}, "cache": {"all", "fresh", "l1", "l2"},
                        "feedback": {"all", "helpful", "not_helpful", "unrated"}} if self.kind == "queries" else
                       {"hours": {"1", "24", "168", "720"}, "outcome": {"all", "error", "rejected", "stream_error", "disconnected"}, "status": None})
        if set(self.filters) != set(options):
            raise ValueError("Filters do not match this view")
        for key, value in self.filters.items():
            if len(value) > 200 or "\x00" in value or (options[key] is not None and value not in options[key]):
                raise ValueError(f"Invalid {key} filter")
        if "\x00" in self.name:
            raise ValueError("Invalid view name")
        if self.filters["project"]:
            uuid.UUID(self.filters["project"])
        status = self.filters.get("status", "")
        if status and (not status.isascii() or not status.isdigit() or not 100 <= int(status) <= 599):
            raise ValueError("Invalid HTTP status")
        return self


def output(row):
    return {"id": str(row.id), "name": row.name, "kind": row.kind, "filters": row.filters}


@router.get("")
def list_views(kind: Literal["queries", "failures"], user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return [output(row) for row in db.scalars(select(SavedQueryView).where(
        SavedQueryView.owner_id == user_id, SavedQueryView.kind == kind).order_by(SavedQueryView.name, SavedQueryView.id).limit(50))]


@router.put("/{view_id}")
def save_view(view_id: uuid.UUID, body: SaveView, user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    if view_id != body.id:
        raise HTTPException(422, "View IDs must match")
    project_id = body.filters["project"]
    if project_id and db.scalar(select(Project.id).where(Project.id == uuid.UUID(project_id), Project.owner_id == user_id)) is None:
        raise HTTPException(404, "Project not found")
    row = db.get(SavedQueryView, view_id)
    if row and row.owner_id != user_id:
        raise HTTPException(404, "View not found")
    if row is None:
        if db.scalar(select(func.count()).select_from(SavedQueryView).where(SavedQueryView.owner_id == user_id)) >= 50:
            raise HTTPException(422, "You can save up to 50 views. Remove an unused view first.")
        row = SavedQueryView(id=view_id, owner_id=user_id)
        db.add(row)
    row.name, row.kind, row.filters = body.name, body.kind, body.filters
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A view with this name already exists. Choose another name.") from None
    return output(row)


@router.delete("/{view_id}", status_code=204)
def delete_view(view_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(SavedQueryView).where(SavedQueryView.id == view_id, SavedQueryView.owner_id == user_id))
    if row is None:
        raise HTTPException(404, "View not found")
    db.delete(row)
    db.commit()
