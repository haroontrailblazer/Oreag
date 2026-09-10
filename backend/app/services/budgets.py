"""Warning-only budgets over existing metering. No query/provider-path hooks.

The worker locks one due budget at a time, so multiple processes can scan safely.
Alerts retain the limit/spend that triggered them, once per threshold and UTC month.
"""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from ..config import settings
from ..db import SessionLocal
from ..models import Project, UsageBudget, UsageBudgetAlert, UsageEvent

logger = logging.getLogger(__name__)
CHECK_SECONDS = 60


def utcnow():
    return datetime.now(timezone.utc)


def month_start(value):
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)


def next_month(value):
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def spend(db, budget, start, end):
    filters = [UsageEvent.owner_id == budget.owner_id, UsageEvent.created_at >= start, UsageEvent.created_at < end]
    if budget.project_id is not None:
        filters.append(UsageEvent.project_id == budget.project_id)
    unpriced = or_(
        (UsageEvent.cost_usd.is_(None) & UsageEvent.embedding_cost_usd.is_(None)),
        (UsageEvent.cost_usd.is_(None) & ((UsageEvent.prompt_tokens > 0) | (UsageEvent.completion_tokens > 0))),
        (UsageEvent.embedding_cost_usd.is_(None) & (UsageEvent.embedding_tokens > 0)),
    )
    row = db.execute(select(func.count(), func.sum(UsageEvent.cost_usd), func.sum(UsageEvent.embedding_cost_usd),
                            func.sum(case((unpriced, 1), else_=0))).where(*filters)).one()
    # Empty is zero requests, not evidence that an unmeasured request was free.
    measured = [Decimal(value) for value in row[1:3] if value is not None]
    total = sum(measured, Decimal(0)) if measured else (Decimal(0) if row[0] == 0 else None)
    return total, row[0], row[3] or 0


def evaluate(db, budget, now):
    if not budget.enabled:
        return
    current = month_start(now)
    # Catch crossings at month rollover or after downtime, within retained data.
    previous = month_start(budget.last_checked_at) if budget.last_checked_at else current
    period = max(previous, month_start(now - timedelta(days=settings.log_retention_days)))
    while period <= current:
        total, _, _ = spend(db, budget, period, min(next_month(period), now))
        if total is not None:
            for threshold in (budget.warning_percent, 100):
                if total * 100 < Decimal(budget.amount_usd) * threshold:
                    continue
                exists = db.scalar(select(UsageBudgetAlert.id).where(UsageBudgetAlert.budget_id == budget.id,
                    UsageBudgetAlert.period_start == period.date(), UsageBudgetAlert.threshold_percent == threshold))
                if exists is None:
                    db.add(UsageBudgetAlert(budget_id=budget.id, period_start=period.date(), threshold_percent=threshold,
                                           amount_usd=budget.amount_usd, spent_usd=total, created_at=now))
        period = next_month(period)
    budget.last_checked_at = now
    budget.next_check_at = now + timedelta(seconds=CHECK_SECONDS)


def save(db, owner_id, body):
    if body.project_id is not None and db.scalar(select(Project.id).where(Project.id == body.project_id, Project.owner_id == owner_id)) is None:
        raise HTTPException(404, "Project not found")
    scope = str(body.project_id) if body.project_id else "account"
    budget = db.scalar(select(UsageBudget).where(UsageBudget.owner_id == owner_id, UsageBudget.scope_key == scope).with_for_update())
    if (budget.revision if budget else 0) != body.revision:
        raise HTTPException(409, "This budget changed in another session. Reload before saving.")
    if budget is None:
        if db.scalar(select(func.count()).select_from(UsageBudget).where(UsageBudget.owner_id == owner_id)) >= 26:
            raise HTTPException(409, "You can save up to 26 budgets. Remove one before adding another.")
        budget = UsageBudget(owner_id=owner_id, project_id=body.project_id, scope_key=scope, revision=0)
        db.add(budget)
    budget.amount_usd, budget.warning_percent, budget.enabled = body.amount_usd, body.warning_percent, body.enabled
    budget.revision += 1
    # A changed configuration applies to the current month, not past months.
    now = utcnow()
    budget.last_checked_at = now
    budget.next_check_at = now
    try:
        db.flush()
        evaluate(db, budget, now)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This budget was saved by another session. Reload before saving.") from None
    return report(db, owner_id)


def report(db, owner_id):
    now = utcnow()
    start, end = month_start(now), next_month(month_start(now))
    rows = db.execute(select(UsageBudget, Project.name).outerjoin(Project, Project.id == UsageBudget.project_id)
                      .where(UsageBudget.owner_id == owner_id).order_by(UsageBudget.created_at, UsageBudget.id)).all()
    budgets = []
    for budget, name in rows:
        total, requests, unpriced = spend(db, budget, start, now)
        ratio = total * 100 / Decimal(budget.amount_usd) if total is not None else None
        state = "paused" if not budget.enabled else "unmeasured" if ratio is None else "exceeded" if ratio >= 100 else "warning" if ratio >= budget.warning_percent else "on_track"
        budgets.append(dict(id=budget.id, project_id=budget.project_id, project_name=name, amount_usd=budget.amount_usd,
            warning_percent=budget.warning_percent, enabled=budget.enabled, revision=budget.revision, spent_usd=total,
            requests=requests, unpriced_requests=unpriced, percent_used=ratio, state=state, last_checked_at=budget.last_checked_at))
    return dict(period_start=start.date(), period_end=end.date(), budgets=budgets, **alerts(db, owner_id))


def alerts(db, owner_id):
    base = select(UsageBudgetAlert, Project.name).join(UsageBudget, UsageBudget.id == UsageBudgetAlert.budget_id).outerjoin(Project, Project.id == UsageBudget.project_id).where(UsageBudget.owner_id == owner_id)
    rows = db.execute(base.order_by(UsageBudgetAlert.created_at.desc(), UsageBudgetAlert.threshold_percent.desc()).limit(50)).all()
    unread = db.scalar(select(func.count()).select_from(UsageBudgetAlert).join(UsageBudget).where(UsageBudget.owner_id == owner_id, UsageBudgetAlert.read_at.is_(None)))
    return {"alerts": [dict(id=a.id, budget_id=a.budget_id, project_name=name, period_start=a.period_start,
        threshold_percent=a.threshold_percent, amount_usd=a.amount_usd, spent_usd=a.spent_usd, created_at=a.created_at, read_at=a.read_at) for a, name in rows], "unread_count": unread}


def mark_read(db, owner_id, alert_id):
    alert = db.scalar(select(UsageBudgetAlert).join(UsageBudget).where(UsageBudget.owner_id == owner_id, UsageBudgetAlert.id == alert_id))
    if alert is None:
        raise HTTPException(404, "Alert not found")
    alert.read_at = alert.read_at or utcnow()
    db.commit()


def mark_all_read(db, owner_id):
    owned = select(UsageBudget.id).where(UsageBudget.owner_id == owner_id)
    db.execute(update(UsageBudgetAlert).where(UsageBudgetAlert.budget_id.in_(owned), UsageBudgetAlert.read_at.is_(None))
               .values(read_at=utcnow()))
    db.commit()


def remove(db, owner_id, budget_id):
    budget = db.scalar(select(UsageBudget).where(UsageBudget.owner_id == owner_id, UsageBudget.id == budget_id).with_for_update())
    if budget is None:
        raise HTTPException(404, "Budget not found")
    db.execute(delete(UsageBudgetAlert).where(UsageBudgetAlert.budget_id == budget.id))
    db.delete(budget)
    db.commit()


def check_one(db, now=None):
    now = now or utcnow()
    budget = db.scalar(select(UsageBudget).where(UsageBudget.enabled.is_(True), UsageBudget.next_check_at <= now)
                       .order_by(UsageBudget.next_check_at).with_for_update(skip_locked=True).limit(1))
    if budget is None:
        db.rollback()
        return False
    evaluate(db, budget, now)
    db.commit()
    return True


def budget_loop(stop):
    # One transaction per budget; no provider calls or API request work here.
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                found = check_one(db)
            if not found:
                stop.wait(5)
        except Exception:
            logger.warning("Budget alert check failed; retrying in 60 seconds", exc_info=True)
            stop.wait(CHECK_SECONDS)
