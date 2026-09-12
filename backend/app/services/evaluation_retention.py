"""Archive terminal results, releasing snapshot/vector storage; protect references."""
import gzip
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, or_, select
from ..models import EvaluationRun, EvaluationSchedule, EvaluationVector

ACTIVE_LIMIT = 20


def make_room(db, project_id):
    # Caller owns the project lock, shared with reference/schedule changes.
    count = db.scalar(select(func.count()).select_from(EvaluationRun).where(EvaluationRun.project_id == project_id, EvaluationRun.archived_at.is_(None)))
    if count < ACTIVE_LIMIT:
        return
    from .evaluations import run_out
    # Finished automatic and gap checks retain comparisons in quality_report.
    # Keeping every link protected would fill history with an unarchivable chain.
    protected = set(db.scalars(select(EvaluationRun.reference_run_id).where(EvaluationRun.project_id == project_id, EvaluationRun.reference_run_id.is_not(None),
        or_(EvaluationRun.trigger_reason.is_(None), EvaluationRun.trigger_reason.not_in(["project_change", "gap_verification"]),
            EvaluationRun.status.in_(["preparing", "running"]), EvaluationRun.quality_report.is_(None)))))
    protected.update(db.scalars(select(EvaluationSchedule.reference_run_id).where(EvaluationSchedule.project_id == project_id, EvaluationSchedule.reference_run_id.is_not(None))))
    instant = datetime.now(timezone.utc)
    statement = select(EvaluationRun).where(EvaluationRun.project_id == project_id, EvaluationRun.archived_at.is_(None),
        EvaluationRun.status.in_(["completed", "failed", "cancelled"]),
        or_(EvaluationRun.lease_until.is_(None), EvaluationRun.lease_until < instant))
    if protected:
        statement = statement.where(EvaluationRun.id.not_in(protected))
    rows = db.scalars(statement.order_by(EvaluationRun.created_at, EvaluationRun.id).with_for_update().execution_options(populate_existing=True)).all()
    needed = count - ACTIVE_LIMIT + 1
    if len(rows) < needed:
        raise HTTPException(409, "All retained runs are active or protected references. Finish a run or remove an unused reference before starting another.")
    for row in rows[:needed]:
        row.archived_payload = gzip.compress(json.dumps(jsonable_encoder(run_out(row)), separators=(",", ":")).encode(), mtime=0)
        row.archived_at = instant
        row.corpus, row.results = [], []
        db.execute(delete(EvaluationVector).where(EvaluationVector.run_id == row.id))
    db.flush()
