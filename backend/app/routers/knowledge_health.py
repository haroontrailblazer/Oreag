"""Owner-scoped, read-only knowledge diagnostics; no provider or vector calls."""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import File, Project, QueryLog

router = APIRouter(prefix="/api/account/knowledge-health", tags=["knowledge health"])


class ProjectHealth(BaseModel):
    id: uuid.UUID
    name: str
    suspended: bool
    current_files: int = 0
    searchable_files: int = 0
    indexed_chunks: int = 0
    failed_files: int = 0
    review_files: int = 0
    indexing_files: int = 0
    empty_indexed_files: int = 0
    unknown_files: int = 0
    duplicate_copies: int = 0
    last_indexed_at: datetime | None = None
    fresh_queries: int = 0
    measured_queries: int = 0
    avg_retrieval_similarity: float | None = None


class KnowledgeHealth(BaseModel):
    generated_at: datetime
    query_window_days: int = 30
    projects: list[ProjectHealth]


def _count(condition):
    return func.sum(case((condition, 1), else_=0))


@router.get("", response_model=KnowledgeHealth)
def knowledge_health(
    user_id: uuid.UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeHealth:
    now = datetime.now(timezone.utc)
    # Explicit columns: project credentials and document content never enter
    # the report. Four grouped reads, independent of the number of projects.
    projects = db.execute(select(Project.id, Project.name, Project.suspended)
                          .where(Project.owner_id == user_id)
                          .order_by(Project.name, Project.id)).mappings().all()
    if not projects:
        return KnowledgeHealth(generated_at=now, projects=[])

    current = File.in_force_to.is_(None)
    searchable = and_(File.status == "indexed", File.chunk_count > 0)
    files = db.execute(select(
        File.project_id,
        func.count().label("current_files"),
        _count(searchable).label("searchable_files"),
        func.sum(case((searchable, File.chunk_count), else_=0)).label("indexed_chunks"),
        _count(File.status == "failed").label("failed_files"),
        _count(File.status == "review").label("review_files"),
        _count(File.status.in_(["pending", "processing"])).label("indexing_files"),
        _count(and_(File.status == "indexed", File.chunk_count == 0)).label("empty_indexed_files"),
        _count(File.status.not_in(["pending", "processing", "indexed", "failed", "review"])).label("unknown_files"),
        func.max(case((searchable, File.indexed_at), else_=None)).label("last_indexed_at"),
    ).join(Project, Project.id == File.project_id)
      .where(Project.owner_id == user_id, current).group_by(File.project_id)).mappings().all()
    file_map = {row["project_id"]: dict(row) for row in files}

    # Exact original-upload hashes only, within each project. NULL hashes do
    # not prove duplication; retired editions are not redundant active copies.
    duplicate_groups = select(
        File.project_id, (func.count() - 1).label("extra_copies")
    ).join(Project, Project.id == File.project_id).where(
        Project.owner_id == user_id, current,
        File.content_sha256.is_not(None), File.content_sha256 != "",
    ).group_by(File.project_id, File.content_sha256).having(func.count() > 1).subquery()
    duplicates = dict(db.execute(select(
        duplicate_groups.c.project_id, func.sum(duplicate_groups.c.extra_copies)
    ).group_by(duplicate_groups.c.project_id)).all())

    queries = db.execute(select(
        QueryLog.project_id,
        func.count().label("fresh_queries"),
        func.count(QueryLog.retrieval_similarity).label("measured_queries"),
        func.avg(QueryLog.retrieval_similarity).label("avg_retrieval_similarity"),
    ).join(Project, Project.id == QueryLog.project_id).where(
        Project.owner_id == user_id,
        QueryLog.created_at >= now - timedelta(days=30),
        QueryLog.created_at <= now,
        QueryLog.cache_layer.is_(None),
    ).group_by(QueryLog.project_id)).mappings().all()
    query_map = {row["project_id"]: dict(row) for row in queries}

    items = []
    for project in projects:
        values = {**project, **file_map.get(project["id"], {}), **query_map.get(project["id"], {})}
        values.pop("project_id", None)
        timestamp = values.get("last_indexed_at")
        if timestamp is not None and timestamp.tzinfo is None:
            values["last_indexed_at"] = timestamp.replace(tzinfo=timezone.utc)
        values["duplicate_copies"] = duplicates.get(project["id"], 0)
        items.append(ProjectHealth(**values))
    return KnowledgeHealth(generated_at=now, projects=items)
