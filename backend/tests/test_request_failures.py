"""Real SQL filters, ownership, stable time cursors, and safe project attribution."""
import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.auth.jwt import get_current_user
from app.db import get_db
from app.models import Base, Project, RequestMetric
from app.routers.deps import get_owned_project
from app.routers.operations import router
from app.services import operations

URL = "/api/account/operations/failures"
NOW = datetime.now(timezone.utc) - timedelta(seconds=1)


@compiles(sa.BigInteger, "sqlite")
def bigint(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture()
def explorer():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[Project.__table__, RequestMetric.__table__])
    with Session(engine) as db:
        mine = Project(owner_id=uuid.uuid4(), name="Mine")
        other = Project(owner_id=uuid.uuid4(), name="PRIVATE_OTHER_PROJECT")
        db.add_all([mine, other]); db.commit()
        app = FastAPI(); app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: mine.owner_id
        with TestClient(app) as client:
            yield client, db, mine, other
    engine.dispose()


def metric(db, project, **values):
    row = RequestMetric(**{"owner_id": project.owner_id, "project_id": project.id,
        "endpoint": "/v1/projects/{project_id}/query", "status_code": 500, "outcome": "error",
        "latency_ms": 321.5, "created_at": NOW, **values})
    db.add(row); db.commit()
    return row


def page(client, **params):
    response = client.get(URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_scope_on_list_detail_and_filters(explorer):
    client, db, mine, other = explorer
    own = metric(db, mine)
    foreign = metric(db, other)
    inconsistent = metric(db, other, owner_id=mine.owner_id)
    metric(db, mine, owner_id=None)
    result = page(client)
    assert [item["id"] for item in result["items"]] == [str(own.id)]
    assert "PRIVATE" not in json.dumps(result)
    assert page(client, project_id=str(other.id))["items"] == []
    assert client.get(f"{URL}/{foreign.id}").status_code == 404
    assert client.get(f"{URL}/{inconsistent.id}").status_code == 404
    assert client.get(f"{URL}/{own.id}").status_code == 200


def test_includes_http_200_failures_but_never_successes(explorer):
    client, db, mine, _ = explorer
    metric(db, mine, outcome="success", status_code=200)
    metric(db, mine, outcome="future_unknown", status_code=200)
    records = [metric(db, mine, outcome=outcome, status_code=code) for outcome, code in
        [("error", 503), ("rejected", 429), ("stream_error", 200), ("disconnected", 200)]]
    assert {item["id"] for item in page(client)["items"]} == {str(row.id) for row in records}
    assert len(page(client, status_code=200)["items"]) == 2
    assert page(client, outcome="stream_error")["items"][0]["outcome"] == "stream_error"


def test_filters_apply_before_pagination_and_wildcards_are_literal(explorer):
    client, db, mine, _ = explorer
    metric(db, mine, outcome="rejected", status_code=422, endpoint="/v1/files/upload", latency_ms=4000)
    metric(db, mine, outcome="rejected", status_code=429, latency_ms=1)
    selected = metric(db, mine, outcome="rejected", status_code=429, endpoint="/v1/100%_LITERAL", latency_ms=4000)
    result = page(client, hours=168, outcome="rejected", status_code=429, project_id=str(mine.id), search="%_literal", min_latency_ms=3000, limit=1)
    assert [item["id"] for item in result["items"]] == [str(selected.id)]
    assert result["next_cursor"] is None


def test_retained_windows_unknown_project_and_bigint_ids(explorer):
    client, db, mine, _ = explorer
    row = metric(db, mine, id=9_007_199_254_740_993, project_id=None, first_token_ms=None, latency_ms=0)
    metric(db, mine, created_at=NOW - timedelta(days=3))
    metric(db, mine, created_at=NOW - timedelta(days=40))
    metric(db, mine, created_at=NOW + timedelta(days=1))
    result = page(client, hours=24)
    assert len(result["items"]) == 1 and result["window_hours"] == 24
    item = result["items"][0]
    assert item["id"] == str(row.id) and item["latency_ms"] == 0
    assert item["first_token_ms"] is None and item["project_name"] is None and item["project_id"] is None
    assert item["created_at"].endswith("Z")
    assert len(page(client, hours=168)["items"]) == 2
    assert page(client, project_id=str(mine.id))["items"] == []
    assert set(client.get(f"{URL}/{row.id}").json()) == {"id", "project_id", "project_name", "endpoint", "status_code", "outcome", "latency_ms", "first_token_ms", "created_at"}


def test_pagination_orders_by_time_then_id_and_preserves_snapshot(explorer):
    client, db, mine, _ = explorer
    early = metric(db, mine, created_at=NOW - timedelta(hours=2))
    recent = [metric(db, mine) for _ in range(4)]
    # A later insert ID can have an older timestamp (asynchronous metrics).
    middle = metric(db, mine, created_at=NOW - timedelta(hours=1))
    first = page(client, limit=2)
    assert [item["id"] for item in first["items"]] == [str(recent[3].id), str(recent[2].id)]
    metric(db, mine, created_at=datetime.now(timezone.utc))
    second = page(client, limit=2, before=first["next_cursor"])
    third = page(client, limit=2, before=second["next_cursor"])
    assert [item["id"] for item in second["items"] + third["items"]] == [str(recent[1].id), str(recent[0].id), str(middle.id), str(early.id)]
    assert third["next_cursor"] is None
    assert first["as_of"] == second["as_of"] == third["as_of"]


@pytest.mark.parametrize("params", [
    {"hours": 2}, {"hours": 0}, {"hours": 721}, {"limit": 0}, {"limit": 101},
    {"status_code": 99}, {"status_code": 600}, {"outcome": "success"}, {"outcome": "unknown"},
    {"project_id": "bad"}, {"min_latency_ms": -1}, {"min_latency_ms": 3_600_001},
    {"search": "x" * 201}, {"before": "not-a-cursor"}, {"before": ""}, {"before": "x" * 257},
])
def test_invalid_filters(explorer, params):
    assert explorer[0].get(URL, params=params).status_code == 422


@pytest.mark.parametrize("payload", [
    [NOW.isoformat(), "99999999999999999999999", NOW.isoformat()],
    [NOW.isoformat(), "-1", NOW.isoformat()],
    [NOW.isoformat(), 1, NOW.isoformat()],
    [NOW.replace(tzinfo=None).isoformat(), "1", NOW.isoformat()],
    [(NOW + timedelta(days=1)).isoformat(), "1", NOW.isoformat()],
    [NOW.isoformat(), "1", (NOW + timedelta(days=1)).isoformat()],
    None, [], [None, "1", None],
])
def test_invalid_cursor_values(explorer, payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    assert explorer[0].get(URL, params={"before": encoded}).status_code == 422


@pytest.mark.parametrize("ident", [0, -1, 9999999999999999999999])
def test_invalid_detail_id(explorer, ident):
    assert explorer[0].get(f"{URL}/{ident}").status_code == 404


def test_success_not_available_as_failure_detail(explorer):
    client, db, mine, _ = explorer
    row = metric(db, mine, outcome="success", status_code=200)
    assert client.get(f"{URL}/{row.id}").status_code == 404


def test_requires_authentication():
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as client:
        assert client.get(URL).status_code in (401, 403)
        assert client.get(f"{URL}/1").status_code in (401, 403)


def test_dashboard_project_attribution_only_after_ownership_check(explorer, monkeypatch):
    _, db, mine, other = explorer
    captured = []
    monkeypatch.setattr(operations, "enqueue", captured.append)
    app = FastAPI(); app.add_middleware(operations.RequestMetricsMiddleware)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: mine.owner_id
    @app.get("/api/projects/{project_id}/fixture")
    def route(request: Request, project: Project = Depends(get_owned_project)):
        from fastapi import HTTPException
        raise HTTPException(422, "PRIVATE_FAILURE_MESSAGE")
    with TestClient(app) as client:
        assert client.get(f"/api/projects/{mine.id}/fixture?secret=PRIVATE_QUERY_STRING").status_code == 422
        assert client.get(f"/api/projects/{other.id}/fixture").status_code == 404
    assert len(captured) == 1
    assert captured[0]["project_id"] == mine.id
    assert captured[0]["outcome"] == "rejected"
    assert captured[0]["endpoint"] == "/api/projects/{project_id}/fixture"
    assert "PRIVATE" not in str(captured)
