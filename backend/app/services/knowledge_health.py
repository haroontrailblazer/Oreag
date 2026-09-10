"""Owner-scoped, read-only knowledge diagnostics; no provider or vector calls."""
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ..models import File, Project, QueryLog

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
    total_queries: int = 0
    cached_queries: int = 0
    helpful_queries: int = 0
    not_helpful_queries: int = 0
    fresh_queries: int = 0
    measured_queries: int = 0
    avg_retrieval_similarity: float | None = None


class KnowledgeHealth(BaseModel):
    generated_at: datetime
    query_window_days: int = 30
    projects: list[ProjectHealth]


def _count(condition):
    return func.sum(case((condition, 1), else_=0))


def read_health(db: Session, *, scope: ColumnElement[bool]) -> KnowledgeHealth:
    now = datetime.now(timezone.utc)
    # Explicit columns: project credentials and document content never enter
    # the report. Four grouped reads, independent of the number of projects.
    projects = db.execute(select(Project.id, Project.name, Project.suspended)
                          .where(scope)
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
      .where(scope, current).group_by(File.project_id)).mappings().all()
    file_map = {row["project_id"]: dict(row) for row in files}

    # Exact original-upload hashes only, within each project. NULL hashes do
    # not prove duplication; retired editions are not redundant active copies.
    duplicate_groups = select(
        File.project_id, (func.count() - 1).label("extra_copies")
    ).join(Project, Project.id == File.project_id).where(
        scope, current,
        File.content_sha256.is_not(None), File.content_sha256 != "",
    ).group_by(File.project_id, File.content_sha256).having(func.count() > 1).subquery()
    duplicates = dict(db.execute(select(
        duplicate_groups.c.project_id, func.sum(duplicate_groups.c.extra_copies)
    ).group_by(duplicate_groups.c.project_id)).all())

    # Every query surface writes this log. Count cached API traffic and feedback
    # too, while keeping retrieval similarity limited to fresh measurements.
    fresh = QueryLog.cache_layer.is_(None)
    queries = db.execute(select(
        QueryLog.project_id,
        func.count().label("total_queries"),
        _count(QueryLog.cache_layer.is_not(None)).label("cached_queries"),
        _count(QueryLog.feedback_rating == "helpful").label("helpful_queries"),
        _count(QueryLog.feedback_rating == "not_helpful").label("not_helpful_queries"),
        _count(fresh).label("fresh_queries"),
        _count(and_(fresh, QueryLog.retrieval_similarity.is_not(None))).label("measured_queries"),
        func.avg(case((fresh, QueryLog.retrieval_similarity), else_=None)).label("avg_retrieval_similarity"),
    ).join(Project, Project.id == QueryLog.project_id).where(
        scope,
        QueryLog.created_at >= now - timedelta(days=30),
        QueryLog.created_at <= now,
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
