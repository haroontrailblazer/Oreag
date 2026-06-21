import time
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Chunk, Memory, Project, QueryLog
from ..providers.base import ProviderUnavailableError
from ..schemas import QueryResponse, SourceChunk
from . import generation
from . import memory as memory_service
from . import retrieval


def run_query(
    db: Session,
    project: Project,
    question: str,
    top_k_override: int | None,
    api_key_id: uuid.UUID | None,
) -> QueryResponse:
    """Shared by the dashboard playground and the public /v1 endpoint.

    Answers from the project's "brain": document chunks plus any relevant agent
    memories (both live in the same per-project embedding space).
    """
    chunk_count = (
        db.scalar(select(func.count()).select_from(Chunk).where(Chunk.project_id == project.id))
        or 0
    )
    memory_count = (
        db.scalar(
            select(func.count())
            .select_from(Memory)
            .where(Memory.project_id == project.id, Memory.embedding.isnot(None))
        )
        or 0
    )
    if not chunk_count and not memory_count:
        raise HTTPException(
            status_code=409,
            detail="Project has no indexed content yet — upload files (or save memories) and wait for indexing",
        )

    top_k = min(top_k_override or project.top_k, 20)
    started = time.perf_counter()
    try:
        sources = retrieval.retrieve(db, project, question, top_k) if chunk_count else []
        # Blend in relevant memories — same vector space, so directly comparable.
        if memory_count and settings.rag_memory_blend_k > 0:
            try:
                for mem, sim in memory_service.search_memories(
                    db, project, question, settings.rag_memory_blend_k
                ):
                    if sim >= settings.rag_memory_min_similarity:
                        sources.append(
                            {
                                "filename": "memory",
                                "page_number": None,
                                "chunk_index": -1,
                                "content": mem.content,
                                "similarity": sim,
                            }
                        )
            except ProviderUnavailableError:
                pass  # no embedding key for memory search — answer from docs only
        sources.sort(key=lambda s: s["similarity"], reverse=True)
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
