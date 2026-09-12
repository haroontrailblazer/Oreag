"""Bounded owner-scoped review of repeated questions; no provider calls.

GETs never write. Stable keys normalize wording rather than guessing semantic
equivalence: numbers, negation, word order and internal punctuation survive.
Saved resolutions are independent of the selected reporting window.
"""
import hashlib
import json
import math
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..knowledge_gap_schemas import GapDetail, GapEvidence, GapItem, GapReport, GapReviewInput
from ..models import KnowledgeGapReview, Project, QueryLog

SCAN_LIMIT = 5000
WEAK_SIMILARITY = 0.35  # A review heuristic, not an answer-policy threshold.
# Conservative, whole-message matches only. A greeting followed by a real
# question ("Hi, how do refunds work?") must still be checked for evidence.
CONVERSATIONAL_MESSAGES = frozenset({
    "hi", "hello", "hey", "greetings", "hi there", "hello there", "hey there",
    "good morning", "good afternoon", "good evening", "good night",
    "thanks", "thank you", "thanks a lot", "thank you very much",
    "bye", "goodbye", "see you", "see you later",
    "how are you", "how are you doing", "how's it going", "what's up",
})


def _is_conversational_only(question: str) -> bool:
    normalized = unicodedata.normalize("NFC", question).casefold()
    normalized = re.sub(r"\s+", " ", normalized).strip().replace("’", "'")
    normalized = re.sub(r"^[\W_]+|[\W_]+$", "", normalized)
    return normalized in CONVERSATIONAL_MESSAGES


def question_key(question: str) -> str:
    normalized = unicodedata.normalize("NFC", question).casefold()
    normalized = re.sub(r"\s+", " ", normalized).strip().rstrip("?!。？！").rstrip()
    return hashlib.sha256(("wording-v1:" + normalized).encode("utf-8")).hexdigest()


def _utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def _flags(row) -> tuple[bool, bool]:
    similarity = row["retrieval_similarity"]
    return (
        row["feedback_rating"] == "not_helpful",
        row["cache_layer"] is None and similarity is not None
        and math.isfinite(similarity) and similarity < WEAK_SIMILARITY
        and not _is_conversational_only(row["question"]),
    )


@dataclass
class Snapshot:
    now: datetime
    rows: list
    groups: dict
    reviews: dict
    limited: bool


def _snapshot(db: Session, owner: uuid.UUID, days: int, project_id: uuid.UUID | None) -> Snapshot:
    if days not in (7, 30, 90):
        raise HTTPException(422, "Time range must be 7, 30, or 90 days")
    scope = [Project.owner_id == owner]
    if project_id is not None:
        scope.append(Project.id == project_id)
        if not db.scalar(select(Project.id).where(*scope)):
            raise HTTPException(404, "Project not found")
    now = datetime.now(timezone.utc)
    rows = db.execute(select(
        QueryLog.id, QueryLog.project_id, Project.name.label("project_name"),
        QueryLog.question, QueryLog.created_at, QueryLog.cache_layer,
        QueryLog.retrieval_similarity, QueryLog.feedback_rating,
        QueryLog.feedback_note, QueryLog.feedback_updated_at,
    ).join(Project, Project.id == QueryLog.project_id).where(
        *scope, QueryLog.created_at >= now - timedelta(days=days), QueryLog.created_at <= now,
    ).order_by(QueryLog.id.desc()).limit(SCAN_LIMIT + 1)).mappings().all()
    limited = len(rows) > SCAN_LIMIT
    rows = rows[:SCAN_LIMIT]
    groups = {}
    for row in rows:
        key = (row["project_id"], question_key(row["question"]))
        groups.setdefault(key, []).append(row)
    reviews = {
        (review.project_id, review.question_key): review
        for review in db.scalars(select(KnowledgeGapReview).join(
            Project, Project.id == KnowledgeGapReview.project_id
        ).where(*scope, tuple_(KnowledgeGapReview.project_id, KnowledgeGapReview.question_key).in_(list(groups))))
    } if groups else {}
    return Snapshot(now, rows, groups, reviews, limited)


def _item(key, rows, review: KnowledgeGapReview | None, *, full_question: bool = False) -> GapItem:
    flags = [_flags(row) for row in rows]
    resolved_at = _utc(review.resolved_at) if review else None
    # New query evidence and feedback added to an older query both reopen a
    # resolution. GET merely derives this state; it never changes the review.
    reopened = bool(review and review.status == "resolved" and any(
        (negative or weak) and (
            row["id"] > (review.resolved_through_id or 0)
            or _utc(row["created_at"]) > resolved_at
            or (negative and _utc(row["feedback_updated_at"]) is not None
                and _utc(row["feedback_updated_at"]) > resolved_at)
        ) for row, (negative, weak) in zip(rows, flags)
    ))
    # Include all current evidence in the version, including edited notes and
    # removed ratings. A stale tab must refresh before acknowledging changes.
    version = hashlib.sha256(json.dumps([
        [row["id"], row["feedback_rating"], row["feedback_note"],
         str(row["feedback_updated_at"]), row["retrieval_similarity"], row["cache_layer"]]
        for row in rows
    ], ensure_ascii=False).encode("utf-8")).hexdigest()
    return GapItem(
        project_id=key[0], project_name=rows[0]["project_name"], question_key=key[1],
        question=rows[0]["question"] if full_question else rows[0]["question"][:240],
        query_count=len(rows), flagged_count=sum(negative or weak for negative, weak in flags),
        not_helpful_count=sum(negative for negative, _ in flags),
        weak_evidence_count=sum(weak for _, weak in flags),
        helpful_count=sum(row["feedback_rating"] == "helpful" for row in rows),
        unmeasured_count=sum(row["cache_layer"] is None and row["retrieval_similarity"] is None for row in rows),
        first_seen=min(_utc(row["created_at"]) for row in rows),
        last_seen=max(_utc(row["created_at"]) for row in rows),
        status="open" if reopened or review is None else review.status,
        reopened=reopened, revision=review.revision if review else 0,
        note=review.note if review else None, resolved_at=resolved_at,
        updated_at=_utc(review.updated_at) if review else None, evidence_version=version,
    )


def report(db: Session, owner: uuid.UUID, *, days=30, project_id=None, status="open", search="", recurring=False, offset=0, limit=25) -> GapReport:
    snapshot = _snapshot(db, owner, days, project_id)
    items = [_item(key, rows, snapshot.reviews.get(key)) for key, rows in snapshot.groups.items()]
    items = [item for item in items if item.flagged_count or item.revision]
    open_groups = sum(item.status == "open" for item in items)
    resolved_groups = len(items) - open_groups
    flagged_queries = sum(item.flagged_count for item in items)
    needle = search.strip().casefold()
    filtered = [item for item in items if
                (status == "all" or item.status == status)
                and (not recurring or item.query_count >= 2)
                and (not needle or any(needle in row["question"].casefold()
                     for row in snapshot.groups[(item.project_id, item.question_key)]))]
    filtered.sort(key=lambda item: (item.status != "open", -item.flagged_count, -item.query_count,
                                   -item.last_seen.timestamp(), str(item.project_id), item.question_key))
    return GapReport(
        generated_at=snapshot.now, window_days=days, scanned_queries=len(snapshot.rows),
        scan_limit=SCAN_LIMIT, limited=snapshot.limited, weak_similarity_threshold=WEAK_SIMILARITY,
        open_groups=open_groups, resolved_groups=resolved_groups, flagged_queries=flagged_queries,
        matched_groups=len(filtered), items=filtered[offset:offset + limit],
        next_offset=offset + limit if offset + limit < len(filtered) else None,
    )


def _selected(snapshot, project_id, key):
    group_key = (project_id, key)
    rows = snapshot.groups.get(group_key)
    if not rows:
        raise HTTPException(404, "Gap evidence is no longer in this window. Refresh the inbox.")
    item = _item(group_key, rows, snapshot.reviews.get(group_key), full_question=True)
    if not item.flagged_count and not item.revision:
        raise HTTPException(404, "This question has no current gap signals")
    return item, rows


def detail(db: Session, owner: uuid.UUID, project_id: uuid.UUID, key: str, *, days=30, offset=0, limit=25) -> GapDetail:
    snapshot = _snapshot(db, owner, days, project_id)
    item, rows = _selected(snapshot, project_id, key)
    # Negative/weak evidence first, then newest within each category.
    ordered = sorted(rows, key=lambda row: (not any(_flags(row)), -row["id"]))
    return GapDetail(
        item=item, window_days=days, limited=snapshot.limited, scanned_queries=len(snapshot.rows),
        scan_limit=SCAN_LIMIT, weak_similarity_threshold=WEAK_SIMILARITY,
        evidence=[GapEvidence(
            id=str(row["id"]), question=row["question"], created_at=_utc(row["created_at"]),
            feedback_rating=row["feedback_rating"], feedback_note=row["feedback_note"],
            retrieval_similarity=row["retrieval_similarity"], cache_layer=row["cache_layer"],
            not_helpful=_flags(row)[0], weak_evidence=_flags(row)[1],
        ) for row in ordered[offset:offset + limit]],
        evidence_total=len(rows), next_offset=offset + limit if offset + limit < len(rows) else None,
    )


def save_review(db: Session, owner: uuid.UUID, project_id: uuid.UUID, key: str, body: GapReviewInput, *, days=30) -> GapDetail:
    snapshot = _snapshot(db, owner, days, project_id)
    item, rows = _selected(snapshot, project_id, key)
    if body.revision != item.revision or body.evidence_version != item.evidence_version:
        raise HTTPException(409, "Evidence or review changed. Refresh this gap before saving.")
    values = dict(
        status=body.status, note=body.note or None, revision=body.revision + 1,
        updated_at=snapshot.now,
        resolved_at=snapshot.now if body.status == "resolved" else None,
        resolved_through_id=max(row["id"] for row in rows) if body.status == "resolved" else None,
    )
    try:
        if body.revision == 0:
            db.add(KnowledgeGapReview(project_id=project_id, question_key=key, **values))
        else:
            result = db.execute(update(KnowledgeGapReview).where(
                KnowledgeGapReview.project_id == project_id,
                KnowledgeGapReview.question_key == key,
                KnowledgeGapReview.revision == body.revision,
                KnowledgeGapReview.project_id.in_(select(Project.id).where(Project.owner_id == owner)),
            ).values(**values))
            if result.rowcount != 1:
                db.rollback()
                raise HTTPException(409, "Review changed. Refresh this gap before saving.")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Review changed. Refresh this gap before saving.") from None
    return detail(db, owner, project_id, key, days=days)
