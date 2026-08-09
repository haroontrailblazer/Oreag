"""Account-scoped usage aggregation for the dashboard Usage page.

Read-only rollups over ``usage_events`` and ``query_logs`` for ONE owner,
built from a small fixed number of aggregate queries (seven, all served by the
``usage_events(owner_id, created_at)`` and ``query_logs(project_id,
created_at)`` indexes) - never a per-row Python loop.

TENANCY IS THE CONTRACT. Every query filters on the authenticated owner.
``usage_events`` carries ``owner_id`` directly. ``query_logs`` does NOT - it
only has ``project_id`` - so its aggregate JOINs through ``projects`` and
filters on ``projects.owner_id``. Filtering query_logs by project id alone
would let any signed-in account read another tenant's cache stats by guessing
a project UUID.

NULL IS NOT ZERO. Token and cost columns are NULL when nothing was measured -
a provider that reports no usage, an endpoint that never calls an LLM. SQL
``SUM()`` already returns NULL over all-NULL input and this module preserves
that all the way to the response; COALESCE would forge a measurement out of
thin air, so it is reserved for request COUNTs, which genuinely are 0 when
empty. What was NOT measured is reported explicitly in ``caveats`` instead of
being hidden: the rows with no token counts, the models that produced them,
and the standing fact that ingestion-time embedding, image captioning and
audio transcription bypass the LLM factory and are not metered at all - for a
document-heavy project that is plausibly the largest real cost.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models import ApiKey, Project, QueryLog, UsageEvent
from ..schemas import (
    UsageByApiKey,
    UsageByModel,
    UsageByProject,
    UsageCacheSplit,
    UsageCaveats,
    UsageDaily,
    UsageReport,
    UsageTotals,
)

MAX_WINDOW_DAYS = 365


def _f(value) -> float | None:
    """NULL-preserving float (SUM of a Numeric column arrives as Decimal)."""
    return None if value is None else float(value)


def _i(value) -> int | None:
    return None if value is None else int(value)


def _day_bucket(db: Session):
    """``created_at`` as a 'YYYY-MM-DD' UTC date string, per dialect.

    Postgres in production; the SQLite branch exists so the test suite can run
    the real queries against a real database instead of a stub.
    """
    if db.get_bind().dialect.name == "sqlite":
        return func.strftime("%Y-%m-%d", UsageEvent.created_at)
    return func.to_char(func.timezone("UTC", UsageEvent.created_at), "YYYY-MM-DD")


def _estimate_saved_cost(model_rows, totals_row) -> float | None:
    """Estimate the dollars the answer cache avoided spending.

    There is no ``saved_cost_usd`` column - cost is priced per request at
    write time, and a cache hit spends nothing - so this derives a rate from
    what WAS measured in the same window: per model, dollars per token =
    SUM(cost) / SUM(tokens), applied to that model's saved tokens. Saved
    tokens that cannot be priced per model (e.g. rows with no model) fall back
    to the account-wide blended rate. Returns None when savings were never
    measured, or were measured but nothing in the window carries a price to
    derive a rate from - an estimate invented from nothing would be worse than
    admitting we cannot say.
    """
    if totals_row.saved_prompt is None and totals_row.saved_completion is None:
        return None
    total_saved = (totals_row.saved_prompt or 0) + (totals_row.saved_completion or 0)
    if total_saved == 0:
        return 0.0

    estimated = 0.0
    covered = 0
    for row in model_rows:
        saved = (row.saved_prompt or 0) + (row.saved_completion or 0)
        spent = (row.prompt or 0) + (row.completion or 0)
        if saved and spent and row.cost is not None:
            estimated += float(row.cost) / spent * saved
            covered += saved

    remainder = total_saved - covered
    if remainder > 0:
        spent_all = (totals_row.prompt or 0) + (totals_row.completion or 0)
        if spent_all and totals_row.cost is not None:
            estimated += float(totals_row.cost) / spent_all * remainder
            covered = total_saved

    if covered == 0:
        return None
    return round(estimated, 6)


def build_report(db: Session, owner_id: uuid.UUID, *, days: int) -> UsageReport:
    """The full usage report for one account over the last ``days`` days."""
    if not 1 <= days <= MAX_WINDOW_DAYS:
        # The route already validates; this guards direct callers.
        raise ValueError(f"days must be between 1 and {MAX_WINDOW_DAYS}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    in_window = (UsageEvent.owner_id == owner_id, UsageEvent.created_at >= cutoff)

    # -- totals --------------------------------------------------------------
    totals_row = db.execute(
        select(
            func.count(UsageEvent.id).label("requests"),
            func.sum(UsageEvent.prompt_tokens).label("prompt"),
            func.sum(UsageEvent.completion_tokens).label("completion"),
            func.sum(UsageEvent.cost_usd).label("cost"),
            func.sum(UsageEvent.saved_prompt_tokens).label("saved_prompt"),
            func.sum(UsageEvent.saved_completion_tokens).label("saved_completion"),
        ).where(*in_window)
    ).one()

    # -- by model (also feeds the saved-cost estimate) -----------------------
    model_rows = db.execute(
        select(
            UsageEvent.model.label("model"),
            func.count(UsageEvent.id).label("requests"),
            func.sum(UsageEvent.prompt_tokens).label("prompt"),
            func.sum(UsageEvent.completion_tokens).label("completion"),
            func.sum(UsageEvent.cost_usd).label("cost"),
            func.sum(UsageEvent.saved_prompt_tokens).label("saved_prompt"),
            func.sum(UsageEvent.saved_completion_tokens).label("saved_completion"),
        )
        .where(*in_window, UsageEvent.model.is_not(None))
        .group_by(UsageEvent.model)
        .order_by(func.count(UsageEvent.id).desc(), UsageEvent.model)
    ).all()

    # -- by API key ----------------------------------------------------------
    # Outer join: usage_events.api_key_id has no FK on purpose (a usage row
    # outlives its key), so a deleted key still aggregates - shown revoked,
    # with an "unknown" prefix. Rows written without a key are excluded: they
    # belong to no key, and the account totals still count them.
    key_rows = db.execute(
        select(
            UsageEvent.api_key_id.label("api_key_id"),
            ApiKey.key_prefix.label("key_prefix"),
            ApiKey.revoked_at.label("revoked_at"),
            ApiKey.id.label("key_row_id"),
            func.count(UsageEvent.id).label("requests"),
            func.sum(UsageEvent.prompt_tokens).label("prompt"),
            func.sum(UsageEvent.completion_tokens).label("completion"),
            func.sum(UsageEvent.cost_usd).label("cost"),
        )
        .outerjoin(ApiKey, ApiKey.id == UsageEvent.api_key_id)
        .where(*in_window, UsageEvent.api_key_id.is_not(None))
        .group_by(
            UsageEvent.api_key_id, ApiKey.key_prefix, ApiKey.revoked_at, ApiKey.id
        )
        .order_by(func.count(UsageEvent.id).desc())
    ).all()

    # -- by project: spend side (usage_events, owner-filtered directly) ------
    project_event_rows = db.execute(
        select(
            UsageEvent.project_id.label("project_id"),
            func.count(UsageEvent.id).label("requests"),
            func.sum(UsageEvent.cost_usd).label("cost"),
            func.sum(UsageEvent.saved_prompt_tokens).label("saved_prompt"),
            func.sum(UsageEvent.saved_completion_tokens).label("saved_completion"),
        )
        .where(*in_window)
        .group_by(UsageEvent.project_id)
    ).all()

    # -- by project: cache side (query_logs) ---------------------------------
    # SECURITY: query_logs has NO owner column. The JOIN through projects and
    # the filter on projects.owner_id IS the tenancy boundary - do not "relax"
    # it to a bare project_id filter.
    project_log_rows = db.execute(
        select(
            QueryLog.project_id.label("project_id"),
            func.sum(case((QueryLog.cache_layer == "l1", 1), else_=0)).label("l1"),
            func.sum(case((QueryLog.cache_layer == "l2", 1), else_=0)).label("l2"),
            func.sum(case((QueryLog.cache_layer.is_(None), 1), else_=0)).label("miss"),
            func.avg(QueryLog.retrieval_similarity).label("avg_retrieval"),
            func.avg(QueryLog.cache_similarity).label("avg_cache"),
        )
        .join(Project, Project.id == QueryLog.project_id)
        .where(Project.owner_id == owner_id, QueryLog.created_at >= cutoff)
        .group_by(QueryLog.project_id)
    ).all()

    # Names for exactly this owner's projects - also the merge allowlist, so a
    # usage row whose project has since been deleted (no FK) cannot resurface.
    project_names: dict[uuid.UUID, str] = dict(
        db.execute(
            select(Project.id, Project.name).where(Project.owner_id == owner_id)
        ).all()
    )

    # -- daily series --------------------------------------------------------
    day = _day_bucket(db).label("day")
    daily_rows = db.execute(
        select(
            day,
            func.count(UsageEvent.id).label("requests"),
            func.sum(UsageEvent.prompt_tokens).label("prompt"),
            func.sum(UsageEvent.completion_tokens).label("completion"),
            func.sum(UsageEvent.cost_usd).label("cost"),
            func.sum(UsageEvent.saved_prompt_tokens).label("saved_prompt"),
        )
        .where(*in_window)
        .group_by(day)
        .order_by(day)
    ).all()

    # -- caveats: what this report could NOT see -----------------------------
    # "Unmeasured" means a model ran and did not report its tokens - NOT a
    # request that legitimately spent nothing.
    #
    # A cache hit has NULL tokens because no model ran at all, so counting it
    # here would tell the user "N requests have no token data" about requests
    # whose zero cost is the entire point of the cache. That inflates the
    # caveat and undermines trust in the one disclosure the page exists to
    # make, so cache-served rows are excluded.
    unmeasured = db.execute(
        select(UsageEvent.model, func.count(UsageEvent.id))
        .where(
            *in_window,
            UsageEvent.prompt_tokens.is_(None),
            UsageEvent.cache_layer.is_(None),
        )
        .group_by(UsageEvent.model)
    ).all()

    # -- assemble ------------------------------------------------------------
    by_project: list[UsageByProject] = []
    log_by_id = {row.project_id: row for row in project_log_rows}
    ev_by_id = {row.project_id: row for row in project_event_rows}
    for project_id in project_names:
        ev = ev_by_id.get(project_id)
        log = log_by_id.get(project_id)
        if ev is None and log is None:
            continue  # no activity in the window
        l1 = int(log.l1) if log else 0
        l2 = int(log.l2) if log else 0
        miss = int(log.miss) if log else 0
        answered = l1 + l2 + miss
        by_project.append(
            UsageByProject(
                project_id=str(project_id),
                name=project_names[project_id],
                requests=int(ev.requests) if ev else 0,
                cost_usd=_f(ev.cost) if ev else None,
                cache=UsageCacheSplit(
                    l1=l1,
                    l2=l2,
                    miss=miss,
                    hit_rate=round((l1 + l2) / answered, 4) if answered else 0.0,
                ),
                avg_retrieval_similarity=_f(log.avg_retrieval) if log else None,
                avg_cache_similarity=_f(log.avg_cache) if log else None,
                saved_prompt_tokens=_i(ev.saved_prompt) if ev else None,
                saved_completion_tokens=_i(ev.saved_completion) if ev else None,
            )
        )
    by_project.sort(key=lambda p: (-p.requests, p.name))

    return UsageReport(
        window_days=days,
        totals=UsageTotals(
            requests=int(totals_row.requests),
            prompt_tokens=_i(totals_row.prompt),
            completion_tokens=_i(totals_row.completion),
            cost_usd=_f(totals_row.cost),
            saved_prompt_tokens=_i(totals_row.saved_prompt),
            saved_completion_tokens=_i(totals_row.saved_completion),
            saved_cost_usd=_estimate_saved_cost(model_rows, totals_row),
        ),
        by_model=[
            UsageByModel(
                model=row.model,
                requests=int(row.requests),
                prompt_tokens=_i(row.prompt),
                completion_tokens=_i(row.completion),
                cost_usd=_f(row.cost),
            )
            for row in model_rows
        ],
        by_api_key=[
            UsageByApiKey(
                api_key_id=str(row.api_key_id),
                key_prefix=row.key_prefix if row.key_row_id is not None else "unknown",
                revoked=row.key_row_id is None or row.revoked_at is not None,
                requests=int(row.requests),
                prompt_tokens=_i(row.prompt),
                completion_tokens=_i(row.completion),
                cost_usd=_f(row.cost),
            )
            for row in key_rows
        ],
        by_project=by_project,
        daily=[
            UsageDaily(
                date=row.day,
                requests=int(row.requests),
                prompt_tokens=_i(row.prompt),
                completion_tokens=_i(row.completion),
                cost_usd=_f(row.cost),
                saved_prompt_tokens=_i(row.saved_prompt),
            )
            for row in daily_rows
        ],
        caveats=UsageCaveats(
            unmeasured_requests=sum(count for _, count in unmeasured),
            unmeasured_models=sorted({m for m, _ in unmeasured if m}),
            ingestion_excluded=True,
        ),
    )
