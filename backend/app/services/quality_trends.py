"""Read-only trends from retained query logs; no model or retrieval calls."""
import math
import hashlib
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from ..models import EvaluationRun, Project, QueryLog
from .knowledge_gaps import WEAK_SIMILARITY, _is_conversational_only, _is_keyboard_noise

SCAN_LIMIT = 10_000
RUN_LIMIT = 200


class QualityMetrics(BaseModel):
    queries: int = 0
    helpful: int = 0
    not_helpful: int = 0
    rated: int = 0
    document_queries: int = 0
    measured: int = 0
    low_match: int = 0
    helpful_percent: float | None = None
    low_match_percent: float | None = None
    avg_similarity: float | None = None


class QualityPeriod(QualityMetrics):
    start: date
    end: date  # exclusive
    complete: bool


class QualityDay(QualityMetrics):
    date: date
    complete: bool


class QualityTrends(BaseModel):
    generated_at: datetime
    window_days: int
    project_id: uuid.UUID | None
    current: QualityPeriod
    previous: QualityPeriod
    daily: list[QualityDay]
    limited: bool
    scanned_queries: int
    scan_limit: int
    weak_similarity_threshold: float


def _metrics(rows) -> dict:
    helpful = sum(row["feedback_rating"] == "helpful" for row in rows)
    negative = sum(row["feedback_rating"] == "not_helpful" for row in rows)
    document_rows = [row for row in rows if row["cache_layer"] is None
                     and not _is_conversational_only(row["question"])
                     and not _is_keyboard_noise(row["question"])]
    similarities = [row["retrieval_similarity"] for row in document_rows
                    if row["retrieval_similarity"] is not None and math.isfinite(row["retrieval_similarity"])]
    weak = sum(value < WEAK_SIMILARITY for value in similarities)
    return dict(queries=len(rows), helpful=helpful, not_helpful=negative, rated=helpful + negative,
                document_queries=len(document_rows), measured=len(similarities), low_match=weak,
                helpful_percent=100 * helpful / (helpful + negative) if helpful + negative else None,
                low_match_percent=100 * weak / len(similarities) if similarities else None,
                avg_similarity=sum(similarities) / len(similarities) if similarities else None)


def read_trends(db: Session, owner: uuid.UUID, *, days=30, project_id=None, as_of=None) -> QualityTrends:
    if days not in (7, 30, 90):
        raise HTTPException(422, "Time range must be 7, 30, or 90 days")
    filters = [Project.owner_id == owner]
    if project_id is not None:
        filters.append(Project.id == project_id)
        if not db.scalar(select(Project.id).where(*filters)):
            raise HTTPException(404, "Project not found")
    now = as_of or datetime.now(timezone.utc)
    end = datetime.combine(now.astimezone(timezone.utc).date(), time.min, timezone.utc)
    start, previous_start = end - timedelta(days=days), end - timedelta(days=2 * days)
    rows = db.execute(select(QueryLog.id, QueryLog.created_at, QueryLog.question,
                             QueryLog.feedback_rating, QueryLog.retrieval_similarity, QueryLog.cache_layer)
        .join(Project, Project.id == QueryLog.project_id)
        .where(*filters, QueryLog.created_at >= previous_start, QueryLog.created_at < end)
        .order_by(QueryLog.created_at.desc(), QueryLog.id.desc()).limit(SCAN_LIMIT + 1)).mappings().all()
    limited = len(rows) > SCAN_LIMIT
    rows = rows[:SCAN_LIMIT]
    by_day = {}
    for row in rows:
        stamp = row["created_at"]
        day = (stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)).date()
        by_day.setdefault(day, []).append(row)
    # The boundary day may be truncated. Never render earlier unseen days as
    # measured zero or compare a truncated period with a complete period.
    cutoff = min(by_day) if limited and by_day else None
    complete = lambda day: cutoff is None or day > cutoff
    current_rows = [row for day, group in by_day.items() if day >= start.date() for row in group]
    previous_rows = [row for day, group in by_day.items() if day < start.date() for row in group]
    return QualityTrends(generated_at=now, window_days=days, project_id=project_id,
        current=QualityPeriod(start=start.date(), end=end.date(), complete=complete(start.date()), **_metrics(current_rows)),
        previous=QualityPeriod(start=previous_start.date(), end=start.date(), complete=complete(previous_start.date()), **_metrics(previous_rows)),
        daily=[QualityDay(date=day, complete=complete(day), **_metrics(by_day.get(day, [])))
               for day in (start.date() + timedelta(days=index) for index in range(days))],
        limited=limited, scanned_queries=len(rows), scan_limit=SCAN_LIMIT,
        weak_similarity_threshold=WEAK_SIMILARITY)


class EvaluationPoint(BaseModel):
    id: uuid.UUID
    created_at: datetime
    variant: int
    passed: int
    checked: int
    errors: int
    unscored: int
    expected: int
    pass_percent: float | None
    latency_ms: float | None
    cost_usd: float | None
    archived: bool


class EvaluationSeries(BaseModel):
    key: str
    cases: int
    models: list[str]
    points: list[EvaluationPoint]


class EvaluationTrends(BaseModel):
    generated_at: datetime
    window_days: int
    project_id: uuid.UUID
    limited: bool
    run_limit: int
    series: list[EvaluationSeries]


def read_evaluation_trends(db: Session, owner: uuid.UUID, *, project_id, days=30, as_of=None) -> EvaluationTrends:
    from .evaluations import run_out
    if days not in (7, 30, 90):
        raise HTTPException(422, "Time range must be 7, 30, or 90 days")
    if not db.scalar(select(Project.id).where(Project.id == project_id, Project.owner_id == owner)):
        raise HTTPException(404, "Project not found")
    now = as_of or datetime.now(timezone.utc)
    runs = db.scalars(select(EvaluationRun).options(undefer(EvaluationRun.archived_payload)).where(EvaluationRun.project_id == project_id,
        EvaluationRun.status == "completed", EvaluationRun.created_at >= now - timedelta(days=days),
        EvaluationRun.created_at <= now).order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
        .limit(RUN_LIMIT + 1)).all()
    groups = {}
    for run in runs[:RUN_LIMIT]:
        saved = run_out(run)  # Archived runs retain their suite/results in compressed storage.
        suite = saved["suite"]
        key = hashlib.sha256(json.dumps(suite, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        group = groups.setdefault(key, EvaluationSeries(key=key, cases=len(suite["cases"]),
            models=[f"{config['llm_provider']}/{config['llm_model']}" for config in suite["variants"]], points=[]))
        for variant in range(len(group.models)):
            rows = [row for row in saved["results"] if row["variant"] == variant]
            passed = sum(row["status"] == "passed" for row in rows)
            checked = sum(row["status"] in ("passed", "failed") for row in rows)
            errors = sum(row["status"] == "error" for row in rows)
            def measured_mean(values):
                return sum(values) / len(values) if len(values) == group.cases and values and all(
                    isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in values) else None
            stamp = run.created_at.replace(tzinfo=timezone.utc) if run.created_at.tzinfo is None else run.created_at
            group.points.append(EvaluationPoint(id=run.id, created_at=stamp, variant=variant, passed=passed,
                checked=checked, errors=errors, unscored=max(0, group.cases - checked - errors), expected=group.cases,
                pass_percent=100 * passed / checked if checked else None,
                latency_ms=measured_mean([(row.get("response") or {}).get("latency_ms") for row in rows]),
                cost_usd=measured_mean([row.get("cost_usd") for row in rows]), archived=run.archived_at is not None))
    for group in groups.values():
        group.points.sort(key=lambda point: (point.created_at, str(point.id), point.variant))
    return EvaluationTrends(generated_at=now, window_days=days, project_id=project_id,
        limited=len(runs) > RUN_LIMIT, run_limit=RUN_LIMIT, series=list(groups.values()))
