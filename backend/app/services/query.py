import time
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Chunk, Project, QueryLog
from ..providers.base import ProviderUnavailableError
from ..schemas import QueryResponse, SourceChunk
from . import generation, retrieval


def run_query(
    db: Session,
    project: Project,
    question: str,
    top_k_override: int | None,
    api_key_id: uuid.UUID | None,
) -> QueryResponse:
    """Shared by the dashboard playground and the public /v1 endpoint."""
    chunk_count = db.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.project_id == project.id)
    )
    if not chunk_count:
        raise HTTPException(
            status_code=409,
            detail="Project has no indexed content yet — upload files and wait for indexing",
        )

    top_k = min(top_k_override or project.top_k, 20)
    started = time.perf_counter()
    try:
        sources = retrieval.retrieve(db, project, question, top_k)
        answer = generation.generate_answer(db, project, question, sources)
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    latency_ms = int((time.perf_counter() - started) * 1000)

    db.add(
        QueryLog(
            project_id=project.id,
            api_key_id=api_key_id,
            question=question,
            top_k=top_k,
            latency_ms=latency_ms,
        )
    )
    db.commit()

    return QueryResponse(
        answer=answer,
        sources=[SourceChunk(**s) for s in sources],
        model=f"{project.llm_provider}/{project.llm_model}",
        latency_ms=latency_ms,
    )
