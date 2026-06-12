from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project
from ..schemas import QueryRequest, QueryResponse
from ..services.query import run_query
from .deps import get_owned_project

router = APIRouter(prefix="/api/projects/{project_id}", tags=["playground"])


@router.post("/query", response_model=QueryResponse)
def playground_query(
    body: QueryRequest,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    return run_query(db, project, body.question, body.top_k, api_key_id=None)
