"""Workflow contracts: owner isolation, stale evidence, debounce, and measurements."""
import copy
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from app.models import Base, Chunk, EvaluationRun, EvaluationSchedule, File, KnowledgeGapReview, QueryLog, SavedQueryView, SourceConflictReview
from app.routers import gap_verification, knowledge_gaps, saved_views, source_conflicts
from app.services import cache_insights, evaluations, quality, query_timeline
from app.services import knowledge_gaps as gaps
from app.services import source_conflicts as conflicts
from tests.test_evaluations import app_data, base, SUITE


@pytest.fixture()
def workflows(app_data):
    client, db, project, other = app_data
    Base.metadata.create_all(db.get_bind(), tables=[KnowledgeGapReview.__table__, SavedQueryView.__table__, SourceConflictReview.__table__])
    for module in (gap_verification, knowledge_gaps, saved_views, source_conflicts):
        client.app.include_router(module.router)
    return client, db, project, other


FILTERS = {"days": "30", "project": "", "search": "refund", "cache": "fresh", "feedback": "unrated", "latency": "1000"}


def test_saved_views_roundtrip_rename_delete_and_scope(workflows):
    client, db, project, other = workflows
    view_id = str(uuid.uuid4())
    endpoint = f"/api/account/query-views/{view_id}"
    body = {"id": view_id, "name": "Slow refunds", "kind": "queries", "filters": {**FILTERS, "project": str(project.id)}}
    assert client.put(endpoint, json=body).status_code == 200
    assert client.put(endpoint, json=body).status_code == 200  # retry does not duplicate
    assert client.get("/api/account/query-views?kind=queries").json()[0]["filters"] == body["filters"]
    assert client.get("/api/account/query-views?kind=failures").json() == []
    assert client.put(endpoint, json={**body, "filters": {**FILTERS, "project": str(other.id)}}).status_code == 404
    stranger = SavedQueryView(owner_id=other.owner_id, name="Private", kind="queries", filters=FILTERS)
    db.add(stranger); db.commit()
    assert client.delete(f"/api/account/query-views/{stranger.id}").status_code == 404
    assert client.put(f"/api/account/query-views/{stranger.id}", json={**body, "id": str(stranger.id)}).status_code == 404
    assert client.put(endpoint, json={**body, "name": "Renamed"}).status_code == 200
    assert client.delete(endpoint).status_code == 204
    assert client.get("/api/account/query-views?kind=queries").json() == []


@pytest.mark.parametrize("patch", [{"days": "999"}, {"before": "50"}, {"search": "bad\x00"}, {"project": "not-a-uuid"}, {"cache": "invalid"}])
def test_saved_views_validate_filters(workflows, patch):
    client, _, _, _ = workflows
    view_id = str(uuid.uuid4())
    assert client.put(f"/api/account/query-views/{view_id}", json={"id": view_id, "name": "Test", "kind": "queries", "filters": {**FILTERS, **patch}}).status_code == 422


def gap_query(db, project):
    row = QueryLog(project_id=project.id, question="How long is the refund window?", retrieval_similarity=.1,
                   created_at=datetime.now(timezone.utc) - timedelta(seconds=2))
    db.add(row); db.commit()
    return row


def verification_body(client, db, project):
    query = gap_query(db, project)
    key = gaps.question_key(query.question)
    review_endpoint = f"/api/account/knowledge-gaps/{project.id}/{key}"
    detail = client.get(review_endpoint).json()
    body = {"id": str(uuid.uuid4()), "evidence_version": detail["item"]["evidence_version"],
            "cases": [{"query_id": str(query.id), "expected": "30 days", "source": "policy.pdf"}]}
    return f"/api/projects/{project.id}/gaps/{key}/verification", review_endpoint, body


def test_verify_fix_reuses_evaluator_and_rejects_foreign_queries(workflows):
    client, db, project, other = workflows
    endpoint, _, body = verification_body(client, db, project)
    original = {column.key: getattr(project, column.key) for column in project.__table__.columns}
    foreign = gap_query(db, other)
    assert client.post(endpoint, json={**body, "cases": [{"query_id": str(foreign.id)}]}).status_code == 422
    assert client.post(endpoint, json={**body, "evidence_version": "0" * 64}).status_code == 409
    result = client.post(endpoint, json=body)
    assert result.status_code == 201, result.text
    run = result.json()
    assert run["trigger_reason"] == "gap_verification"
    assert run["suite"]["cases"][0]["expected"] == "30 days"
    assert client.post(endpoint, json=body).json()["id"] == run["id"]
    assert client.post(endpoint, json={**body, "id": str(uuid.uuid4())}).status_code == 409
    assert client.post(endpoint, json={**body, "cases": [{"query_id": body["cases"][0]["query_id"], "expected": "other"}]}).status_code == 409
    assert original == {column.key: getattr(project, column.key) for column in project.__table__.columns}
    assert client.get(endpoint.replace(str(project.id), str(other.id))).status_code == 404


def test_verified_resolution_requires_complete_current_results(workflows):
    client, db, project, _ = workflows
    endpoint, review_endpoint, body = verification_body(client, db, project)
    run_id = client.post(endpoint, json=body).json()["id"]
    run = db.get(EvaluationRun, uuid.UUID(run_id))
    item = client.get(review_endpoint).json()["item"]
    resolution = {"status": "resolved", "revision": item["revision"], "evidence_version": item["evidence_version"], "verification_run_id": run_id}
    assert client.put(review_endpoint, json=resolution).status_code == 409
    run.status = "completed"
    run.results = [{"caseId": run.suite["cases"][0]["id"], "variant": 0, "status": "review"}]; db.commit()
    assert client.put(review_endpoint, json=resolution).status_code == 409
    run.results = [{**run.results[0], "status": "passed"}]; db.commit()
    project.top_k += 1; db.commit()
    assert client.get(endpoint).json()["runs"][0]["matches_current"] is False
    assert client.put(review_endpoint, json=resolution).status_code == 409
    project.top_k -= 1; db.commit()
    response = client.put(review_endpoint, json=resolution)
    assert response.status_code == 200, response.text
    assert response.json()["item"]["verification_run_id"] == run_id
    # An attached historical result survives a note edit after later changes.
    project.top_k += 1; db.commit()
    assert client.put(review_endpoint, json={**resolution, "revision": 1, "note": "Reviewed at the time"}).status_code == 200


def enable_changes(client, project):
    assert client.put(base(project)+"/suite", json={"revision": 0, "suite": SUITE}).status_code == 200
    response = client.put(base(project)+"/schedule", json={"revision": 0, "on_changes": True, "enabled": False})
    assert response.status_code == 200, response.text


def test_changes_debounce_and_wait_for_indexing(workflows, monkeypatch):
    client, db, project, _ = workflows
    enable_changes(client, project)
    schedule = db.get(EvaluationSchedule, project.id)
    instant = quality.now() + timedelta(seconds=1)
    monkeypatch.setattr(quality, "now", lambda: instant)
    assert quality.queue_changes(db)
    assert db.query(EvaluationRun).count() == 0
    project.content_version += 1; db.commit()
    instant += timedelta(seconds=31)
    assert quality.queue_changes(db)
    assert schedule.pending_signature and schedule.change_due_at
    project.top_k += 1; db.commit()
    instant += timedelta(seconds=31)
    assert quality.queue_changes(db)
    assert db.query(EvaluationRun).count() == 0
    file = db.scalar(select(File).where(File.project_id == project.id))
    file.status = "processing"; db.commit()
    instant += timedelta(seconds=61)
    assert quality.queue_changes(db)
    assert db.query(EvaluationRun).count() == 0
    file.status = "indexed"; db.commit()
    instant += timedelta(seconds=31)
    assert quality.queue_changes(db)
    run = db.query(EvaluationRun).one()
    assert run.trigger_reason == "project_change"
    assert run.suite["variants"][0]["top_k"] == project.top_k
    assert len(run.suite["variants"]) == 1
    instant += timedelta(seconds=31)
    assert quality.queue_changes(db)
    assert db.query(EvaluationRun).count() == 1
    assert client.get(base(project)+"/change-checks").json()[0]["id"] == str(run.id)


def test_change_comparison_records_individual_checks(workflows):
    _, db, project, _ = workflows
    suite = copy.deepcopy(SUITE); suite["variants"] = suite["variants"][:1]
    before = EvaluationRun(project_id=project.id, status="completed", suite=suite, corpus=[], corpus_count=1, content_version=0, results=[{"caseId": "q", "variant": 0, "status": "failed"}])
    db.add(before); db.commit()
    after = EvaluationRun(project_id=project.id, status="completed", reference_run_id=before.id, trigger_reason="project_change",
        suite={**suite, "variants": [{**suite["variants"][0], "top_k": 9}]}, results=[{"caseId": "q", "variant": 0, "status": "passed"}])
    result = quality.assess(db, after)
    assert result["configuration_changed"] is True
    assert result["case_changes"] == [{"case_id": "q", "before": "failed", "after": "passed"}]


def test_change_checks_validate_current_project_credentials(workflows, monkeypatch):
    client, _, project, _ = workflows
    checked = []
    monkeypatch.setattr(evaluations, "check_credentials", lambda db, project, suite: checked.extend(suite.variants))
    enable_changes(client, project)
    assert [config.model_dump() for config in checked] == [quality.project_config(project).model_dump()]


def passage(content, **values):
    return {"content": content, "file_id": uuid.uuid4(), "document_id": None, "filename": "policy.pdf", "page_number": 1,
            "in_force_from": None, "in_force_to": None, "version_label": None, **values}


def test_conflict_candidates_require_matching_claims_and_separate_documents():
    a, b = passage("Customer refunds are available within 30 days."), passage("Customer refunds are available within 14 days.")
    assert len(conflicts.candidates([a, b])[0]) == 1
    assert conflicts.candidates([a, {**b, "file_id": a["file_id"]}])[0] == []
    lineage = uuid.uuid4()
    assert conflicts.candidates([{**a, "document_id": lineage}, {**b, "document_id": lineage}])[0] == []
    assert conflicts.candidates([a, passage("Customer returns must include an original receipt.")])[0] == []
    assert conflicts.candidates([a, passage(a["content"])])[0] == []
    assert conflicts.candidates([a, passage("Customer refunds are available within 30.0 days.")])[0] == []
    assert len(conflicts.candidates([passage("Customers may request a refund online."), passage("Customers may not request a refund online.")])[0]) == 1


def test_source_review_is_scoped_versioned_and_durable(workflows):
    client, db, project, other = workflows
    first = db.scalar(select(Chunk).where(Chunk.project_id == project.id))
    first.content = "Customer refunds are available within 30 days."
    second = File(project_id=project.id, filename="returns.pdf", storage_path="private", status="indexed", in_force_from=date(2020, 1, 1))
    db.add(second); db.flush()
    db.add(Chunk(project_id=project.id, file_id=second.id, chunk_index=0, content="Customer refunds are available within 14 days.", embedding=[1, 0]))
    db.commit()
    endpoint = f"/api/projects/{project.id}/source-conflicts"
    report = client.get(endpoint).json()
    assert len(report["items"]) == 1
    item = report["items"][0]
    body = {"status": "confirmed", "note": "Update the old refund policy", "revision": 0, "content_version": project.content_version}
    assert client.put(f'{endpoint}/{item["key"]}', json=body).status_code == 200
    assert client.put(f'{endpoint}/{item["key"]}', json=body).status_code == 409
    assert client.get(endpoint).json()["items"][0]["status"] == "confirmed"
    assert client.get(endpoint.replace(str(project.id), str(other.id))).status_code == 404
    assert first.content.endswith("30 days.")  # reviews do not rewrite sources
    second.status = "review"; db.commit()
    assert client.get(endpoint).json()["items"] == []
    assert client.put(f'{endpoint}/{item["key"]}', json={**body, "revision": 1}).status_code == 409


def test_cache_observation_does_not_invent_missing_entry_reasons():
    from app.services.query_cache import InMemoryBackend, QueryCache
    store = QueryCache(InMemoryBackend(), ttl_seconds=30, serialize=lambda value: value, deserialize=lambda value: value)
    with query_timeline.adopt(query_timeline.Timeline()):
        cache_insights.start(signature="test|v7", history_turns=2, history_unavailable=False, bypass=False,
            exact_enabled=True, semantic_enabled=True, backend="redis", ttl=30)
        assert store.get("missing") is None
        details = cache_insights.snapshot(None)
        assert details["exact"] == "no_entry"
        assert details["semantic"] == "conversation_context"
        assert details["content_version"] == 7
        store.set("same", "answer")
        assert store.get("same") == "answer"
        assert cache_insights.snapshot("l1")["exact"] == "hit"
    assert cache_insights.snapshot(None) is None


@pytest.mark.parametrize("reason", ["project_change", "gap_verification"])
def test_finished_change_check_chains_can_be_archived(workflows, reason):
    from app.services.evaluation_retention import make_room
    _, db, project, _ = workflows
    prior = None
    for i in range(20):
        run = EvaluationRun(project_id=project.id, status="completed", trigger_reason=reason, reference_run_id=prior,
            suite=SUITE, corpus=[], corpus_count=1, content_version=i, results=[], quality_report={"state": "passed", "warnings": []},
            created_at=datetime.now(timezone.utc) - timedelta(days=20-i))
        db.add(run); db.flush(); prior = run.id
    db.commit()
    make_room(db, project.id)
    assert db.scalar(select(sa.func.count()).select_from(EvaluationRun).where(EvaluationRun.archived_at.is_not(None))) == 1


def test_gap_verification_compares_only_matching_tests(workflows):
    client, db, project, _ = workflows
    endpoint, _, body = verification_body(client, db, project)
    first = client.post(endpoint, json=body).json()
    assert first["reference_run_id"] is None
    run = db.get(EvaluationRun, uuid.UUID(first["id"]))
    run.status = "completed"
    run.results = [{"caseId": run.suite["cases"][0]["id"], "variant": 0, "status": "failed"}]
    db.commit()
    project.content_version += 1; db.commit()
    second_response = client.post(endpoint, json={**body, "id": str(uuid.uuid4())})
    assert second_response.status_code == 201, second_response.text
    second = db.get(EvaluationRun, uuid.UUID(second_response.json()["id"]))
    assert second.reference_run_id == run.id
    second.status = "completed"
    second.results = [{**run.results[0], "status": "passed"}]
    second.quality_report = quality.assess(db, second)
    assert second.quality_report["case_changes"] == [{"case_id": run.suite["cases"][0]["id"], "before": "failed", "after": "passed"}]
    db.commit()
    changed = client.post(endpoint, json={**body, "id": str(uuid.uuid4()), "cases": [{**body["cases"][0], "expected": "different check"}]})
    assert changed.status_code == 201, changed.text
    assert changed.json()["reference_run_id"] is None


def test_attached_verification_remains_visible_beyond_latest_five_runs(workflows):
    import gzip
    import json
    from fastapi.encoders import jsonable_encoder
    client, db, project, _ = workflows
    endpoint, review_endpoint, body = verification_body(client, db, project)
    run_id = client.post(endpoint, json=body).json()["id"]
    run = db.get(EvaluationRun, uuid.UUID(run_id))
    run.status = "completed"
    run.results = [{"caseId": run.suite["cases"][0]["id"], "variant": 0, "status": "passed"}]
    db.commit()
    item = client.get(review_endpoint).json()["item"]
    assert client.put(review_endpoint, json={"status": "resolved", "revision": item["revision"],
        "evidence_version": item["evidence_version"], "verification_run_id": run_id}).status_code == 200
    run.archived_payload = gzip.compress(json.dumps(jsonable_encoder(evaluations.run_out(run))).encode())
    run.archived_at = datetime.now(timezone.utc)
    run.results = []
    for i in range(6):
        db.add(EvaluationRun(project_id=project.id, status="completed", suite=run.suite, gap_key=run.gap_key,
            results=[], corpus=[], corpus_count=1, content_version=run.content_version, created_at=run.created_at + timedelta(minutes=i+1)))
    db.commit()
    history = client.get(endpoint).json()["runs"]
    assert len(history) == 6
    saved = next(entry for entry in history if entry["id"] == run_id)
    assert saved["results"][0]["status"] == "passed"
    assert saved["archived_at"] is not None


@pytest.mark.parametrize("reason", ["gap_verification", "project_change"])
def test_background_completion_preserves_case_comparisons(workflows, monkeypatch, reason):
    from app.schemas import QueryResponse
    from tests.test_evaluations import start
    client, db, project, _ = workflows
    suite = copy.deepcopy(SUITE)
    suite["variants"] = suite["variants"][:1]
    suite["cases"][0]["source"] = ""
    before = db.get(EvaluationRun, uuid.UUID(start(client, project, suite)["id"]))
    before.status = "completed"
    before.results = [{"caseId": "q", "variant": 0, "status": "failed"}]
    db.commit()
    after = db.get(EvaluationRun, uuid.UUID(start(client, project, suite)["id"]))
    after.trigger_reason, after.reference_run_id = reason, before.id
    db.commit()
    monkeypatch.setattr(evaluations, "run_query", lambda *args, **kwargs: QueryResponse(answer="30 days", sources=[], model="gpt-4o-mini", latency_ms=10))
    for _ in range(3):
        if after.status == "completed": break
        assert quality.run_one(db)
    assert after.status == "completed"
    assert after.quality_report["case_changes"] == [{"case_id": "q", "before": "failed", "after": "passed"}]
