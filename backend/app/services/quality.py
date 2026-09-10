"""Durable evaluation jobs and explicit regression checks. Never edits Project."""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from statistics import mean

from fastapi import HTTPException
from sqlalchemy import or_, select

from ..db import SessionLocal
from ..evaluation_schemas import EvaluationSuite, QualityLimits, StartEvaluation, SaveEvaluation, EvaluationConfig
from ..models import ApiKey, EvaluationRun, EvaluationSchedule, EvaluationSuiteRecord, Project, QueryLog, SuspendedAccount
from . import embedding_usage

logger = logging.getLogger(__name__)
ACTIVE = ("preparing", "running")


def now():
    return datetime.now(timezone.utc)


def allowed(db, project, key_id=None):
    if project is None or project.suspended or db.get(SuspendedAccount, project.owner_id):
        raise HTTPException(403, "Project or account is unavailable for evaluation.")
    if key_id:
        key = db.get(ApiKey, key_id)
        if key is None or key.project_id != project.id or key.revoked_at is not None:
            raise HTTPException(403, "The API key that queued this run is no longer active.")


def validate_reference(db, project_id, run_id, suite):
    if run_id is None:
        return None
    ref = db.scalar(select(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.project_id == project_id))
    if ref is None or ref.status != "completed":
        raise HTTPException(422, "Choose a completed reference run from this project.")
    if ref.suite != suite:
        raise HTTPException(422, "The reference must use the same questions and model configurations.")
    return ref


def schedule_out(row):
    return {"revision": row.revision if row else 0, "enabled": row.enabled if row else False,
        "interval_hours": row.interval_hours if row else 24, "reference_run_id": str(row.reference_run_id) if row and row.reference_run_id else None,
        "quality_limits": row.quality_limits if row else QualityLimits().model_dump(),
        "next_run_at": row.next_run_at if row and row.enabled else None, "last_run_at": row.last_run_at if row else None,
        "last_error": row.last_error if row else None}


def save_schedule(db, project, body):
    from .evaluations import check_credentials
    db.execute(select(Project.id).where(Project.id == project.id).with_for_update()).one()
    row = db.get(EvaluationSchedule, project.id, populate_existing=True)
    if (row.revision if row else 0) != body.revision:
        raise HTTPException(409, "Schedule changed in another session. Reload it before saving.")
    # Turning off an existing job must remain possible after its set or reference changes.
    if not body.enabled:
        if row:
            row.enabled, row.last_error = False, None
            row.revision += 1
        db.commit()
        return schedule_out(row)
    saved = db.get(EvaluationSuiteRecord, project.id)
    if saved is None or not saved.suite.get("cases"):
        raise HTTPException(422, "Save a test set with questions first.")
    validate_reference(db, project.id, body.reference_run_id, saved.suite)
    if body.enabled:
        allowed(db, project)
        check_credentials(db, project, EvaluationSuite.model_validate(saved.suite))
    if row is None:
        row = EvaluationSchedule(project_id=project.id, revision=0)
        db.add(row)
    row.enabled, row.interval_hours = body.enabled, body.interval_hours
    row.suite = saved.suite
    row.reference_run_id, row.quality_limits = body.reference_run_id, body.quality_limits.model_dump()
    row.next_run_at, row.last_error = now() + timedelta(hours=body.interval_hours), None
    row.revision += 1
    db.commit()
    return schedule_out(row)


def add_query(db, project, body):
    from .evaluations import save_suite
    query = db.scalar(select(QueryLog).where(QueryLog.id == body.query_id, QueryLog.project_id == project.id))
    if query is None:
        raise HTTPException(404, "Query not found")
    db.execute(select(Project.id).where(Project.id == project.id).with_for_update()).one()
    saved = db.get(EvaluationSuiteRecord, project.id, populate_existing=True)
    if (saved.revision if saved else 0) != body.revision:
        raise HTTPException(409, "Test set changed. Reload it before adding the question.")
    if saved:
        suite = EvaluationSuite.model_validate(saved.suite)
    else:
        values = {name: getattr(project, name) for name in EvaluationConfig.model_fields if hasattr(project, name)}
        suite = EvaluationSuite(variants=[EvaluationConfig(**values)])
    case_id = f"query-{query.id}"
    if any(c.id == case_id for c in suite.cases):
        raise HTTPException(409, "This query is already in the test set.")
    if len(suite.cases) >= 20:
        raise HTTPException(422, "This test set already has 20 questions.")
    # Validate the full question; never silently truncate it or invent an answer.
    from ..evaluation_schemas import EvaluationCase
    if len(query.question) > 4000:
        raise HTTPException(422, "This question exceeds the evaluator's 4,000-character limit. Add a shorter question in the evaluator.")
    suite.cases.append(EvaluationCase(id=case_id, question=query.question, expected=body.expected, source=body.source, match=body.match))
    return save_suite(db, project, SaveEvaluation(revision=body.revision, suite=suite))


def metrics(run):
    result = []
    for variant in range(len(run.suite["variants"])):
        rows = [r for r in run.results if r["variant"] == variant]
        checked = [r for r in rows if r["status"] in ("passed", "failed")]
        latency = [r.get("response", {}).get("latency_ms") for r in rows]
        costs = [r.get("cost_usd") for r in rows]
        result.append({"pass_percent": 100 * sum(r["status"] == "passed" for r in checked) / len(checked) if checked else None,
            "latency_ms": mean(latency) if latency and all(v is not None for v in latency) else None,
            "cost_usd": mean(costs) if costs and all(v is not None for v in costs) else None})
    return result


def assess(db, run):
    current = metrics(run)
    ref = db.get(EvaluationRun, run.reference_run_id) if run.reference_run_id else None
    report = {"state": "no_reference", "reference_run_id": str(run.reference_run_id) if run.reference_run_id else None, "metrics": current, "warnings": []}
    if ref is None or ref.project_id != run.project_id or ref.status != "completed":
        return report
    if ref.suite != run.suite:
        report["state"] = "incompatible_reference"
        return report
    baseline = metrics(ref)
    limits = QualityLimits.model_validate(run.quality_limits or {}).model_dump()
    report.update(state="passed", baseline=baseline)
    for variant, (a, b) in enumerate(zip(baseline, current)):
        for metric, threshold in (("pass_percent", "quality_drop_pp"), ("latency_ms", "latency_increase_percent"), ("cost_usd", "cost_increase_percent")):
            if a[metric] is None or b[metric] is None:
                continue
            delta = a[metric] - b[metric] if metric == "pass_percent" else (100 * (b[metric] - a[metric]) / a[metric] if a[metric] > 0 else None)
            if delta is not None and delta > limits[threshold]:
                report["warnings"].append({"variant": variant, "metric": metric, "reference": a[metric], "current": b[metric], "change": delta, "limit": limits[threshold]})
    if report["warnings"]:
        report["state"] = "regressed"
    return report


def finish_one(db):
    row = db.scalar(select(EvaluationRun).where(EvaluationRun.status == "completed", EvaluationRun.quality_report.is_(None))
                    .order_by(EvaluationRun.created_at).with_for_update(skip_locked=True).limit(1))
    if row is None:
        db.rollback(); return False
    row.quality_report = assess(db, row)
    db.commit()
    return True


def queue_due(db):
    from .evaluations import create_run
    instant = now()
    # Project is always the first lock, matching suite/schedule edits and creates.
    project = db.scalar(select(Project).join(EvaluationSchedule).where(EvaluationSchedule.enabled.is_(True), EvaluationSchedule.next_run_at <= instant)
                        .order_by(EvaluationSchedule.next_run_at).with_for_update(of=Project, skip_locked=True).limit(1))
    if project is None:
        db.rollback(); return False
    row = db.get(EvaluationSchedule, project.id, populate_existing=True)
    if row.next_run_at.replace(tzinfo=timezone.utc) > instant or not row.enabled:
        db.rollback(); return False
    row.next_run_at = instant + timedelta(hours=row.interval_hours)
    try:
        allowed(db, project)
        if db.scalar(select(EvaluationRun.id).where(EvaluationRun.project_id == project.id, EvaluationRun.status.in_(ACTIVE)).limit(1)):
            row.last_error = "Previous run is still active; skipped this scheduled slot."
        else:
            with db.begin_nested():
                create_run(db, project, StartEvaluation(id=uuid.uuid4(), suite=EvaluationSuite.model_validate(row.suite), background=True,
                                      reference_run_id=row.reference_run_id), commit=False, quality_limits=row.quality_limits)
            row.last_run_at, row.last_error = instant, None
    except Exception as exc:
        row.last_error = str(exc.detail) if isinstance(exc, HTTPException) else "Could not queue evaluation. Check the saved set, provider keys and run history limit."
    db.commit()
    return True


def run_one(db):
    from .evaluations import advance
    instant = now()
    row = db.scalar(select(EvaluationRun).where(EvaluationRun.execution == "background", EvaluationRun.status.in_(ACTIVE),
        or_(EvaluationRun.lease_until.is_(None), EvaluationRun.lease_until < instant)).order_by(EvaluationRun.updated_at).limit(1))
    if row is None:
        db.rollback(); return False
    run_id, project_id, key_id = row.id, row.project_id, row.requested_by_key_id
    project = db.get(Project, project_id)
    try:
        allowed(db, project, key_id)
        with embedding_usage.scope():
            advance(db, project, run_id, key_id)
    except HTTPException as exc:
        db.rollback()
        if exc.status_code != 409:
            row = db.get(EvaluationRun, run_id)
            if row and row.status in ACTIVE:
                row.status, row.error = "failed", str(exc.detail)
                db.commit()
    return True


def quality_loop(stop):
    while not stop.is_set():
        did_work = False
        for task in (queue_due, run_one, finish_one):
            if stop.is_set(): break
            try:
                with SessionLocal() as db:
                    did_work = task(db) or did_work
            except Exception:
                logger.warning("Evaluation worker step failed; it will retry", exc_info=True)
                stop.wait(5)
        stop.wait(.25 if did_work else 2)
