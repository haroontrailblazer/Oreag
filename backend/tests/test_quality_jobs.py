import uuid
from datetime import timedelta
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.evaluation_schemas import EvaluationSuite, SaveSchedule
from app.models import EvaluationRun, EvaluationSchedule, EvaluationSuiteRecord, QueryLog, ApiKey
from app.services import quality, evaluations
from tests.test_evaluations import app_data, base, start, SUITE


def test_schedule_snapshot_revision_and_single_due_run(app_data):
    client, db, project, other = app_data
    saved = client.put(base(project)+"/suite", json={"revision": 0, "suite": SUITE}).json()
    response = client.put(base(project)+"/schedule", json={"revision": 0, "enabled": True, "interval_hours": 6})
    assert response.status_code == 200, response.text
    assert client.get(base(other)+"/schedule").status_code == 404
    assert client.put(base(project)+"/schedule", json={"revision": 0}).status_code == 409
    schedule = db.get(EvaluationSchedule, project.id)
    snapshot = schedule.suite
    client.put(base(project)+"/suite", json={"revision": saved["revision"], "suite": {**SUITE, "cases": []}})
    assert schedule.suite == snapshot
    schedule.next_run_at = quality.now() - timedelta(seconds=1); db.commit()
    assert quality.queue_due(db)
    assert not quality.queue_due(db)
    run = db.query(EvaluationRun).one()
    assert run.execution == "background" and run.suite == snapshot
    schedule.next_run_at = quality.now() - timedelta(seconds=1); db.commit()
    assert quality.queue_due(db)
    assert db.query(EvaluationRun).count() == 1
    assert "still active" in schedule.last_error
    assert client.put(base(project)+"/schedule", json={"revision": 1, "enabled": False}).status_code == 200
    assert not schedule.enabled


def test_worker_completes_without_browser_and_recovers_expired_lease(app_data, monkeypatch):
    from app.schemas import QueryResponse
    client, db, project, _ = app_data
    original = {c.key: getattr(project, c.key) for c in project.__table__.columns}
    run_id = uuid.UUID(start(client, project)["id"])
    row = db.get(EvaluationRun, run_id)
    row.lease_until = quality.now() + timedelta(minutes=1); db.commit()
    assert not quality.run_one(db)
    row.lease_until = quality.now() - timedelta(seconds=1); db.commit()
    monkeypatch.setattr(evaluations, "run_query", lambda *a, **kw: QueryResponse(answer="30 days", sources=[], model="gpt-4o-mini", latency_ms=10))
    for _ in range(4): assert quality.run_one(db)
    assert row.status == "completed" and len(row.results) == 2
    assert row.quality_report["state"] == "no_reference"
    assert not quality.run_one(db)
    assert original == {c.key: getattr(project, c.key) for c in project.__table__.columns}


def test_background_progress_and_revoked_key(app_data):
    client, db, project, _ = app_data
    run = start(client, project)
    assert quality.run_one(db)
    row = db.get(EvaluationRun, uuid.UUID(run["id"]))
    assert row.prepared > 0
    row.requested_by_key_id = uuid.uuid4(); db.commit()
    assert quality.run_one(db)
    assert row.status == "failed" and "API key" in row.error


def test_reference_regressions_nulls_and_project_scope(app_data):
    client, db, project, other = app_data
    row = db.get(EvaluationRun, uuid.UUID(start(client, project)["id"]))
    row.status = "completed"
    row.results = [{"variant": i, "status": "passed", "response": {"latency_ms": 100}, "cost_usd": .01} for i in (0, 1)]
    db.commit()
    current = SimpleNamespace(project_id=project.id, reference_run_id=row.id, suite=row.suite, quality_limits={},
        results=[{"variant": 0, "status": "failed", "response": {"latency_ms": 200}, "cost_usd": .03}, {"variant": 1, "status": "review", "response": {"latency_ms": None}, "cost_usd": None}])
    report = quality.assess(db, current)
    assert report["state"] == "regressed" and len(report["warnings"]) == 3
    assert report["metrics"][1] == {"pass_percent": None, "latency_ms": None, "cost_usd": None}
    with pytest.raises(HTTPException): quality.validate_reference(db, other.id, row.id, row.suite)
    with pytest.raises(HTTPException): quality.validate_reference(db, project.id, row.id, {**row.suite, "cases": []})


def test_add_query_preserves_expected_and_rejects_duplicates_and_other_project(app_data):
    client, db, project, other = app_data
    client.put(base(project)+"/suite", json={"revision": 0, "suite": SUITE})
    q = QueryLog(project_id=project.id, question="How do returns work?")
    db.add(q); db.commit()
    body = {"query_id": str(q.id), "revision": 1, "expected": "Return within 30 days."}
    assert client.post(base(other)+"/cases/from-query", json=body).status_code == 404
    result = client.post(base(project)+"/cases/from-query", json=body)
    assert result.status_code == 200, result.text
    case = result.json()["suite"]["cases"][-1]
    assert case["question"] == q.question and case["expected"] == body["expected"]
    assert client.post(base(project)+"/cases/from-query", json={**body, "revision": 2}).status_code == 409
