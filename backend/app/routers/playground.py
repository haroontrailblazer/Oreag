from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project, QueryLog
from ..schemas import QueryRequest, QueryResponse
from ..sse import sse_response
from ..services.query import run_query, run_query_stream
from .deps import get_owned_project

router = APIRouter(prefix="/api/projects/{project_id}", tags=["playground"])


@router.get("/query-stats")
def query_stats(
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
) -> dict:
    """Project-wide cache performance across EVERY query surface (the
    playground and the public /v1 API both write query_logs), so the hit rate
    reflects the whole project, not one chat session."""

    def count(*where) -> int:
        return (
            db.scalar(
                select(func.count())
                .select_from(QueryLog)
                .where(QueryLog.project_id == project.id, *where)
            )
            or 0
        )

    total = count()
    l1 = count(QueryLog.cache_layer == "l1")
    l2 = count(QueryLog.cache_layer == "l2")
    hits = l1 + l2
    return {
        "queries": total,
        "cache_hits": hits,
        "l1": l1,
        "l2": l2,
        "hit_rate": round(hits / total, 4) if total else 0.0,
    }


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
