import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.auth.jwt import get_current_user
from app.auth.api_keys import generate_api_key
from app.db import get_db
from app.evaluation_schemas import EvaluationConfig
from app.models import Base, Project, File, Chunk, MemoryChunk, EvaluationSuiteRecord, EvaluationRun, EvaluationVector, ApiKey, SuspendedAccount
from app.routers import evaluations
from app.routers.deps import heavy_dashboard_limit
from app.schemas import QueryResponse, SourceChunk
from app.services import evaluations as service


@compiles(sa.BigInteger, "sqlite")
def bigint(type_, compiler, **kw):
    return "INTEGER"


CONFIG = {"llm_provider": "openai", "llm_model": "gpt-4o-mini", "embedding_provider": "openai", "embedding_model": "text-embedding-3-small", "embedding_dimensions": 512, "top_k": 5}
SUITE = {"version": 2, "cases": [{"id": "q", "question": "What is the policy?", "expected": "30 days", "source": "policy.pdf"}], "variants": [CONFIG, {**CONFIG, "llm_model": "gpt-4o", "top_k": 10}]}


@pytest.fixture()
def app_data(monkeypatch):
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[x.__table__ for x in (Project, File, Chunk, MemoryChunk, EvaluationSuiteRecord, EvaluationRun, EvaluationVector, ApiKey, SuspendedAccount)])
    with Session(engine, expire_on_commit=False) as db:
        owner = uuid.uuid4()
        mine, other = Project(owner_id=owner, name="Mine"), Project(owner_id=uuid.uuid4(), name="Other")
        db.add_all([mine, other]); db.commit()
        file = File(project_id=mine.id, filename="policy.pdf", storage_path="private", status="indexed")
        db.add(file); db.commit()
        db.add(Chunk(project_id=mine.id, file_id=file.id, chunk_index=0, content="Return within 30 days.", embedding=[1, 0])); db.commit()
        app = FastAPI(); app.include_router(evaluations.router); app.include_router(evaluations.public_router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: owner
        app.dependency_overrides[heavy_dashboard_limit] = lambda: owner
        monkeypatch.setattr(service, "check_credentials", lambda *a: None)
        monkeypatch.setattr(service.resolver, "resolve_embedding_key", lambda *a: "test-key")
        monkeypatch.setattr(service, "record_usage", lambda *a, **k: None)
        monkeypatch.setattr(evaluations, "enforce_rate_limit", lambda *a, **k: None)
        class Embedder:
            def embed_texts(self, texts): return [[1.0] + [0.0] * 511 for _ in texts]
        monkeypatch.setattr(service, "get_embedder", lambda *a, **k: Embedder())
        with TestClient(app) as client:
            yield client, db, mine, other
    engine.dispose()


def base(project): return f"/api/projects/{project.id}/evaluations"
def start(client, project, suite=SUITE):
    response = client.post(base(project)+"/runs", json={"id": str(uuid.uuid4()), "suite": suite})
    assert response.status_code == 201, response.text
    return response.json()


def test_suite_ownership_revision_and_validation(app_data):
    c, db, mine, other = app_data
    assert c.get(base(other)+"/suite").status_code == 404
    assert c.get(base(mine)+"/suite").json()["revision"] == 0
    saved = c.put(base(mine)+"/suite", json={"revision": 0, "suite": SUITE})
    assert saved.status_code == 200
    assert c.get(base(mine)+"/suite").json()["suite"]["variants"][1]["llm_model"] == "gpt-4o"
    assert c.put(base(mine)+"/suite", json={"revision": 0, "suite": SUITE}).status_code == 409
    for patch in [{"embedding_dimensions": 7}, {"llm_model": "invented"}, {"top_k": 21}, {"min_similarity": -1}, {"answer_disclaimer": "bad\x00"}]:
        assert c.put(base(mine)+"/suite", json={"revision": 1, "suite": {**SUITE, "variants": [{**CONFIG, **patch}]}}).status_code == 422


def test_isolated_indexes_models_results_and_idempotency(app_data, monkeypatch):
    c, db, mine, other = app_data
    original = {column.key: getattr(mine, column.key) for column in Project.__table__.columns}
    writes = []
    def track(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().upper().startswith(("UPDATE", "INSERT", "DELETE")):
            writes.append(statement.lower())
    sa.event.listen(db.bind, "before_cursor_execute", track)
    run = start(c, mine)
    path = base(mine)+f"/runs/{run['id']}"
    assert c.get(base(other)+f"/runs/{run['id']}").status_code == 404
    assert c.post(base(mine)+"/runs", json={"id": run["id"], "suite": SUITE}).json()["id"] == run["id"]
    calls = []
    def query(db, project, question, top_k, **kwargs):
        assert kwargs["bypass_cache"] is True and callable(kwargs["retrieval_override"])
        assert kwargs["record_query"] is False
        assert sa.inspect(project, raiseerr=False) is None
        calls.append((project.llm_model, project.embedding_dimensions, top_k))
        return QueryResponse(answer="Return within 30 days.", sources=[SourceChunk(filename="policy.pdf", page_number=None, chunk_index=0, content="Policy", similarity=.9)], model=project.llm_model, latency_ms=1)
    monkeypatch.setattr(service, "run_query", query)
    for _ in range(4):
        response = c.post(path+"/advance")
        assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "completed", result
    assert len(result["results"]) == 2 and all(r["status"] == "passed" for r in result["results"])
    assert calls == [("gpt-4o-mini",512,5),("gpt-4o",512,10)]
    assert db.scalar(sa.select(sa.func.count()).select_from(EvaluationVector)) == 2
    assert c.post(path+"/advance").json()["results"] == result["results"]
    db.refresh(mine)
    assert {column.key: getattr(mine, column.key) for column in Project.__table__.columns} == original
    assert "corpus" not in result and "test-key" not in str(result)
    assert c.delete(path).status_code == 204
    assert db.scalar(sa.select(sa.func.count()).select_from(EvaluationVector)) == 0
    import re
    assert not any(re.search(r"(?:update|into|from)\s+(?:projects|files|chunks|memories|memory_chunks|query_logs|semantic_query_cache)\b", sql) for sql in writes)


def test_evaluation_feedback_is_persisted_only_inside_the_run(app_data):
    c, db, mine, other = app_data
    run = start(c, mine); rid = uuid.UUID(run["id"])
    url = base(mine)+f"/runs/{rid}/results/0/feedback"
    assert c.put(url, json={"rating":"helpful"}).status_code == 409
    row = db.get(EvaluationRun, rid)
    row.status = "completed"
    row.results = [{"caseId":"q","variant":0,"status":"passed","response":{"answer":"answer","sources":[]}}]
    db.commit()
    assert c.put(url.replace(str(mine.id), str(other.id)), json={"rating":"helpful"}).status_code == 404
    response = c.put(url, json={"rating":"not_helpful","note":"Missing detail"})
    assert response.status_code == 200, response.text
    saved = c.get(base(mine)+f"/runs/{rid}").json()["results"][0]
    assert saved["feedback_rating"] == "not_helpful" and saved["feedback_note"] == "Missing detail"
    assert c.delete(url).status_code == 204
    assert c.get(base(mine)+f"/runs/{rid}").json()["results"][0]["feedback_rating"] is None


def test_evaluation_language_caches_and_corpus_are_request_local(monkeypatch):
    from app.services import cross_lingual as cl, tracing
    from app.providers.base import TokenUsage
    project = Project(id=uuid.uuid4(), content_version=5, cross_lingual_floor=.2)
    monkeypatch.setattr(cl.settings, "cross_lingual_retrieval_enabled", True)
    answers = {"identify-corpus-language":"English", "translate-query":"Refund policy", "identify-question-language":"French"}
    monkeypatch.setattr(tracing, "observed_generate", lambda *a, **kw: (answers[kw["name"]], TokenUsage()))
    caches = [cl._corpus_cache, cl._language_cache, cl._translations, cl._question_languages]
    before = [dict(cache) for cache in caches]
    class DB:
        def execute(self, *a, **kw): raise AssertionError("Must profile the frozen snapshot, not live documents")
    class LLM:
        def generate_with_usage(self, *a): pass
    with cl.isolated_evaluation(["Our English refund policy."]):
        assert cl.corpus_profile(DB(), project)[1] == "Our English refund policy."
        assert cl.corpus_language(DB(), project, LLM()) == "English"
        assert cl.retrieval_query(DB(), project, "नीति क्या है?", rows=[{"similarity":0}], llm=LLM()) == "Refund policy"
        assert cl.answer_language_for(project, "Bonjour", [{"content":"नीति"}], llm=LLM()) == "French"
    assert [dict(cache) for cache in caches] == before
    assert cl._evaluation_caches.get() is None


def test_lease_stop_and_failed_resume(app_data, monkeypatch):
    c, db, mine, _ = app_data
    run = start(c, mine); path = base(mine)+f"/runs/{run['id']}"
    row = db.get(EvaluationRun, uuid.UUID(run["id"]))
    row.lease_until = datetime.now(timezone.utc) + timedelta(minutes=1); db.commit()
    assert c.post(path+"/advance").status_code == 409
    row.lease_until = None; db.commit()
    monkeypatch.setattr(service, "get_embedder", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret credential")))
    failed = c.post(path+"/advance").json()
    assert failed["status"] == "failed" and "secret credential" not in str(failed)
    assert c.post(path+"/resume").json()["status"] == "preparing"
    assert c.post(path+"/cancel").json()["status"] == "cancelled"
    assert c.post(path+"/advance").json()["prepared"] == 0
    assert c.post(path+"/resume").json()["status"] == "cancelled"


def test_provider_switch_drops_wrong_keys():
    project = Project(id=uuid.uuid4(), owner_id=uuid.uuid4(), llm_provider="anthropic", llm_model="claude-sonnet-4-6", embedding_provider="gemini", embedding_key_encrypted="gemini-secret", llm_key_encrypted="anthropic-secret")
    candidate = service.configured_project(project, EvaluationConfig(**CONFIG))
    assert candidate.embedding_key_encrypted is None and candidate.llm_key_encrypted is None
    assert project.embedding_key_encrypted == "gemini-secret"


def test_vector_shapes_and_nonfinite_are_rejected():
    for vectors in [[], [[1]], [[float('nan'),0]], [[float('inf'),0]], [[0,0]]]:
        with pytest.raises(ValueError): service.validate_vectors(vectors, 1, 2)


def test_public_key_scopes_and_no_owner_session(app_data):
    c, db, mine, other = app_data
    token, hashed, prefix = generate_api_key()
    db.add(ApiKey(project_id=mine.id, key_hash=hashed, key_prefix=prefix)); db.commit()
    url = f"/v1/projects/{mine.id}/evaluations/suite"
    assert c.get(url).status_code == 401
    c.app.dependency_overrides[get_current_user] = lambda: (_ for _ in ()).throw(AssertionError("public uses no JWT"))
    assert c.get(url, headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert c.get(f"/v1/projects/{other.id}/evaluations/suite", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    mine.suspended = True; db.commit()
    assert c.get(url, headers={"Authorization": f"Bearer {token}"}).status_code == 403
