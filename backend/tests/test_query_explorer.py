"""Exercise the real read queries and HTTP validation against isolated SQLite."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.auth.jwt import get_current_user
from app.db import get_db
from app.models import ApiKey, Base, Project, QueryLog
from app.routers.query_explorer import router


@compiles(sa.BigInteger, "sqlite")
def _bigint(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture()
def explorer():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool,
                              connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[Project.__table__, ApiKey.__table__, QueryLog.__table__])
    with Session(engine) as db:
        owner = uuid.uuid4()
        mine = Project(owner_id=owner, name="Mine")
        other = Project(owner_id=uuid.uuid4(), name="Secret")
        db.add_all([mine, other])
        db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: owner
        with TestClient(app) as client:
            yield client, db, mine, other
    engine.dispose()


def log(db, project, **values):
    values.setdefault("question", "How does this work?")
    values.setdefault("created_at", datetime.now(timezone.utc))
    row = QueryLog(project_id=project.id, **values)
    db.add(row)
    db.commit()
    return row


URL = "/api/account/queries"


def test_owner_scope_on_list_filters_and_detail(explorer):
    client, db, mine, other = explorer
    own = log(db, mine)
    secret = log(db, other)
    assert [item["id"] for item in client.get(URL).json()["items"]] == [str(own.id)]
    assert client.get(URL, params={"project_id": str(other.id)}).json()["items"] == []
    assert client.get(f"{URL}/{secret.id}").status_code == 404
    assert client.get(f"{URL}/{own.id}").status_code == 200


def test_filters_and_nulls(explorer):
    client, db, mine, _ = explorer
    log(db, mine, question="Cached answer", cache_layer="l1", latency_ms=500)
    slow = log(db, mine, question="Slow semantic answer", cache_layer="l2", latency_ms=3000)
    fresh = log(db, mine, question="Fresh 100%_literal", retrieval_similarity=0.0)
    log(db, mine, created_at=datetime.now(timezone.utc) - timedelta(days=40))
    response = client.get(URL, params={"days": 7, "cache": "l2", "min_latency_ms": 3000, "search": "SEMANTIC"})
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [str(slow.id)]
    result = client.get(URL, params={"cache": "fresh"}).json()["items"]
    assert [item["id"] for item in result] == [str(fresh.id)]
    assert result[0]["latency_ms"] is None
    assert result[0]["cache_similarity"] is None
    assert result[0]["retrieval_similarity"] == 0.0
    assert len(client.get(URL, params={"days": 90}).json()["items"]) == 4
    # LIKE metacharacters must search literally, not expand the result set.
    assert len(client.get(URL, params={"search": "%_"}).json()["items"]) == 1
    assert len(client.get(URL, params={"min_latency_ms": 0}).json()["items"]) == 2


def test_cursor_pagination_is_stable_across_inserts(explorer):
    client, db, mine, _ = explorer
    rows = [log(db, mine) for _ in range(5)]
    first = client.get(URL, params={"limit": 2}).json()
    assert [item["id"] for item in first["items"]] == [str(rows[4].id), str(rows[3].id)]
    log(db, mine)
    second = client.get(URL, params={"limit": 2, "before": first["next_cursor"]}).json()
    third = client.get(URL, params={"limit": 2, "before": second["next_cursor"]}).json()
    assert [item["id"] for item in second["items"] + third["items"]] == [str(row.id) for row in reversed(rows[:3])]
    assert third["next_cursor"] is None


def test_full_question_only_in_detail_and_bigint_ids_are_strings(explorer):
    client, db, mine, _ = explorer
    row = log(db, mine, id=9_007_199_254_740_993, question="A" * 2000)
    item = client.get(URL).json()["items"][0]
    assert item["id"] == str(row.id)
    assert len(item["question"]) == 320
    assert client.get(f"{URL}/{row.id}").json()["question"] == "A" * 2000
    assert client.get(f"{URL}/99999999999999999999999").status_code == 404


@pytest.mark.parametrize("params", [
    {"days": 8}, {"limit": 101}, {"limit": 0}, {"before": -1},
    {"before": "99999999999999999999999"}, {"cache": "bogus"},
    {"min_latency_ms": -1}, {"search": "x" * 201}, {"project_id": "bad"},
])
def test_invalid_filters_are_rejected(explorer, params):
    assert explorer[0].get(URL, params=params).status_code == 422


def test_requires_authentication():
    app = FastAPI()
    app.include_router(router)
    # Avoid even acquiring the production DB when testing missing auth.
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as client:
        assert client.get(URL).status_code in (401, 403)
        assert client.get(f"{URL}/1").status_code in (401, 403)
