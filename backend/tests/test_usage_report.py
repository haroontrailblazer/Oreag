"""The account usage report: GET /api/account/usage.

Two properties here are non-negotiable and each gets explicit coverage:

1. TENANCY. This is account-level observability, so one account must never
   see another's numbers. usage_events carries owner_id and is filtered on it
   directly; query_logs has NO owner column and is only reachable through a
   JOIN on projects.owner_id. The isolation tests seed two accounts and prove
   account B's report contains nothing of account A's - including the
   query_logs path, where filtering by project_id alone would leak stats to
   anyone who guessed a UUID.

2. NULL IS NOT ZERO. A provider that reports no usage yields NULL token
   columns; SUM over all-NULL must surface as null in the response, never 0.
   A forged 0 would tell the user "this cost nothing", which is exactly the
   lie the caveats block exists to prevent.

These tests run the REAL queries against a real (SQLite) database - stubs
would happily pass with an unfiltered query. The only accommodation is a
DDL-level one: BigInteger primary keys render as INTEGER so SQLite rowid
autoincrement works. Tables that need Postgres-only column types (vectors,
JSONB arrays) are simply not created; the report touches none of them.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.models import ApiKey, Base, Project, QueryLog, UsageEvent
from app.services import usage_report


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):
    """SQLite autoincrement only works on INTEGER PRIMARY KEY, not BIGINT.

    Registered for the sqlite dialect only, which production never uses.
    """
    return "INTEGER"


REPORT_TABLES = [
    Project.__table__,
    ApiKey.__table__,
    QueryLog.__table__,
    UsageEvent.__table__,
]


@pytest.fixture()
def db():
    # StaticPool: ONE shared connection, because TestClient runs the endpoint
    # on a worker thread and an in-memory SQLite database exists per
    # connection - the default pool would hand that thread a fresh empty DB.
    engine = sa.create_engine(
        "sqlite://",
        poolclass=sa.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine, tables=REPORT_TABLES)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


def _now():
    return datetime.now(timezone.utc)


def _project(db, owner_id, name="proj"):
    project = Project(owner_id=owner_id, name=name)
    db.add(project)
    db.commit()
    return project


def _event(db, project, **kw):
    kw.setdefault("endpoint", "query")
    kw.setdefault("created_at", _now())
    event = UsageEvent(owner_id=project.owner_id, project_id=project.id, **kw)
    db.add(event)
    db.commit()
    return event


def _log(db, project, **kw):
    kw.setdefault("question", "q")
    kw.setdefault("created_at", _now())
    log = QueryLog(project_id=project.id, **kw)
    db.add(log)
    db.commit()
    return log


def _key(db, project, prefix="oreag_sk_abc", revoked=False):
    key = ApiKey(
        project_id=project.id,
        key_prefix=prefix,
        key_hash=uuid.uuid4().hex,
        revoked_at=_now() if revoked else None,
    )
    db.add(key)
    db.commit()
    return key


# ── tenancy ─────────────────────────────────────────────────────────────────


class TestTenantIsolation:
    def test_account_b_sees_none_of_account_a_usage_events(self, db):
        owner_a, owner_b = uuid.uuid4(), uuid.uuid4()
        project_a = _project(db, owner_a, "a-proj")
        _event(db, project_a, prompt_tokens=100, completion_tokens=50,
               model="gpt-4o-mini", cost_usd=0.5)
        _event(db, project_a)

        project_b = _project(db, owner_b, "b-proj")
        _event(db, project_b, prompt_tokens=7, completion_tokens=3,
               model="claude-x", cost_usd=0.01)

        report = usage_report.build_report(db, owner_b, days=30)

        assert report.totals.requests == 1
        assert report.totals.prompt_tokens == 7
        assert report.totals.cost_usd == pytest.approx(0.01)
        assert [m.model for m in report.by_model] == ["claude-x"]
        assert str(project_a.id) not in [p.project_id for p in report.by_project]

    def test_query_logs_join_is_owner_filtered(self, db):
        """query_logs has no owner_id: A's cache stats must be unreachable
        from B's report even though B could guess A's project UUID - the only
        thing tying a log row to an account is the JOIN through projects."""
        owner_a, owner_b = uuid.uuid4(), uuid.uuid4()
        project_a = _project(db, owner_a, "a-proj")
        _event(db, project_a)  # A has activity, so A's project WOULD be listed
        for layer in ("l1", "l2", None, None):
            _log(db, project_a, cache_layer=layer, retrieval_similarity=0.9)

        project_b = _project(db, owner_b, "b-proj")
        _event(db, project_b)  # B's project appears, but with NO cache stats

        report_b = usage_report.build_report(db, owner_b, days=30)

        assert [p.project_id for p in report_b.by_project] == [str(project_b.id)]
        cache = report_b.by_project[0].cache
        assert (cache.l1, cache.l2, cache.miss) == (0, 0, 0)
        assert report_b.by_project[0].avg_retrieval_similarity is None

        # and A still sees its own: the join filters, it does not drop data
        report_a = usage_report.build_report(db, owner_a, days=30)
        cache_a = report_a.by_project[0].cache
        assert (cache_a.l1, cache_a.l2, cache_a.miss) == (1, 1, 2)

    def test_empty_account_next_to_a_busy_one(self, db):
        busy = uuid.uuid4()
        _event(db, _project(db, busy), prompt_tokens=10, model="m", cost_usd=1)

        report = usage_report.build_report(db, uuid.uuid4(), days=30)
        assert report.totals.requests == 0
        assert report.by_model == []
        assert report.by_project == []
        assert report.daily == []


# ── null vs zero ────────────────────────────────────────────────────────────


class TestNullIsNotZero:
    def test_sum_over_all_null_tokens_is_null_not_zero(self, db):
        """Three requests, none measured: 'we don't know' must not render as
        'it cost nothing'."""
        project = _project(db, uuid.uuid4())
        for _ in range(3):
            _event(db, project)  # tokens, cost, savings all NULL

        totals = usage_report.build_report(db, project.owner_id, days=30).totals
        assert totals.requests == 3  # counts ARE genuinely zero-or-more
        assert totals.prompt_tokens is None
        assert totals.completion_tokens is None
        assert totals.cost_usd is None
        assert totals.saved_prompt_tokens is None
        assert totals.saved_completion_tokens is None
        assert totals.saved_cost_usd is None

    def test_measured_zero_stays_zero(self, db):
        """The inverse guard: a real measured 0 must not be nulled away."""
        project = _project(db, uuid.uuid4())
        _event(db, project, prompt_tokens=0, completion_tokens=0, model="m")

        totals = usage_report.build_report(db, project.owner_id, days=30).totals
        assert totals.prompt_tokens == 0
        assert totals.completion_tokens == 0

    def test_mixed_rows_sum_only_what_was_measured(self, db):
        project = _project(db, uuid.uuid4())
        _event(db, project, prompt_tokens=10, completion_tokens=4,
               model="m", cost_usd=0.002)
        _event(db, project)  # unmeasured

        report = usage_report.build_report(db, project.owner_id, days=30)
        assert report.totals.requests == 2
        assert report.totals.prompt_tokens == 10
        assert report.totals.completion_tokens == 4
        assert report.totals.cost_usd == pytest.approx(0.002)


# ── caveats ─────────────────────────────────────────────────────────────────


class TestCaveats:
    def test_unmeasured_rows_and_their_models_are_reported(self, db):
        """Product requirement: providers that report no usage are SHOWN as
        unmeasured, never silently folded into the totals."""
        project = _project(db, uuid.uuid4())
        _event(db, project, model="sarvam-m")          # model known, no tokens
        _event(db, project, model="sarvam-m")
        _event(db, project, model="ollama-x")
        _event(db, project)                            # no model either
        _event(db, project, model="gpt-4o-mini", prompt_tokens=5,
               completion_tokens=2)                    # measured - not a caveat

        caveats = usage_report.build_report(db, project.owner_id, days=30).caveats
        assert caveats.unmeasured_requests == 4
        assert caveats.unmeasured_models == ["ollama-x", "sarvam-m"]
        assert caveats.ingestion_excluded is True

    def test_ingestion_excluded_is_true_even_when_empty(self, db):
        caveats = usage_report.build_report(db, uuid.uuid4(), days=30).caveats
        assert caveats.ingestion_excluded is True


# ── breakdowns ──────────────────────────────────────────────────────────────


class TestByModel:
    def test_groups_and_sums_per_model(self, db):
        project = _project(db, uuid.uuid4())
        _event(db, project, model="gpt", prompt_tokens=10, completion_tokens=2,
               cost_usd=0.1)
        _event(db, project, model="gpt", prompt_tokens=30, completion_tokens=8,
               cost_usd=0.3)
        _event(db, project, model="claude", prompt_tokens=1, completion_tokens=1,
               cost_usd=0.05)
        _event(db, project)  # NULL model: belongs to totals, not by_model

        report = usage_report.build_report(db, project.owner_id, days=30)
        assert [(m.model, m.requests) for m in report.by_model] == [
            ("gpt", 2), ("claude", 1),
        ]
        gpt = report.by_model[0]
        assert (gpt.prompt_tokens, gpt.completion_tokens) == (40, 10)
        assert gpt.cost_usd == pytest.approx(0.4)

    def test_model_with_no_measurements_keeps_nulls(self, db):
        project = _project(db, uuid.uuid4())
        _event(db, project, model="mystery")
        row = usage_report.build_report(db, project.owner_id, days=30).by_model[0]
        assert row.requests == 1
        assert row.prompt_tokens is None
        assert row.cost_usd is None


class TestByApiKey:
    def test_prefix_and_revoked_come_from_the_key_row(self, db):
        project = _project(db, uuid.uuid4())
        live = _key(db, project, prefix="oreag_sk_live")
        dead = _key(db, project, prefix="oreag_sk_dead", revoked=True)
        _event(db, project, api_key_id=live.id, prompt_tokens=5, cost_usd=0.1)
        _event(db, project, api_key_id=live.id)
        _event(db, project, api_key_id=dead.id)
        _event(db, project)  # keyless (e.g. never attributed): not a key row

        rows = usage_report.build_report(db, project.owner_id, days=30).by_api_key
        by_id = {r.api_key_id: r for r in rows}
        assert set(by_id) == {str(live.id), str(dead.id)}
        assert by_id[str(live.id)].key_prefix == "oreag_sk_live"
        assert by_id[str(live.id)].revoked is False
        assert by_id[str(live.id)].requests == 2
        assert by_id[str(live.id)].prompt_tokens == 5
        assert by_id[str(dead.id)].revoked is True

    def test_a_deleted_key_still_aggregates_as_revoked(self, db):
        """usage_events.api_key_id has no FK: the spend trail outlives the
        key. It must surface (the money was real) rather than vanish."""
        project = _project(db, uuid.uuid4())
        ghost_key_id = uuid.uuid4()  # no api_keys row exists
        _event(db, project, api_key_id=ghost_key_id, cost_usd=0.2)

        rows = usage_report.build_report(db, project.owner_id, days=30).by_api_key
        assert len(rows) == 1
        assert rows[0].api_key_id == str(ghost_key_id)
        assert rows[0].key_prefix == "unknown"
        assert rows[0].revoked is True


class TestByProject:
    def test_cache_split_hit_rate_and_similarities(self, db):
        project = _project(db, uuid.uuid4(), "docs")
        _event(db, project, cost_usd=0.5, saved_prompt_tokens=100,
               saved_completion_tokens=20, cache_layer="l1")
        _log(db, project, cache_layer="l1")
        _log(db, project, cache_layer="l2", cache_similarity=0.8)
        _log(db, project, cache_layer="l2", cache_similarity=0.9)
        _log(db, project, retrieval_similarity=0.6)  # miss
        _log(db, project, retrieval_similarity=0.7)  # miss

        rows = usage_report.build_report(db, project.owner_id, days=30).by_project
        assert len(rows) == 1
        row = rows[0]
        assert row.name == "docs"
        assert (row.cache.l1, row.cache.l2, row.cache.miss) == (1, 2, 2)
        assert row.cache.hit_rate == pytest.approx(0.6)
        assert row.avg_retrieval_similarity == pytest.approx(0.65)
        assert row.avg_cache_similarity == pytest.approx(0.85)
        assert row.saved_prompt_tokens == 100
        assert row.saved_completion_tokens == 20
        assert row.cost_usd == pytest.approx(0.5)

    def test_project_with_no_activity_is_omitted(self, db):
        owner = uuid.uuid4()
        _project(db, owner, "idle")
        active = _project(db, owner, "active")
        _event(db, active)

        rows = usage_report.build_report(db, owner, days=30).by_project
        assert [p.name for p in rows] == ["active"]

    def test_hit_rate_is_zero_when_no_queries(self, db):
        project = _project(db, uuid.uuid4())
        _event(db, project)
        row = usage_report.build_report(db, project.owner_id, days=30).by_project[0]
        assert row.cache.hit_rate == 0.0
        assert (row.cache.l1, row.cache.l2, row.cache.miss) == (0, 0, 0)


class TestDaily:
    def test_buckets_by_utc_day_sorted_ascending(self, db):
        project = _project(db, uuid.uuid4())
        day1 = _now() - timedelta(days=2)
        day2 = _now() - timedelta(days=1)
        _event(db, project, created_at=day1, prompt_tokens=10, cost_usd=0.1)
        _event(db, project, created_at=day1)
        _event(db, project, created_at=day2, prompt_tokens=5,
               saved_prompt_tokens=50)

        daily = usage_report.build_report(db, project.owner_id, days=30).daily
        assert [d.date for d in daily] == [
            day1.strftime("%Y-%m-%d"), day2.strftime("%Y-%m-%d"),
        ]
        assert daily[0].requests == 2
        assert daily[0].prompt_tokens == 10
        assert daily[0].cost_usd == pytest.approx(0.1)
        assert daily[0].saved_prompt_tokens is None  # never measured that day
        assert daily[1].saved_prompt_tokens == 50


class TestWindow:
    def test_rows_outside_the_window_are_excluded_everywhere(self, db):
        project = _project(db, uuid.uuid4())
        old = _now() - timedelta(days=10)
        _event(db, project, created_at=old, prompt_tokens=999, model="old-m",
               cost_usd=9.9)
        _log(db, project, created_at=old, cache_layer="l1")
        _event(db, project, prompt_tokens=1, model="new-m")
        _log(db, project)

        report = usage_report.build_report(db, project.owner_id, days=7)
        assert report.totals.requests == 1
        assert report.totals.prompt_tokens == 1
        assert report.totals.cost_usd is None
        assert [m.model for m in report.by_model] == ["new-m"]
        cache = report.by_project[0].cache
        assert (cache.l1, cache.miss) == (0, 1)

    def test_days_out_of_range_raises_for_direct_callers(self, db):
        with pytest.raises(ValueError):
            usage_report.build_report(db, uuid.uuid4(), days=0)
        with pytest.raises(ValueError):
            usage_report.build_report(db, uuid.uuid4(), days=366)


# ── saved-cost estimate ─────────────────────────────────────────────────────


class TestSavedCostEstimate:
    def test_estimated_from_the_same_models_measured_rate(self, db):
        """1000 tokens cost $0.01 on this model, the cache saved 500 more,
        so the saving is about $0.005."""
        project = _project(db, uuid.uuid4())
        _event(db, project, model="gpt", prompt_tokens=800,
               completion_tokens=200, cost_usd=0.01)
        _event(db, project, model="gpt", saved_prompt_tokens=400,
               saved_completion_tokens=100, cache_layer="l1")

        totals = usage_report.build_report(db, project.owner_id, days=30).totals
        assert totals.saved_cost_usd == pytest.approx(0.005)

    def test_null_when_savings_exist_but_nothing_was_ever_priced(self, db):
        """No rate to derive - an invented estimate would be worse than null."""
        project = _project(db, uuid.uuid4())
        _event(db, project, saved_prompt_tokens=100, cache_layer="l1")

        totals = usage_report.build_report(db, project.owner_id, days=30).totals
        assert totals.saved_prompt_tokens == 100
        assert totals.saved_cost_usd is None


# ── the HTTP surface ────────────────────────────────────────────────────────


class TestEndpoint:
    @pytest.fixture()
    def client(self, db):
        from fastapi.testclient import TestClient

        from app.auth.jwt import get_current_user
        from app.db import get_db
        from app.main import app

        owner_id = uuid.uuid4()
        app.dependency_overrides[get_current_user] = lambda: owner_id
        app.dependency_overrides[get_db] = lambda: db
        try:
            yield TestClient(app), owner_id
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)

    def test_empty_account_exact_contract_shape(self, client):
        """The exact JSON the frontend Usage page is being coded against."""
        http, _ = client
        res = http.get("/api/account/usage")
        assert res.status_code == 200
        assert res.json() == {
            "window_days": 30,
            "totals": {
                "requests": 0,
                "prompt_tokens": None,
                "completion_tokens": None,
                "cost_usd": None,
                "saved_prompt_tokens": None,
                "saved_completion_tokens": None,
                "saved_cost_usd": None,
            },
            "by_model": [],
            "by_api_key": [],
            "by_project": [],
            "daily": [],
            "caveats": {
                "unmeasured_requests": 0,
                "unmeasured_models": [],
                "ingestion_excluded": True,
            },
        }

    def test_days_is_validated_1_to_365(self, client):
        http, _ = client
        assert http.get("/api/account/usage?days=0").status_code == 422
        assert http.get("/api/account/usage?days=366").status_code == 422
        assert http.get("/api/account/usage?days=not-a-number").status_code == 422
        res = http.get("/api/account/usage?days=365")
        assert res.status_code == 200
        assert res.json()["window_days"] == 365

    def test_report_is_scoped_to_the_token_owner(self, client, db):
        """End to end: the owner comes from the auth dependency, never from
        anything the caller can put in the request."""
        http, owner_id = client
        mine = _project(db, owner_id, "mine")
        _event(db, mine, prompt_tokens=3, model="m")
        theirs = _project(db, uuid.uuid4(), "theirs")
        _event(db, theirs, prompt_tokens=1000, model="stolen", cost_usd=99.0)
        _log(db, theirs, cache_layer="l1")

        body = http.get("/api/account/usage").json()
        assert body["totals"]["requests"] == 1
        assert body["totals"]["prompt_tokens"] == 3
        assert body["totals"]["cost_usd"] is None
        assert [p["name"] for p in body["by_project"]] == ["mine"]
        assert [m["model"] for m in body["by_model"]] == ["m"]

    def test_requires_auth(self):
        from fastapi.testclient import TestClient

        from app.main import app

        assert TestClient(app).get("/api/account/usage").status_code == 401


def test_a_cache_hit_is_not_reported_as_unmeasured(db):
    """A cache hit has NULL tokens because no model ran - that is the cache
    WORKING, not a provider failing to report.

    Counting it under `unmeasured_requests` would tell the user "N requests
    have no token data" about the very requests whose zero cost is the point,
    which discredits the one disclosure this page exists to make.
    """
    import uuid as _uuid

    owner_id = _uuid.uuid4()
    project = _project(db, owner_id)
    # Served from cache: no model ran, so there is nothing to measure.
    _event(
        db,
        project,
        prompt_tokens=None,
        completion_tokens=None,
        cache_layer="l1",
        saved_prompt_tokens=900,
        saved_completion_tokens=40,
    )
    # A real model call that reported nothing - THIS is the unmeasured one.
    _event(
        db,
        project,
        prompt_tokens=None,
        completion_tokens=None,
        model="some-local-model",
        cache_layer=None,
    )

    report = usage_report.build_report(db, owner_id, days=30)
    assert report.caveats.unmeasured_requests == 1, (
        "the cache hit was wrongly counted as unmeasured"
    )
    assert report.caveats.unmeasured_models == ["some-local-model"]
