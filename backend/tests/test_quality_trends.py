import gzip
import json
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
from app.models import ApiKey, Base, EvaluationRun, Project, QueryLog
from app.routers.knowledge_health import router
from app.services import quality_trends as service

BASE = "/api/account/knowledge-health"
END = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


@compiles(sa.BigInteger, "sqlite")
def _bigint(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture()
def trends():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[Project.__table__, ApiKey.__table__, QueryLog.__table__, EvaluationRun.__table__])
    with Session(engine) as db:
        mine, other = Project(owner_id=uuid.uuid4(), name="Mine"), Project(owner_id=uuid.uuid4(), name="Other")
        db.add_all([mine, other]); db.commit()
        app = FastAPI(); app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: mine.owner_id
        with TestClient(app) as client:
            yield client, db, mine, other
    engine.dispose()


def query(db, project, **values):
    values = {"question": "How do refunds work?", "created_at": END-timedelta(hours=2), "retrieval_similarity": 0.2, **values}
    db.add(QueryLog(project_id=project.id, **values)); db.commit()


def run(db, project, statuses=("passed", "failed"), **values):
    suite = values.pop("suite", {"cases": [{"id": str(i), "question": "Private question"} for i in range(2)],
                                "variants": [{"llm_provider": "openai", "llm_model": "test-model"}]})
    results = [{"variant": 0, "status": status, "response": {"answer": "Private answer", "latency_ms": 100}, "cost_usd": 0.001} for status in statuses]
    row = EvaluationRun(project_id=project.id, suite=suite, results=results, corpus=[], corpus_count=0, content_version=1,
                        status="completed", created_at=END-timedelta(hours=1), **values)
    db.add(row); db.commit()
    return row


def test_scope_validation_and_no_private_payloads(trends):
    client, db, mine, other = trends
    query(db, mine); query(db, other); run(db, mine); run(db, other)
    assert client.get(f"{BASE}/trends").json()["current"]["queries"] == 1
    for endpoint in ("trends", "evaluation-trends"):
        assert client.get(f"{BASE}/{endpoint}", params={"project_id": other.id}).status_code == 404
        assert client.get(f"{BASE}/{endpoint}", params={"project_id": mine.id, "days": 8}).status_code == 422
        assert client.get(f"{BASE}/{endpoint}", params={"project_id": "bad"}).status_code == 422
    response = client.get(f"{BASE}/evaluation-trends", params={"project_id": mine.id})
    assert response.status_code == 200
    assert "Private" not in response.text and "suite" not in response.text and "response" not in response.text
    assert client.get(f"{BASE}/evaluation-trends").status_code == 422


def test_equal_complete_utc_periods_exclude_today_and_preserve_boundaries(trends):
    client, db, mine, _ = trends
    for instant in [END, END+timedelta(days=1), END-timedelta(days=7), END-timedelta(days=14), END-timedelta(days=14, seconds=1)]:
        query(db, mine, created_at=instant)
    data = client.get(f"{BASE}/trends", params={"days": 7}).json()
    assert data["current"]["queries"] == data["previous"]["queries"] == 1
    assert len(data["daily"]) == 7 and data["daily"][0]["date"] == (END-timedelta(days=7)).date().isoformat()
    assert data["current"]["start"] == data["previous"]["end"]


def test_weighted_feedback_and_document_denominators_exclude_casual_cache_and_unknown(trends):
    client, db, mine, _ = trends
    query(db, mine, feedback_rating="helpful", retrieval_similarity=0)
    query(db, mine, feedback_rating="not_helpful", retrieval_similarity=0.7)
    query(db, mine, retrieval_similarity=None)
    query(db, mine, question="heeeeeey", retrieval_similarity=0.1)
    query(db, mine, cache_layer="l2", retrieval_similarity=0.1)
    data = client.get(f"{BASE}/trends").json()["current"]
    assert data["queries"] == 5 and data["rated"] == 2 and data["helpful_percent"] == 50
    assert data["document_queries"] == 3 and data["measured"] == 2
    assert data["low_match_percent"] == 50 and data["avg_similarity"] == pytest.approx(0.35)


def test_empty_unrated_unknown_and_zero_are_distinct(trends):
    client, db, mine, _ = trends
    empty = client.get(f"{BASE}/trends").json()
    assert empty["current"]["helpful_percent"] is None
    assert all(day["low_match_percent"] is None for day in empty["daily"])
    query(db, mine, feedback_rating="not_helpful", retrieval_similarity=0.9)
    data = client.get(f"{BASE}/trends").json()["current"]
    assert data["helpful_percent"] == data["low_match_percent"] == 0


def test_scan_cap_marks_unseen_history_incomplete(trends, monkeypatch):
    client, db, mine, _ = trends
    for days in [1, 1, 2, 8]: query(db, mine, created_at=END-timedelta(days=days))
    monkeypatch.setattr(service, "SCAN_LIMIT", 2)
    data = client.get(f"{BASE}/trends", params={"days": 7}).json()
    assert data["limited"] and data["scanned_queries"] == 2
    assert not data["current"]["complete"] and not data["previous"]["complete"]
    assert all(not day["complete"] for day in data["daily"])


def test_evaluations_group_only_identical_suites_and_keep_archives(trends):
    client, db, mine, _ = trends
    first = run(db, mine)
    second = run(db, mine, statuses=("passed", "passed"))
    second.archived_payload = gzip.compress(json.dumps({"suite": second.suite, "results": second.results}).encode())
    second.archived_at = END; second.results = []
    changed = {**first.suite, "cases": [{"id": "changed", "question": "Different question"}]}
    run(db, mine, statuses=("passed",), suite=changed)
    db.commit()
    data = client.get(f"{BASE}/evaluation-trends", params={"project_id": mine.id}).json()
    assert len(data["series"]) == 2
    group = next(group for group in data["series"] if group["cases"] == 2)
    assert sorted(point["pass_percent"] for point in group["points"]) == [50, 100]
    assert sum(point["archived"] for point in group["points"]) == 1


def test_evaluation_nulls_partial_checks_and_variants_remain_separate(trends):
    client, db, mine, _ = trends
    row = run(db, mine, statuses=("passed", "unscored"))
    row.results = [{**result, "cost_usd": None} for result in row.results]
    row.suite = {**row.suite, "variants": row.suite["variants"] * 2}
    row.results += [{"variant": 1, "status": "failed", "response": {"latency_ms": 0}, "cost_usd": 0} for _ in range(2)]
    db.commit()
    points = client.get(f"{BASE}/evaluation-trends", params={"project_id": mine.id}).json()["series"][0]["points"]
    assert points[0]["checked"] == 1 and points[0]["unscored"] == 1 and points[0]["cost_usd"] is None
    assert points[1]["pass_percent"] == points[1]["cost_usd"] == points[1]["latency_ms"] == 0


def test_evaluation_run_cap_and_only_completed_in_window(trends, monkeypatch):
    client, db, mine, _ = trends
    run(db, mine); run(db, mine)
    old = run(db, mine); old.created_at = END-timedelta(days=100)
    active = run(db, mine); active.status = "running"
    future = run(db, mine); future.created_at = END+timedelta(days=1)
    db.commit(); monkeypatch.setattr(service, "RUN_LIMIT", 1)
    data = client.get(f"{BASE}/evaluation-trends", params={"project_id": mine.id}).json()
    assert data["limited"] and len(data["series"][0]["points"]) == 1


def test_gets_are_read_only_and_auth_required(trends):
    client, db, mine, _ = trends
    query(db, mine); run(db, mine)
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany): statements.append(statement.strip().split()[0].upper())
    sa.event.listen(db.get_bind(), "before_cursor_execute", capture)
    client.get(f"{BASE}/trends"); client.get(f"{BASE}/evaluation-trends", params={"project_id": mine.id})
    sa.event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert statements and set(statements) == {"SELECT"}
    app = FastAPI(); app.include_router(router); app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as anonymous:
        assert anonymous.get(f"{BASE}/trends").status_code in (401, 403)
