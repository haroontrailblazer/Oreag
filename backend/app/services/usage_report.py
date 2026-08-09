"""Account-scoped usage aggregation for the dashboard Usage page.

Read-only rollups over ``usage_events`` and ``query_logs`` for ONE owner, in
FOUR round trips: one grouped "cube" pass over ``usage_events`` that every
usage rollup is derived from, plus the API-key labels, the project cache stats
and the project names. It was nine, one per rollup - each individually fast
(the ``usage_events(owner_id, created_at)`` index serves them all) but each
paying a full network round trip, which against a pooled Postgres IS the cost:
measured from a laptop, the queries took single-digit milliseconds and the
report took five seconds.

Still aggregate SQL, never a per-row Python loop: the cube's cardinality is
bounded by days x models x keys x projects, not by request volume.

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


def _nsum(values) -> float | int | None:
    """SQL ``SUM`` semantics in Python: NULL over all-NULL input.

    The rollups below are derived from one grouped result set rather than one
    query each, so the NULL-is-not-zero invariant now has to be preserved HERE
    instead of by Postgres. All-None must stay None - a token count of 0 is a
    measurement and "never measured" is a different fact, and the whole
    caveats section depends on being able to tell them apart.
    """
    known = [v for v in values if v is not None]
    if not known:
        return None
    return sum(known)


class _Bucket:
    """One rollup line, accumulated from cube rows."""

    __slots__ = ("requests", "prompt", "completion", "cost", "saved_prompt",
                 "saved_completion", "saved_cost", "embedding_tokens",
                 "embedding_cost", "saved_embedding", "saved_embedding_cost")

    def __init__(self) -> None:
        self.requests = 0
        for field in self.__slots__[1:]:
            setattr(self, field, [])

    def add(self, row) -> None:
        self.requests += int(row.requests)
        self.prompt.append(row.prompt)
        self.completion.append(row.completion)
        self.cost.append(row.cost)
        self.saved_prompt.append(row.saved_prompt)
        self.saved_completion.append(row.saved_completion)
        self.saved_cost.append(row.saved_cost)
        self.embedding_tokens.append(row.embedding_tokens)
        self.embedding_cost.append(row.embedding_cost)
        self.saved_embedding.append(row.saved_embedding)
        self.saved_embedding_cost.append(row.saved_embedding_cost)

    def __getattr__(self, name):  # pragma: no cover - defensive
        raise AttributeError(name)


def _rollup(rows, key_fn):
    """Group cube rows by `key_fn`, skipping rows whose key is None."""
    out: dict = {}
    for row in rows:
        key = key_fn(row)
        if key is None:
            continue
        out.setdefault(key, _Bucket()).add(row)
    return out


def cube_query(in_window, day):
    """The single grouped pass over ``usage_events`` that every rollup derives
    from. Extracted so a test can COMPILE it against the Postgres dialect -
    see tests/test_usage_report.py::TestCubeCompilesForPostgres. The suite runs
    on SQLite, which accepts grouping SQL that Postgres rejects.
    """
    return (
        select(
            day,
            UsageEvent.model.label("model"),
            UsageEvent.embedding_model.label("embedding_model"),
            UsageEvent.api_key_id.label("api_key_id"),
            UsageEvent.project_id.label("project_id"),
            # Carried in the KEY so the caveat rollup can be derived too: a row
            # is "unmeasured" when a model ran and reported nothing, which is
            # not the same as a cache hit where no model ran at all.
            #
            # Bare IS NULL predicates, deliberately, NOT a CASE. A CASE renders
            # its 1/0 as bind parameters, and SQLAlchemy numbers those
            # independently in SELECT and in GROUP BY - so Postgres sees two
            # different expressions and rejects the query outright. SQLite
            # accepts it, which means the test suite would pass and production
            # would 500.
            UsageEvent.prompt_tokens.is_(None).label("unmeasured"),
            UsageEvent.cache_layer.is_(None).label("uncached"),
            func.count(UsageEvent.id).label("requests"),
            func.sum(UsageEvent.prompt_tokens).label("prompt"),
            func.sum(UsageEvent.completion_tokens).label("completion"),
            func.sum(UsageEvent.cost_usd).label("cost"),
            func.sum(UsageEvent.saved_prompt_tokens).label("saved_prompt"),
            func.sum(UsageEvent.saved_completion_tokens).label("saved_completion"),
            func.sum(UsageEvent.saved_cost_usd).label("saved_cost"),
            func.sum(UsageEvent.embedding_tokens).label("embedding_tokens"),
            func.sum(UsageEvent.embedding_cost_usd).label("embedding_cost"),
            func.sum(UsageEvent.saved_embedding_tokens).label("saved_embedding"),
            func.sum(UsageEvent.saved_embedding_cost_usd).label("saved_embedding_cost"),
        )
        .where(*in_window)
        .group_by(
            day,
            UsageEvent.model,
            UsageEvent.embedding_model,
            UsageEvent.api_key_id,
            UsageEvent.project_id,
            UsageEvent.prompt_tokens.is_(None),
            UsageEvent.cache_layer.is_(None),
        )
    )


def build_report(db: Session, owner_id: uuid.UUID, *, days: int) -> UsageReport:
    """The full usage report for one account over the last ``days`` days."""
    if not 1 <= days <= MAX_WINDOW_DAYS:
        # The route already validates; this guards direct callers.
        raise ValueError(f"days must be between 1 and {MAX_WINDOW_DAYS}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    in_window = (UsageEvent.owner_id == owner_id, UsageEvent.created_at >= cutoff)

    # -- ONE pass over usage_events ------------------------------------------
    #
    # This used to be six separate aggregate queries over the same table with
    # the same WHERE clause - totals, by model, by embedding model, by API key,
    # by project, daily, plus the unmeasured caveat. Each was individually fast
    # (the (owner_id, created_at) index serves them all) but each cost a full
    # network round trip, and against a pooled Postgres that round trip is the
    # entire cost: measured from a laptop, 8 trips took ~5s while the queries
    # themselves took single-digit milliseconds.
    #
    # Grouping on the full key tuple once produces a small cube every rollup
    # can be derived from. Cardinality is bounded by
    # days x models x keys x projects, not by request volume, so this stays an
    # aggregate query rather than becoming a per-row fetch as traffic grows.
    day = _day_bucket(db).label("day")
    cube = db.execute(cube_query(in_window, day)).all()

    totals_bucket = _Bucket()
    for row in cube:
        totals_bucket.add(row)

    model_buckets = _rollup(cube, lambda r: r.model)
    embedding_buckets = _rollup(cube, lambda r: r.embedding_model)
    key_buckets = _rollup(cube, lambda r: r.api_key_id)
    project_buckets = _rollup(cube, lambda r: r.project_id)
    day_buckets = _rollup(cube, lambda r: r.day)

    # Sorted the way each table is read: busiest first, name as tiebreak, so
    # the ordering the SQL used to supply is preserved exactly.
    def _by_requests(items):
        return sorted(items, key=lambda kv: (-kv[1].requests, str(kv[0])))

    # -- API key labels ------------------------------------------------------
    # usage_events.api_key_id has no FK on purpose (a usage row outlives its
    # key), so a deleted key still aggregates - shown revoked, with an
    # "unknown" prefix. Rows written without a key (the dashboard playground)
    # belong to no key and are excluded here; the account totals still count
    # them.
    # Looked up by the ids actually present, which reproduces the previous
    # OUTER JOIN exactly: an id with no surviving row simply has no entry.
    # ApiKey has no owner_id (it hangs off a project), and adding that join
    # would drop keys whose project was deleted - rows the account still
    # legitimately owns, because usage_events.owner_id already scoped them.
    key_ids = [k for k in key_buckets]
    key_meta = {
        row.id: row
        for row in db.execute(
            select(ApiKey.id, ApiKey.key_prefix, ApiKey.revoked_at).where(
                ApiKey.id.in_(key_ids)
            )
        ).all()
    } if key_ids else {}

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

    # `daily` and the unmeasured caveat come from the same cube - see the
    # comment above it. Two more round trips saved.
    #
    # "Unmeasured" means a model ran and did not report its tokens - NOT a
    # request that legitimately spent nothing. A cache hit has NULL tokens
    # because no model ran at all, so counting it here would report "N
    # requests have no token data" about requests whose zero cost is the
    # entire point of the cache.
    unmeasured = [
        (row.model, int(row.requests))
        for row in cube
        if row.unmeasured and row.uncached
    ]

    # -- assemble ------------------------------------------------------------
    by_project: list[UsageByProject] = []
    log_by_id = {row.project_id: row for row in project_log_rows}
    for project_id in project_names:
        ev = project_buckets.get(project_id)
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
                requests=ev.requests if ev else 0,
                cost_usd=_f(_nsum(ev.cost)) if ev else None,
                cache=UsageCacheSplit(
                    l1=l1,
                    l2=l2,
                    miss=miss,
                    hit_rate=round((l1 + l2) / answered, 4) if answered else 0.0,
                ),
                avg_retrieval_similarity=_f(log.avg_retrieval) if log else None,
                avg_cache_similarity=_f(log.avg_cache) if log else None,
                saved_prompt_tokens=_i(_nsum(ev.saved_prompt)) if ev else None,
                saved_completion_tokens=_i(_nsum(ev.saved_completion)) if ev else None,
            )
        )
    by_project.sort(key=lambda p: (-p.requests, p.name))

    return UsageReport(
        window_days=days,
        totals=UsageTotals(
            requests=totals_bucket.requests,
            prompt_tokens=_i(_nsum(totals_bucket.prompt)),
            completion_tokens=_i(_nsum(totals_bucket.completion)),
            cost_usd=_f(_nsum(totals_bucket.cost)),
            saved_prompt_tokens=_i(_nsum(totals_bucket.saved_prompt)),
            saved_completion_tokens=_i(_nsum(totals_bucket.saved_completion)),
            saved_cost_usd=_f(_nsum(totals_bucket.saved_cost)),
            embedding_tokens=_i(_nsum(totals_bucket.embedding_tokens)),
            embedding_cost_usd=_f(_nsum(totals_bucket.embedding_cost)),
            saved_embedding_tokens=_i(_nsum(totals_bucket.saved_embedding)),
            saved_embedding_cost_usd=_f(_nsum(totals_bucket.saved_embedding_cost)),
        ),
        # Chat and embedding models in ONE list, tagged by kind: "what did this
        # account spend, by model" is a single question, and splitting it into
        # two tables would make the reader add them up by hand.
        by_model=[
            UsageByModel(
                model=model,
                requests=b.requests,
                prompt_tokens=_i(_nsum(b.prompt)),
                completion_tokens=_i(_nsum(b.completion)),
                cost_usd=_f(_nsum(b.cost)),
                kind="llm",
            )
            for model, b in _by_requests(model_buckets.items())
        ] + [
            UsageByModel(
                model=model,
                requests=b.requests,
                prompt_tokens=_i(_nsum(b.embedding_tokens)),
                # An embedding has no completion side. 0 is the measurement,
                # not an absence.
                completion_tokens=(
                    0 if _nsum(b.embedding_tokens) is not None else None
                ),
                cost_usd=_f(_nsum(b.embedding_cost)),
                kind="embedding",
            )
            for model, b in _by_requests(embedding_buckets.items())
        ],
        by_api_key=[
            UsageByApiKey(
                api_key_id=str(key_id),
                key_prefix=(
                    key_meta[key_id].key_prefix if key_id in key_meta else "unknown"
                ),
                revoked=(
                    key_id not in key_meta
                    or key_meta[key_id].revoked_at is not None
                ),
                requests=b.requests,
                prompt_tokens=_i(_nsum(b.prompt)),
                completion_tokens=_i(_nsum(b.completion)),
                cost_usd=_f(_nsum(b.cost)),
            )
            for key_id, b in _by_requests(key_buckets.items())
        ],
        by_project=by_project,
        daily=[
            UsageDaily(
                date=date,
                requests=b.requests,
                prompt_tokens=_i(_nsum(b.prompt)),
                completion_tokens=_i(_nsum(b.completion)),
                cost_usd=_f(_nsum(b.cost)),
                saved_prompt_tokens=_i(_nsum(b.saved_prompt)),
                embedding_tokens=_i(_nsum(b.embedding_tokens)),
                embedding_cost_usd=_f(_nsum(b.embedding_cost)),
            )
            for date, b in sorted(day_buckets.items())
        ],
        caveats=UsageCaveats(
            unmeasured_requests=sum(count for _, count in unmeasured),
            unmeasured_models=sorted({m for m, _ in unmeasured if m}),
            vision_and_audio_excluded=True,
        ),
    )
