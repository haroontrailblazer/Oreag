import logging
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Memory, Project
from ..providers import resolver
from ..providers.base import ProviderUnavailableError
from ..providers.registry import get_embedder
from ..schemas import MemoryCreate

logger = logging.getLogger(__name__)


def _embed(db: Session, project: Project, content: str) -> list[float] | None:
    """Best-effort embedding of a memory. Returns None if no key / on failure."""
    key = resolver.resolve_embedding_key(db, project)
    if resolver.requires_key(project.embedding_provider) and not key:
        return None
    try:
        embedder = get_embedder(
            project.embedding_provider,
            project.embedding_model,
            key,
            dimensions=project.embedding_dimensions,
        )
        return embedder.embed_texts([content])[0]
    except Exception:
        logger.exception("Memory embedding failed; storing without embedding")
        return None


def reembed_project_memories(project_id: uuid.UUID) -> None:
    """Background task: re-embed every memory with the project's CURRENT model.

    Runs after an embedding model switch - old-model memory vectors live in an
    incompatible space (the caller nulls them out first so search never mixes
    spaces). Best-effort per memory: a failure leaves that one unembedded
    rather than aborting the rest. Owns its DB session (threadpool task).
    """
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if project is None:
            return
        memories = db.scalars(
            select(Memory).where(Memory.project_id == project_id)
        ).all()
        for memory in memories:
            memory.embedding = _embed(db, project, memory.content)
        db.commit()
        logger.info(
            "Re-embedded %d memories for project %s with %s/%s",
            len(memories),
            project_id,
            project.embedding_provider,
            project.embedding_model,
        )
    except Exception:
        logger.exception("Memory re-embedding failed for project %s", project_id)
        db.rollback()
    finally:
        db.close()


def save_memory(db: Session, project: Project, body: MemoryCreate) -> Memory:
    memory = Memory(
        project_id=project.id,
        content=body.content,
        tags=body.tags,
        pinned=body.pinned,
        source=body.source,
        embedding=_embed(db, project, body.content),
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


_SEARCH_SQL = text(
    """
    SELECT id, 1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
    FROM memories
    WHERE project_id = :project_id AND embedding IS NOT NULL
    ORDER BY embedding <=> CAST(:qvec AS vector)
    LIMIT :top_k
    """
)


def search_memories(
    db: Session, project: Project, query: str, top_k: int
) -> list[tuple[Memory, float]]:
    key = resolver.resolve_embedding_key(db, project)
    if resolver.requires_key(project.embedding_provider) and not key:
        raise ProviderUnavailableError(
            "Memory search needs an embedding key. Add one in Settings → API keys."
        )
    embedder = get_embedder(
        project.embedding_provider,
        project.embedding_model,
        key,
        dimensions=project.embedding_dimensions,
    )
    qvec = "[" + ",".join(repr(v) for v in embedder.embed_query(query)) + "]"
    rows = db.execute(
        _SEARCH_SQL, {"qvec": qvec, "project_id": str(project.id), "top_k": top_k}
    ).all()
    by_id = {
        m.id: m
        for m in db.scalars(select(Memory).where(Memory.id.in_([r.id for r in rows])))
    }
    return [(by_id[r.id], round(float(r.similarity), 4)) for r in rows if r.id in by_id]


def recent_memories(db: Session, project: Project, limit: int) -> list[Memory]:
    return list(
        db.scalars(
            select(Memory)
            .where(Memory.project_id == project.id)
            .order_by(Memory.pinned.desc(), Memory.created_at.desc())
            .limit(limit)
        )
    )
