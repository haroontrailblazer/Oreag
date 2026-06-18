import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.api_keys import require_api_key
from ..db import get_db
from ..models import ApiKey, Memory, Project
from ..providers.base import ProviderUnavailableError
from ..schemas import (
    MemoryCreate,
    MemoryOut,
    MemorySearchRequest,
    MemorySearchResult,
)
from ..services import memory as memory_service
from .deps import get_owned_project
from .rag_v1 import _get_project

public_router = APIRouter(prefix="/v1/projects/{project_id}", tags=["memory"])
owner_router = APIRouter(prefix="/api/projects/{project_id}", tags=["memory"])


# --- Public (MCP, oreag_sk_ key) ------------------------------------------


@public_router.post("/memory", response_model=MemoryOut, status_code=201)
def create_memory(
    project_id: uuid.UUID,
    body: MemoryCreate,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    memory = memory_service.save_memory(db, project, body)
    out = MemoryOut.model_validate(memory)
    if memory.embedding is None:
        out.warning = (
            "Stored without an embedding (no embedding key) — not searchable yet."
        )
    return out


@public_router.post("/memory/search", response_model=list[MemorySearchResult])
def search_memory(
    project_id: uuid.UUID,
    body: MemorySearchRequest,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    try:
        results = memory_service.search_memories(
            db, project, body.query, body.top_k or 5
        )
    except ProviderUnavailableError as exc:
        raise HTTPException(503, str(exc))
    return [
        MemorySearchResult(
            **MemoryOut.model_validate(m).model_dump(), similarity=sim
        )
        for m, sim in results
    ]


@public_router.get("/memory/recent", response_model=list[MemoryOut])
def recent_memory(
    project_id: uuid.UUID,
    limit: int = 10,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    return memory_service.recent_memories(db, project, min(max(limit, 1), 50))


@public_router.delete("/memory/{memory_id}", status_code=204)
def delete_memory(
    project_id: uuid.UUID,
    memory_id: int,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    row = db.scalar(
        select(Memory).where(Memory.id == memory_id, Memory.project_id == project.id)
    )
    if row is not None:
        db.delete(row)
        db.commit()


# --- Owner (dashboard, JWT) -----------------------------------------------


@owner_router.get("/memory", response_model=list[MemoryOut])
def list_memory(
    limit: int = 100,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    return memory_service.recent_memories(db, project, min(max(limit, 1), 500))


@owner_router.delete("/memory/{memory_id}", status_code=204)
def owner_delete_memory(
    memory_id: int,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(Memory).where(Memory.id == memory_id, Memory.project_id == project.id)
    )
    if row is not None:
        db.delete(row)
        db.commit()
