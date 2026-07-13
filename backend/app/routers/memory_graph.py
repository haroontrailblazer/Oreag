import time
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.api_keys import require_api_key
from ..models import ApiKey, Project
from ..schemas import MemoryGraphResponse
from ..services.memory_graph import build_memory_graph
from ..services.rate_limit import enforce_rate_limit
from ..services.usage import record_usage
from .deps import get_owned_project
from ..db import get_db
from .rag_v1 import _get_project

owner_router = APIRouter(prefix="/api/projects/{project_id}", tags=["memory-graph"])
public_router = APIRouter(prefix="/v1/projects/{project_id}", tags=["public-api"])


@owner_router.get("/memory-graph", response_model=MemoryGraphResponse)
def owner_memory_graph(
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    return build_memory_graph(db, project)


@public_router.get("/memory-graph", response_model=MemoryGraphResponse)
def public_memory_graph(
    project_id: uuid.UUID,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    # Walking every file + chunk makes this the API's priciest GET - heavy
    # budget (the per-content_version cache below keeps honest use cheap).
    enforce_rate_limit(api_key.id, project.id, heavy=True)
    started = time.perf_counter()
    graph = build_memory_graph(db, project)
    record_usage(
        db,
        project=project,
        api_key_id=api_key.id,
        endpoint="memory_graph",
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return graph
