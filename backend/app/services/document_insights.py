"""Document attribution and explicit content reviews, scoped to project owners.

No provider calls or freshness guesses from an upload/indexing timestamp.
Attribution is bounded, deduplicated per query, and never an accuracy score.
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import DocumentReview, File, Project, QueryLog

SCAN_LIMIT = 10_000
PAGE_SIZE = 20
REVIEW_DAYS = 90


def _utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def source_attribution(sources: list[dict]) -> list[dict] | None:
    """Sources already have citation flags from the existing answer parser."""
    documents: dict[str, bool] = {}
    for source in sources:
        if source.get("filename") == "memory" and source.get("chunk_index") == -1:
            continue
        try:
            file_id = str(uuid.UUID(str(source["file_id"])))
        except (KeyError, ValueError, TypeError, AttributeError):
            # Legacy cache entries lack IDs; filenames cannot identify editions.
            return None
        documents[file_id] = documents.get(file_id, False) or source.get("cited") is True
    return [{"file_id": key, "cited": documents[key]} for key in sorted(documents)]


def content_signature(file: File) -> str:
    # Re-indexing identical text preserves a review. If hashes are unavailable,
    # the indexing timestamp is a conservative version token, not proof of age.
    payload = [str(file.id), file.content_sha256, file.markdown_sha256,
               str(_utc(file.indexed_at)) if not file.markdown_sha256 else None,
               str(file.in_force_from), file.legal_status, file.relation_kind]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


class DocumentInsight(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    chunk_count: int
    created_at: datetime
    indexed_at: datetime | None
    content_signature: str
    reviewed_at: datetime | None
    review_due_at: datetime | None
    freshness: Literal["not_reviewed", "reviewed", "review_due", "changed", "not_searchable"]
    included_queries: int | None
    cited_answers: int | None
    helpful: int
    not_helpful: int
    last_cited_at: datetime | None


class DocumentInsights(BaseModel):
    generated_at: datetime
    project_id: uuid.UUID
    window_days: int
    review_after_days: int = REVIEW_DAYS
    query_count: int
    tracked_queries: int
    answers_with_citations: int
    tracking_started_at: datetime | None
    limited: bool
    scan_limit: int = SCAN_LIMIT
    total_documents: int
    matching_documents: int
    offset: int
    page_size: int = PAGE_SIZE
    items: list[DocumentInsight]


class ReviewInput(BaseModel):
    content_signature: str = Field(pattern=r"^[0-9a-f]{64}$")


def _freshness(file: File, review: DocumentReview | None, now: datetime):
    signature = content_signature(file)
    reviewed_at = _utc(review.reviewed_at) if review else None
    due_at = reviewed_at + timedelta(days=REVIEW_DAYS) if reviewed_at else None
    if file.status != "indexed" or not file.chunk_count:
        state = "not_searchable"
    elif not review:
        state = "not_reviewed"
    elif review.content_signature != signature:
        state = "changed"
    elif due_at <= now:
        state = "review_due"
    else:
        state = "reviewed"
    return signature, reviewed_at, due_at, state


def _scope(db, owner, project_id):
    if not db.scalar(select(Project.id).where(Project.id == project_id, Project.owner_id == owner)):
        raise HTTPException(404, "Project not found")


def read_document_insights(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID, *, days=30, search="", offset=0, as_of=None,
) -> DocumentInsights:
    _scope(db, owner, project_id)
    if days not in (7, 30, 90) or offset < 0 or offset > 100_000 or len(search) > 200:
        raise HTTPException(422, "Choose 7, 30, or 90 days and a valid document page")
    now = _utc(as_of) if as_of else datetime.now(timezone.utc)
    query_filters = [QueryLog.project_id == project_id, QueryLog.created_at >= now - timedelta(days=days), QueryLog.created_at <= now]
    rows = db.execute(select(QueryLog.document_sources, QueryLog.feedback_rating, QueryLog.created_at)
        .where(*query_filters).order_by(QueryLog.created_at.desc(), QueryLog.id.desc())
        .limit(SCAN_LIMIT + 1)).mappings().all()
    limited = len(rows) > SCAN_LIMIT
    rows = rows[:SCAN_LIMIT]
    tracked = citations = 0
    started = None
    impact: dict[str, dict] = {}
    for row in rows:
        sources = row["document_sources"]
        if not isinstance(sources, list):
            continue
        # Defensive parsing keeps malformed historical telemetry unmeasured.
        try:
            docs = {}
            for source in sources:
                key = str(uuid.UUID(source["file_id"]))
                if not isinstance(source["cited"], bool):
                    raise ValueError("Invalid citation flag")
                docs[key] = docs.get(key, False) or source["cited"]
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
        tracked += 1
        stamp = _utc(row["created_at"])
        started = min(started, stamp) if started else stamp
        citations += any(docs.values())
        for key, cited in docs.items():
            stats = impact.setdefault(key, dict(included_queries=0, cited_answers=0, helpful=0, not_helpful=0, last_cited_at=None))
            stats["included_queries"] += 1
            if cited:
                stats["cited_answers"] += 1
                stats["helpful"] += row["feedback_rating"] == "helpful"
                stats["not_helpful"] += row["feedback_rating"] == "not_helpful"
                stats["last_cited_at"] = max(stats["last_cited_at"], stamp) if stats["last_cited_at"] else stamp

    current = [File.project_id == project_id, File.in_force_to.is_(None)]
    total = db.scalar(select(func.count()).select_from(File).where(*current)) or 0
    filters = [*current]
    if search.strip():
        filters.append(File.filename.icontains(search.strip(), autoescape=True))
    matching = db.scalar(select(func.count()).select_from(File).where(*filters)) or 0
    files = db.execute(select(File, DocumentReview).outerjoin(DocumentReview,
        (DocumentReview.file_id == File.id) & (DocumentReview.project_id == File.project_id))
        .where(*filters).order_by(func.lower(File.filename), File.id).offset(offset).limit(PAGE_SIZE)).all()
    items = []
    for file, review in files:
        signature, reviewed_at, due_at, state = _freshness(file, review, now)
        stats = impact.get(str(file.id), dict(included_queries=0 if tracked else None,
            cited_answers=0 if tracked else None, helpful=0, not_helpful=0, last_cited_at=None))
        items.append(DocumentInsight(id=file.id, filename=file.filename, status=file.status,
            chunk_count=file.chunk_count, created_at=_utc(file.created_at), indexed_at=_utc(file.indexed_at),
            content_signature=signature, reviewed_at=reviewed_at, review_due_at=due_at, freshness=state, **stats))
    return DocumentInsights(generated_at=now, project_id=project_id, window_days=days,
        query_count=len(rows), tracked_queries=tracked, answers_with_citations=citations,
        tracking_started_at=started, limited=limited, scan_limit=SCAN_LIMIT, total_documents=total,
        matching_documents=matching, offset=offset, items=items)


def review_document(db: Session, owner: uuid.UUID, file_id: uuid.UUID, body: ReviewInput):
    file = db.scalar(select(File).join(Project, Project.id == File.project_id)
        .where(File.id == file_id, Project.owner_id == owner, File.in_force_to.is_(None))
        .with_for_update(of=File))
    if file is None:
        raise HTTPException(404, "Document not found")
    if file.status != "indexed" or not file.chunk_count:
        raise HTTPException(409, "Wait until this document is searchable before recording a review")
    if content_signature(file) != body.content_signature:
        raise HTTPException(409, "This document changed. Refresh it before recording your review")
    review = db.get(DocumentReview, file.id)
    if review is None:
        review = DocumentReview(file_id=file.id, project_id=file.project_id)
        db.add(review)
    review.content_signature = body.content_signature
    review.reviewed_at = datetime.now(timezone.utc)
    review.reviewed_by = owner
    db.commit()
    return {"file_id": str(file.id), "reviewed_at": review.reviewed_at, "review_after_days": REVIEW_DAYS}
