"""Public feedback with real key authentication, SQL scopes, and rate limits."""
import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.auth.api_keys import generate_api_key
from app.auth.jwt import get_current_user
from app.db import get_db
from app.models import ApiKey, Base, File, Project, QueryLog, SuspendedAccount
from app.routers import knowledge_health, query_explorer, rag_v1
from app.services import rate_limit


@compiles(sa.BigInteger, "sqlite")
def _bigint(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture()
def feedback(monkeypatch):
    monkeypatch.setattr(rate_limit, "limiter", rate_limit.RateLimiter())
    monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rate_limit.settings, "query_rate_per_minute_per_key", 120)
    monkeypatch.setattr(rate_limit.settings, "query_rate_per_minute_per_project", 300)
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool,
                              connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[
        Project.__table__, ApiKey.__table__, QueryLog.__table__, SuspendedAccount.__table__, File.__table__,
    ])
    with Session(engine) as db:
        project = Project(owner_id=uuid.uuid4(), name="Mine")
        other = Project(owner_id=uuid.uuid4(), name="Other")
        db.add_all([project, other])
        db.flush()
        token, key_hash, prefix = generate_api_key()
        key = ApiKey(project_id=project.id, key_hash=key_hash, key_prefix=prefix)
        db.add(key)
        db.flush()
        own = QueryLog(id=9_007_199_254_740_993, project_id=project.id,
                       api_key_id=key.id, question="Our question")
        foreign = QueryLog(project_id=other.id, question="Private question")
        db.add_all([own, foreign])
        db.commit()
        app = FastAPI()
        app.include_router(rag_v1.router)
        app.include_router(query_explorer.router)
        app.include_router(knowledge_health.router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: project.owner_id
        with TestClient(app) as client:
            client.headers["Authorization"] = f"Bearer {token}"
            yield client, db, project, other, key, own, foreign
    engine.dispose()


def url(project, query):
    return f"/v1/projects/{project.id}/queries/{query.id}/feedback"


def test_save_replace_clear_and_dashboard_visibility(feedback):
    client, db, project, _, key, own, _ = feedback
    assert not key.can_upload  # Feedback does not require upload permission.
    response = client.put(url(project, own), json={"rating": "not_helpful", "note": "  Missing sources  "})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data == {"query_id": str(own.id), "rating": "not_helpful",
                    "note": "Missing sources", "updated_at": data["updated_at"]}
    assert datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")).tzinfo is not None
    listed = client.get("/api/account/queries", params={"feedback": "not_helpful"}).json()
    assert [item["id"] for item in listed["items"]] == [str(own.id)]
    detail = client.get(f"/api/account/queries/{own.id}").json()
    assert detail["feedback_note"] == "Missing sources"
    response = client.put(url(project, own), json={"rating": "helpful"})
    assert response.json()["note"] is None
    assert response.json()["rating"] == "helpful"
    for _ in range(2):
        response = client.delete(url(project, own))
        assert response.status_code == 204 and response.content == b""
    db.refresh(own)
    assert (own.feedback_rating, own.feedback_note, own.feedback_updated_at) == (None, None, None)


def test_feedback_submission_requires_only_project_key_not_owner_session(feedback):
    client, db, project, _, _, own, _ = feedback
    # Remove the dashboard login fixture: the real owner JWT dependency would
    # reject this project key if the public feedback route depended on it.
    client.app.dependency_overrides.pop(get_current_user)
    response = client.put(url(project, own), json={"rating": "helpful"})
    assert response.status_code == 200, response.text
    assert response.json()["rating"] == "helpful"
    db.refresh(own)
    assert own.feedback_rating == "helpful"
    assert client.delete(url(project, own)).status_code == 204


@pytest.mark.parametrize("method", ["put", "delete"])
def test_scope_authentication_and_suspension(feedback, method):
    client, db, project, other, key, own, foreign = feedback
    kwargs = {"json": {"rating": "helpful"}} if method == "put" else {}
    request = getattr(client, method)
    assert request(url(project, foreign), **kwargs).status_code == 404
    assert request(url(other, foreign), **kwargs).status_code == 401
    for query_id in (0, -1, 42, 9_223_372_036_854_775_808):
        path = f"/v1/projects/{project.id}/queries/{query_id}/feedback"
        assert request(path, **kwargs).status_code == 404
    for auth in ("", "Bearer bad", "Bearer oreag_sk_unknown"):
        assert request(url(project, own), headers={"Authorization": auth}, **kwargs).status_code == 401
    project.suspended = True
    db.commit()
    assert request(url(project, own), **kwargs).status_code == 403
    project.suspended = False
    db.add(SuspendedAccount(owner_id=project.owner_id))
    db.commit()
    assert request(url(project, own), **kwargs).status_code == 403
    db.delete(db.get(SuspendedAccount, project.owner_id))
    key.revoked_at = datetime.now(timezone.utc)
    db.commit()
    assert request(url(project, own), **kwargs).status_code == 401
    db.refresh(own)
    db.refresh(foreign)
    assert own.feedback_rating is None and foreign.feedback_rating is None


@pytest.mark.parametrize("body", [
    {}, {"rating": "bad"}, {"rating": True}, {"rating": "helpful", "note": None},
    {"rating": "helpful", "note": "x" * 1001}, {"rating": "helpful", "note": "a\x00b"},
    {"rating": "helpful", "project_id": "other"},
])
def test_validation_does_not_mutate(feedback, body):
    client, db, project, _, _, own, _ = feedback
    assert client.put(url(project, own), json=body).status_code == 422
    db.refresh(own)
    assert own.feedback_rating is None


def test_project_keys_share_feedback_and_rate_budget(feedback, monkeypatch):
    client, db, project, _, _, own, _ = feedback
    monkeypatch.setattr(rate_limit.settings, "query_rate_per_minute_per_project", 2)
    assert client.put(url(project, own), json={"rating": "helpful", "note": "x" * 1000}).status_code == 200
    token, key_hash, prefix = generate_api_key()
    db.add(ApiKey(project_id=project.id, key_hash=key_hash, key_prefix=prefix))
    db.commit()
    client.headers["Authorization"] = f"Bearer {token}"
    assert client.put(url(project, own), json={"rating": "not_helpful"}).status_code == 200
    response = client.delete(url(project, own))
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    db.refresh(own)
    assert own.feedback_rating == "not_helpful"


def test_key_rate_limit_blocks_writes(feedback, monkeypatch):
    client, db, project, _, _, own, _ = feedback
    monkeypatch.setattr(rate_limit.settings, "query_rate_per_minute_per_key", 1)
    assert client.delete(url(project, own)).status_code == 204
    response = client.put(url(project, own), json={"rating": "helpful"})
    assert response.status_code == 429 and "Retry-After" in response.headers
    db.refresh(own)
    assert own.feedback_rating is None


@pytest.mark.parametrize("streaming", [False, True])
def test_public_answers_cache_hits_and_feedback_flow_into_dashboards(feedback, monkeypatch, streaming):
    """Exercise actual HTTP query routes and shared logging, without AI/network calls."""
    import json
    from app.services import query

    client, db, project, _, key, _, _ = feedback
    # Start without the fixture's query logs so every dashboard record here
    # must have originated through a real public query request.
    db.execute(sa.delete(QueryLog))
    db.commit()

    class QueryDB:
        def scalar(self, *args, **kwargs):
            return 1  # Content-existence probes; retrieval below supplies content.

        def __getattr__(self, name):
            return getattr(db, name)

    monkeypatch.setattr(query.settings, "query_cache_enabled", True)
    monkeypatch.setattr(query.retrieval, "retrieve", lambda *a, **k: [
        {"filename": "guide.md", "page_number": None, "chunk_index": i,
         "content": "A useful fact.", "similarity": 0.8} for i in range(2)
    ])
    monkeypatch.setattr(query.memory_service, "search_memories", lambda *a, **k: [])
    monkeypatch.setattr(query.semantic_cache, "lookup", lambda *a, **k: (None, [0.1], None))
    monkeypatch.setattr(query.semantic_cache, "store", lambda *a, **k: None)
    monkeypatch.setattr(query.generation, "generate_answer", lambda *a, **k: "A useful answer.")
    monkeypatch.setattr(query.generation, "generate_answer_stream", lambda *a, **k: iter(["A useful answer."]))
    monkeypatch.setattr(rag_v1, "run_query", lambda _db, *a, **k: query.run_query(QueryDB(), *a, **k))
    monkeypatch.setattr(rag_v1, "run_query_stream", lambda _db, *a, **k: query.run_query_stream(QueryDB(), *a, **k))
    monkeypatch.setattr(rag_v1, "record_usage", lambda *a, **k: None)
    monkeypatch.setattr(rag_v1, "_maybe_judge", lambda *a, **k: None)

    def ask():
        response = client.post(f"/v1/projects/{project.id}/query" + ("/stream" if streaming else ""),
                               json={"question": "What does the guide say?"})
        assert response.status_code == 200, response.text
        if not streaming:
            return response.json()
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        return next(event["response"] for event in events if event["type"] == "done")

    first, cached = ask(), ask()
    assert first["query_id"] != cached["query_id"]
    assert cached["cache_layer"] == "l1"
    records = client.get("/api/account/queries").json()["items"]
    assert {item["id"] for item in records} == {first["query_id"], cached["query_id"]}
    assert all(row.api_key_id == key.id for row in db.scalars(sa.select(QueryLog)))
    path = f"/v1/projects/{project.id}/queries/{cached['query_id']}/feedback"
    assert client.put(path, json={"rating": "not_helpful"}).status_code == 200
    report = client.get("/api/account/knowledge-health").json()["projects"][0]
    assert report["total_queries"] == 2
    assert report["cached_queries"] == 1
    assert report["fresh_queries"] == report["measured_queries"] == 1
    assert report["avg_retrieval_similarity"] == pytest.approx(0.8)
    assert report["not_helpful_queries"] == 1
    assert report["helpful_queries"] == 0
    assert client.delete(path).status_code == 204
    assert client.get("/api/account/knowledge-health").json()["projects"][0]["not_helpful_queries"] == 0


@pytest.mark.parametrize("suffix", ["queries", "queries/{id}", "health"])
def test_public_reports_scope_auth_and_limits(feedback, monkeypatch, suffix):
    client, db, project, other, key, own, foreign = feedback
    base = f"/v1/projects/{project.id}"
    path = base + "/" + suffix.format(id=own.id)
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert "Private question" not in response.text and str(other.id) not in response.text
    assert client.get(path, headers={"Authorization": ""}).status_code == 401
    assert client.get(path.replace(str(project.id), str(other.id))).status_code == 401
    assert client.get(f"{base}/queries/{foreign.id}").status_code == 404
    project.suspended = True
    db.commit()
    assert client.get(path).status_code == 403
    project.suspended = False
    db.add(SuspendedAccount(owner_id=project.owner_id))
    db.commit()
    assert client.get(path).status_code == 403
    db.delete(db.get(SuspendedAccount, project.owner_id))
    key.revoked_at = datetime.now(timezone.utc)
    db.commit()
    assert client.get(path).status_code == 401
    key.revoked_at = None
    db.commit()
    monkeypatch.setattr(rate_limit.settings, "query_rate_per_minute_per_key", 0)
    response = client.get(path)
    assert response.status_code == 429 and "Retry-After" in response.headers


def test_public_history_filters_pagination_and_health_parity(feedback):
    client, db, project, _, _, own, _ = feedback
    base = f"/v1/projects/{project.id}"
    sibling = Project(owner_id=project.owner_id, name="Sibling private")
    db.add(sibling)
    db.flush()
    db.add(QueryLog(project_id=sibling.id, question="Sibling question"))
    test_query = QueryLog(project_id=project.id, question="Playground test 100%", cache_layer="l1", latency_ms=2000)
    db.add(test_query)
    db.commit()
    assert client.put(url(project, test_query), json={"rating": "helpful", "note": "Full feedback"}).status_code == 200
    first = client.get(base + "/queries", params={"limit": 1}).json()
    assert first["items"][0]["id"] == str(test_query.id)
    assert first["items"][0]["feedback_note"] is None
    second = client.get(base + "/queries", params={"limit": 1, "before": first["next_cursor"]}).json()
    assert [row["id"] for row in second["items"]] == [str(own.id)]
    assert second["next_cursor"] is None
    filtered = client.get(base + "/queries", params={"cache": "l1", "feedback": "helpful", "search": "100%", "min_latency_ms": 1000}).json()
    assert len(filtered["items"]) == 1
    detail = client.get(base + f"/queries/{test_query.id}").json()
    assert detail["feedback_note"] == "Full feedback"
    assert detail == client.get(f"/api/account/queries/{test_query.id}").json()
    for params in [{"days": 8}, {"days": 91}, {"limit": 101}, {"before": 0}, {"cache": "invalid"}, {"feedback": "bad"}, {"search": "x" * 201}]:
        assert client.get(base + "/queries", params=params).status_code == 422
    public = client.get(base + "/health").json()
    owner = client.get("/api/account/knowledge-health").json()
    assert len(public["projects"]) == 1
    assert public["projects"][0] == next(p for p in owner["projects"] if p["id"] == str(project.id))
    assert public["projects"][0]["helpful_queries"] == 1


def test_documented_monitoring_openapi_contract():
    app = FastAPI()
    app.include_router(rag_v1.router)
    schema = app.openapi()
    base = "/v1/projects/{project_id}"
    expected = {
        ("/queries", "get"): ("200", "QueryPage"),
        ("/queries/{query_id}", "get"): ("200", "QueryRecord"),
        ("/health", "get"): ("200", "KnowledgeHealth"),
        ("/queries/{query_id}/feedback", "put"): ("200", "FeedbackResponse"),
    }
    for (suffix, method), (status, model) in expected.items():
        operation = schema["paths"][base + suffix][method]
        assert operation["security"] == [{"HTTPBearer": []}]
        assert operation["responses"][status]["content"]["application/json"]["schema"]["$ref"].endswith("/" + model)
    listing = schema["paths"][base + "/queries"]["get"]
    assert {p["name"] for p in listing["parameters"] if p["in"] == "query"} == {
        "days", "search", "cache", "feedback", "min_latency_ms", "before", "limit",
    }
    feedback_schema = schema["components"]["schemas"]["FeedbackInput"]
    assert feedback_schema["required"] == ["rating"]
    assert feedback_schema["properties"]["note"]["maxLength"] == 1000
    assert feedback_schema["properties"]["rating"]["enum"] == ["helpful", "not_helpful"]
    assert feedback_schema["additionalProperties"] is False
    deletion = schema["paths"][base + "/queries/{query_id}/feedback"]["delete"]
    assert "content" not in deletion["responses"]["204"]
