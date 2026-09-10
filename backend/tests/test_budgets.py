import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.auth.jwt import get_current_user
from app.db import get_db
from app.models import Base, Project, UsageBudget, UsageBudgetAlert, UsageEvent
from app.routers import budgets
from app.services import budgets as service


@compiles(sa.BigInteger, "sqlite")
def bigint(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture()
def fixture(monkeypatch):
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[x.__table__ for x in (Project, UsageBudget, UsageBudgetAlert, UsageEvent)])
    now = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(service, "utcnow", lambda: now)
    with Session(engine, expire_on_commit=False) as db:
        owner = uuid.uuid4()
        mine, other = Project(owner_id=owner, name="Mine"), Project(owner_id=uuid.uuid4(), name="Other")
        db.add_all([mine, other]); db.commit()
        app = FastAPI(); app.include_router(budgets.router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: owner
        with TestClient(app) as client:
            yield client, db, mine, other, now


def event(db, project, now, cost=None, embedding=None, endpoint="query", **kw):
    db.add(UsageEvent(owner_id=project.owner_id, project_id=project.id, endpoint=endpoint,
        created_at=now-timedelta(seconds=1), cost_usd=cost, embedding_cost_usd=embedding, **kw)); db.commit()


def save(client, **kw):
    return client.put("/api/account/budgets", json={"amount_usd":"10.00", **kw})


def test_spend_includes_api_playground_ingestion_evaluations_but_not_savings(fixture):
    client, db, mine, other, now = fixture
    for endpoint in ("query", "playground_query_stream", "file_ingest", "evaluation_index", "evaluation_query"):
        event(db, mine, now, cost=1, embedding=.2, endpoint=endpoint, saved_cost_usd=100, saved_embedding_cost_usd=50)
    event(db, other, now, cost=100)
    data = save(client).json()
    assert data["budgets"][0]["spent_usd"] == 6
    assert data["budgets"][0]["requests"] == 5
    assert data["mode"] == "warn_only"
    assert mine.top_k == 5 and not mine.suspended


def test_unknown_and_zero_are_distinct(fixture):
    client, db, mine, _, now = fixture
    event(db, mine, now)
    data = save(client).json()
    assert data["budgets"][0]["spent_usd"] is None
    assert data["budgets"][0]["state"] == "unmeasured"
    assert data["alerts"] == []
    event(db, mine, now, cost=0)
    data = client.get("/api/account/budgets").json()
    assert data["budgets"][0]["spent_usd"] == 0
    assert data["budgets"][0]["unpriced_requests"] == 1


def test_partial_unpriced_cost_remains_visible(fixture):
    client, db, mine, _, now = fixture
    event(db, mine, now, embedding=2, prompt_tokens=100)
    data = save(client).json()["budgets"][0]
    assert data["spent_usd"] == 2 and data["unpriced_requests"] == 1


def test_thresholds_once_per_month_and_mark_read_persists(fixture):
    client, db, mine, _, now = fixture
    event(db, mine, now, cost=8)
    data = save(client).json()
    assert data["unread_count"] == 1
    alert = data["alerts"][0]
    assert alert["threshold_percent"] == 80
    assert client.post(f'/api/account/budgets/alerts/{alert["id"]}/read').status_code == 204
    assert service.check_one(db, now+timedelta(seconds=61))
    assert client.get("/api/account/budgets/alerts").json()["unread_count"] == 0
    event(db, mine, now, cost=2)
    assert service.check_one(db, now+timedelta(seconds=122))
    data = client.get("/api/account/budgets").json()
    assert len(data["alerts"]) == 2 and data["unread_count"] == 1
    assert data["budgets"][0]["state"] == "exceeded"


def test_month_reset_and_rollover_catches_previous_month(fixture, monkeypatch):
    client, db, mine, _, now = fixture
    save(client)
    event(db, mine, now.replace(day=30, hour=23), cost=10)
    october = datetime(2026, 10, 1, 0, 1, tzinfo=timezone.utc)
    assert service.check_one(db, october)
    monkeypatch.setattr(service, "utcnow", lambda: october)
    data = client.get("/api/account/budgets").json()
    assert data["budgets"][0]["spent_usd"] == 0
    assert {a["period_start"] for a in data["alerts"]} == {"2026-09-01"}
    event(db, mine, october, cost=10)
    assert service.check_one(db, october+timedelta(seconds=61))
    assert len(client.get("/api/account/budgets").json()["alerts"]) == 4


def test_project_scope_and_owner_isolation(fixture):
    client, db, mine, other, now = fixture
    assert save(client, project_id=str(other.id)).status_code == 404
    second = Project(owner_id=mine.owner_id, name="Second"); db.add(second); db.commit()
    event(db, mine, now, cost=2); event(db, second, now, cost=3); event(db, other, now, cost=99)
    save(client); data = save(client, project_id=str(mine.id)).json()
    assert sorted(b["spent_usd"] for b in data["budgets"]) == [2, 5]
    stranger = UsageBudget(owner_id=other.owner_id, scope_key="account", amount_usd=1, enabled=True, warning_percent=80, revision=1)
    db.add(stranger); db.flush(); service.evaluate(db, stranger, now); db.commit()
    hidden = db.scalar(sa.select(UsageBudgetAlert).where(UsageBudgetAlert.budget_id==stranger.id))
    assert client.delete(f"/api/account/budgets/{stranger.id}").status_code == 404
    assert client.post(f"/api/account/budgets/alerts/{hidden.id}/read").status_code == 404
    assert client.get("/api/account/budgets/alerts").json()["alerts"] == []
    assert client.post("/api/account/budgets/alerts/read-all").status_code == 204
    db.refresh(hidden)
    assert hidden.read_at is None


def test_revision_pause_resume_and_delete(fixture):
    client, db, mine, _, now = fixture
    event(db, mine, now, cost=20)
    data = save(client, enabled=False).json()
    assert data["alerts"] == [] and data["budgets"][0]["state"] == "paused"
    assert not service.check_one(db, now+timedelta(minutes=1))
    assert save(client).status_code == 409
    data = save(client, revision=1).json()
    assert len(data["alerts"]) == 2
    original = data["alerts"][0]["amount_usd"]
    data = save(client, revision=2, amount_usd="50").json()
    assert data["alerts"][0]["amount_usd"] == original
    assert client.delete(f'/api/account/budgets/{data["budgets"][0]["id"]}').status_code == 204
    assert client.get("/api/account/budgets").json()["budgets"] == []
    assert db.scalar(sa.select(sa.func.count()).select_from(UsageEvent)) == 1


@pytest.mark.parametrize("patch", [{"amount_usd":"0"},{"amount_usd":"-1"},{"amount_usd":"NaN"},{"amount_usd":"Infinity"},{"amount_usd":"1.001"},{"amount_usd":"1000001"},{"warning_percent":0},{"warning_percent":100},{"mode":"hard_stop"}])
def test_invalid_budgets_rejected(fixture, patch):
    assert save(fixture[0], **patch).status_code == 422


def test_worker_claim_uses_skip_locked():
    from sqlalchemy.dialects import postgresql
    class EmptyDB:
        def scalar(self, stmt):
            assert "FOR UPDATE SKIP LOCKED" in str(stmt.compile(dialect=postgresql.dialect()))
            return None
        def rollback(self):
            pass
    assert not service.check_one(EmptyDB())


def test_mark_all_read_includes_alerts_older_than_the_visible_page(fixture):
    client, db, mine, _, now = fixture
    data = save(client).json()
    budget_id = uuid.UUID(data["budgets"][0]["id"])
    for threshold in range(1, 61):
        db.add(UsageBudgetAlert(budget_id=budget_id, period_start=now.date().replace(day=1), threshold_percent=threshold, amount_usd=10, spent_usd=10))
    db.commit()
    data = client.get("/api/account/budgets/alerts").json()
    assert len(data["alerts"]) == 50 and data["unread_count"] == 60
    assert client.post("/api/account/budgets/alerts/read-all").status_code == 204
    assert client.get("/api/account/budgets/alerts").json()["unread_count"] == 0
