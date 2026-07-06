from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project
from ..schemas import QueryRequest, QueryResponse
from ..sse import sse_response
from ..services.query import run_query, run_query_stream
from .deps import get_owned_project

router = APIRouter(prefix="/api/projects/{project_id}", tags=["playground"])


@router.post("/query", response_model=QueryResponse)
def playground_query(
    body: QueryRequest,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    return run_query(
        db,
        project,
        body.question,
        body.top_k,
        api_key_id=None,
        conversation_id=body.conversation_id,
    )


@router.post("/query/stream")
def playground_query_stream(
    body: QueryRequest,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Same answer as /query, streamed token by token over SSE."""
    return sse_response(
        run_query_stream(
            db,
            project,
            body.question,
            body.top_k,
            api_key_id=None,
            conversation_id=body.conversation_id,
        )
    )
