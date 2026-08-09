import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project, QueryLog
from ..schemas import QueryRequest, QueryResponse
from ..sse import sse_response
from ..services import tracing
from ..services.query import run_query, run_query_stream
from ..services.usage import record_usage
from .deps import get_owned_project, heavy_dashboard_limit

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
    # Calls a provider, so it takes the small per-user budget on top of the
    # standard one applied in get_current_user.
    _: uuid.UUID = Depends(heavy_dashboard_limit),
):
    # Metered exactly like the public /v1 route. A dashboard question spends
    # the owner's provider quota just as a key-authenticated one does, so
    # leaving it out made the Usage page under-report real spend - and made
    # a question asked in the playground look free.
    usage_out: dict = {}
    with tracing.query_trace(
        project=project,
        question=body.question,
        api_key_id=None,
        conversation_id=body.conversation_id,
    ) as _root:
        response = run_query(
            db,
            project,
            body.question,
            body.top_k,
            api_key_id=None,
            conversation_id=body.conversation_id,
            usage_out=usage_out,
        )
        if _root is not None:
            _root.update(
                output={"answer": response.answer, "sources": len(response.sources)},
                metadata={"cache_layer": usage_out.get("cache_layer")},
            )
    record_usage(
        db,
        project=project,
        api_key_id=None,
        endpoint="playground_query",
        latency_ms=response.latency_ms,
        usage=usage_out.get("usage"),
        saved=usage_out.get("saved"),
        cache_layer=usage_out.get("cache_layer"),
    )
    return response


@router.post("/query/stream")
def playground_query_stream(
    body: QueryRequest,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
    # Calls a provider, so it takes the small per-user budget on top of the
    # standard one applied in get_current_user.
    _: uuid.UUID = Depends(heavy_dashboard_limit),
) -> StreamingResponse:
    """Same answer as /query, streamed token by token over SSE."""
    usage_out: dict = {}
    events = run_query_stream(
        db,
        project,
        body.question,
        body.top_k,
        api_key_id=None,
        conversation_id=body.conversation_id,
        usage_out=usage_out,
    )

    def stream_and_record():
        # See the public stream route: the trace and the usage write both have
        # to live inside the generator, because the router returns before a
        # single token exists.
        with tracing.query_trace(
            project=project,
            question=body.question,
            api_key_id=None,
            conversation_id=body.conversation_id,
        ):
            try:
                yield from events
            finally:
                record_usage(
                    db,
                    project=project,
                    api_key_id=None,
                    endpoint="playground_query_stream",
                    latency_ms=usage_out.get("latency_ms"),
                    usage=usage_out.get("usage"),
                    saved=usage_out.get("saved"),
                    cache_layer=usage_out.get("cache_layer"),
                )

    return sse_response(stream_and_record())
