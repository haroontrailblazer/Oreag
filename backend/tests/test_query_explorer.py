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
        assert client.put(f"{URL}/1/feedback", json={"rating": "helpful"}).status_code in (401, 403)
        assert client.delete(f"{URL}/1/feedback").status_code in (401, 403)


def test_feedback_persists_updates_and_clears(explorer):
    client, db, mine, _ = explorer
    row = log(db, mine, id=9_007_199_254_740_993)
    url = f"{URL}/{row.id}/feedback"
    response = client.put(url, json={"rating": "not_helpful", "note": "  Missing the exception.  "})
    assert response.status_code == 200
    saved = client.get(f"{URL}/{row.id}").json()
    assert saved["feedback_rating"] == "not_helpful"
    assert saved["feedback_note"] == "Missing the exception."
    assert saved["feedback_updated_at"].endswith("Z")
    # Full notes are detail-only, not repeated in every history response.
    listed = client.get(URL).json()["items"][0]
    assert listed["feedback_rating"] == "not_helpful" and listed["feedback_note"] is None
    assert client.put(url, json={"rating": "helpful"}).status_code == 200
    assert client.get(f"{URL}/{row.id}").json()["feedback_note"] is None
    assert client.delete(url).status_code == 204
    cleared = client.get(f"{URL}/{row.id}").json()
    assert all(cleared[field] is None for field in ("feedback_rating", "feedback_note", "feedback_updated_at"))
    assert client.delete(url).status_code == 204


def test_feedback_cannot_modify_another_owners_query(explorer):
    client, db, _, other = explorer
    row = log(db, other)
    for query_id in (row.id, 0, -1, 999999999999999999999):
        assert client.put(f"{URL}/{query_id}/feedback", json={"rating": "helpful"}).status_code == 404
        assert client.delete(f"{URL}/{query_id}/feedback").status_code == 404
    db.expire_all()
    assert db.get(QueryLog, row.id).feedback_rating is None


def test_feedback_filters_apply_before_pagination(explorer):
    client, db, mine, other = explorer
    rated = [log(db, mine, feedback_rating="not_helpful", feedback_updated_at=datetime.now(timezone.utc)) for _ in range(3)]
    log(db, other, feedback_rating="not_helpful", feedback_updated_at=datetime.now(timezone.utc))
    helpful = log(db, mine, feedback_rating="helpful", feedback_updated_at=datetime.now(timezone.utc))
    unrated = log(db, mine)
    first = client.get(URL, params={"feedback": "not_helpful", "limit": 2}).json()
    second = client.get(URL, params={"feedback": "not_helpful", "before": first["next_cursor"]}).json()
    assert [item["id"] for item in first["items"] + second["items"]] == [str(row.id) for row in reversed(rated)]
    assert client.get(URL, params={"feedback": "helpful"}).json()["items"][0]["id"] == str(helpful.id)
    assert client.get(URL, params={"feedback": "unrated"}).json()["items"][0]["id"] == str(unrated.id)
    assert client.get(URL, params={"feedback": "invalid"}).status_code == 422


@pytest.mark.parametrize("body", [
    {"rating": "great"}, {"rating": 1}, {"rating": None},
    {"rating": "helpful", "note": "x" * 1001},
    {"rating": "helpful", "note": "bad\x00note"},
    {"rating": "helpful", "project_id": "untrusted"},
])
def test_invalid_feedback_is_rejected(explorer, body):
    client, db, mine, _ = explorer
    row = log(db, mine)
    assert client.put(f"{URL}/{row.id}/feedback", json=body).status_code == 422
    assert client.get(f"{URL}/{row.id}").json()["feedback_rating"] is None


@pytest.mark.parametrize("streaming", [False, True])
def test_answer_identity_is_persisted_and_distinct_on_cache_hits(explorer, monkeypatch, streaming):
    from app.services import query

    client, db, mine, _ = explorer
    # Real logging transactions, with content existence and provider calls stubbed.
    class QueryDB:
        def scalar(self, *args, **kwargs):
            return 1

        def __getattr__(self, name):
            return getattr(db, name)

    monkeypatch.setattr(query.settings, "query_cache_enabled", True)
    monkeypatch.setattr(query.retrieval, "retrieve", lambda *a, **k: [
        {"filename": "guide.md", "page_number": None, "chunk_index": i,
         "content": "A useful fact.", "similarity": 0.9} for i in range(2)
    ])
    monkeypatch.setattr(query.memory_service, "search_memories", lambda *a, **k: [])
    monkeypatch.setattr(query.semantic_cache, "lookup", lambda *a, **k: (None, [0.1], None))
    monkeypatch.setattr(query.semantic_cache, "store", lambda *a, **k: None)
    monkeypatch.setattr(query.generation, "generate_answer", lambda *a, **k: "A useful answer.")
    monkeypatch.setattr(query.generation, "generate_answer_stream", lambda *a, **k: iter(["A useful answer."]))

    def answer():
        if streaming:
            events = list(query.run_query_stream(QueryDB(), mine, "What is this?", None, api_key_id=None))
            return next(event["response"] for event in events if event["type"] == "done")
        return query.run_query(QueryDB(), mine, "What is this?", None, api_key_id=None).model_dump()

    first, cached = answer(), answer()
    assert first["query_id"] and first["query_id"] != cached["query_id"]
    assert cached["cache_layer"] == "l1"
    assert first["answer"] == cached["answer"] == "A useful answer."
    assert client.put(f"{URL}/{first['query_id']}/feedback", json={"rating": "helpful"}).status_code == 200
    assert client.get(f"{URL}/{cached['query_id']}").json()["feedback_rating"] is None
