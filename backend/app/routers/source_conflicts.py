import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project
from ..services import source_conflicts as service
from .deps import get_owned_project, heavy_dashboard_limit

router = APIRouter(prefix="/api/projects/{project_id}/source-conflicts", tags=["source conflict review"])


class ReviewConflict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Literal["open", "confirmed", "dismissed"]
    note: str = Field(default="", max_length=2000, pattern=r"^[^\x00]*$")
    revision: int = Field(ge=0, le=2_147_483_646)
    content_version: int = Field(ge=0)


@router.get("")
def report(project: Project = Depends(get_owned_project), db: Session = Depends(get_db), _: uuid.UUID = Depends(heavy_dashboard_limit)):
    return service.report(db, project)


@router.put("/{key}")
def review(key: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")], body: ReviewConflict,
           project: Project = Depends(get_owned_project), db: Session = Depends(get_db), _: uuid.UUID = Depends(heavy_dashboard_limit)):
    return service.save(db, project, key, body)
