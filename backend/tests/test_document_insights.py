"""Real SQL ownership, review-version safety and honest attribution coverage."""
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
from app.models import ApiKey, Base, DocumentReview, File, Project, QueryLog
from app.routers.knowledge_health import router
from app.services import document_insights as service

BASE = "/api/account/knowledge-health/documents"
NOW = datetime.now(timezone.utc)


@compiles(sa.BigInteger, "sqlite")
def bigint(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture()
def insights():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[Project.__table__, File.__table__, ApiKey.__table__, QueryLog.__table__, DocumentReview.__table__])
    with Session(engine) as db:
        mine = Project(owner_id=uuid.uuid4(), name="Mine")
        other = Project(owner_id=uuid.uuid4(), name="Other")
        db.add_all([mine, other]); db.commit()
        app = FastAPI(); app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: mine.owner_id
        with TestClient(app) as client:
            yield client, db, mine, other
    engine.dispose()


def file(db, project, **values):
    record = File(project_id=project.id, **{"filename": "policy.pdf", "storage_path": "PRIVATE_STORAGE",
        "status": "indexed", "chunk_count": 2, "indexed_at": NOW - timedelta(days=1),
        "content_sha256": "upload", "markdown_sha256": "markdown", **values})
    db.add(record); db.commit()
    return record


def query(db, project, sources=None, **values):
    record = QueryLog(project_id=project.id, question="PRIVATE_QUESTION", document_sources=sources,
        **{"created_at": NOW - timedelta(hours=1), **values})
    db.add(record); db.commit()
    return record


def get(client, project, **params):
    response = client.get(BASE, params={"project_id": str(project.id), **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_owner_scope_and_no_private_content(insights):
    client, db, mine, other = insights
    file(db, mine)
    foreign = file(db, other, filename="OTHER_SECRET.pdf")
    query(db, other, [{"file_id": str(foreign.id), "cited": True}])
    payload = get(client, mine)
    assert payload["total_documents"] == 1
    assert payload["query_count"] == 0
    assert "PRIVATE" not in str(payload) and "OTHER_SECRET" not in str(payload)
    assert client.get(BASE, params={"project_id": other.id}).status_code == 404
    assert client.put(f"{BASE}/{foreign.id}/review", json={"content_signature": service.content_signature(foreign)}).status_code == 404


def test_legacy_queries_remain_unmeasured_and_empty_tracking_is_zero(insights):
    client, db, mine, _ = insights
    doc = file(db, mine)
    query(db, mine)
    result = get(client, mine)
    assert result["tracked_queries"] == 0 and result["query_count"] == 1
    assert result["items"][0]["cited_answers"] is None
    query(db, mine, [])
    result = get(client, mine)
    assert result["tracked_queries"] == 1 and result["query_count"] == 2
    assert result["items"][0]["cited_answers"] == 0
    assert result["items"][0]["id"] == str(doc.id)


def test_citations_deduplicate_chunks_and_keep_same_name_documents_separate(insights):
    client, db, mine, _ = insights
    first, second = file(db, mine), file(db, mine)
    query(db, mine, [{"file_id": str(first.id), "cited": False}, {"file_id": str(first.id), "cited": True},
        {"file_id": str(second.id), "cited": False}], feedback_rating="helpful", cache_layer="l1")
    query(db, mine, [{"file_id": str(first.id), "cited": True}], feedback_rating="not_helpful", cache_layer="l2")
    result = get(client, mine)
    rows = {row["id"]: row for row in result["items"]}
    assert result["answers_with_citations"] == 2
    assert rows[str(first.id)]["included_queries"] == rows[str(first.id)]["cited_answers"] == 2
    assert rows[str(first.id)]["helpful"] == rows[str(first.id)]["not_helpful"] == 1
    assert rows[str(second.id)]["included_queries"] == 1
    assert rows[str(second.id)]["cited_answers"] == rows[str(second.id)]["helpful"] == 0


def test_current_versions_search_escaping_and_pagination(insights):
    client, db, mine, _ = insights
    file(db, mine, filename="retired.pdf", in_force_to=NOW.date())
    for index in range(23):
        file(db, mine, filename=f"doc-{index:02}.pdf")
    file(db, mine, filename="literal%name.pdf")
    first = get(client, mine)
    second = get(client, mine, offset=20)
    assert first["total_documents"] == first["matching_documents"] == 24
    assert len(first["items"]) == 20 and len(second["items"]) == 4
    assert not {row["id"] for row in first["items"]} & {row["id"] for row in second["items"]}
    assert get(client, mine, search="%name")["matching_documents"] == 1


def test_review_is_explicit_version_checked_and_does_not_change_content(insights):
    client, db, mine, _ = insights
    doc = file(db, mine)
    before = mine.content_version
    row = get(client, mine)["items"][0]
    assert row["freshness"] == "not_reviewed"  # recent indexing is not a review
    response = client.put(f"{BASE}/{doc.id}/review", json={"content_signature": row["content_signature"]})
    assert response.status_code == 200
    row = get(client, mine)["items"][0]
    assert row["freshness"] == "reviewed" and row["review_due_at"]
    assert db.get(DocumentReview, doc.id).reviewed_by == mine.owner_id
    assert mine.content_version == before and doc.chunk_count == 2
    doc.indexed_at = NOW; db.commit()
    assert get(client, mine)["items"][0]["freshness"] == "reviewed"  # identical text reindex
    doc.markdown_sha256 = "changed text"; db.commit()
    assert get(client, mine)["items"][0]["freshness"] == "changed"
    assert client.put(f"{BASE}/{doc.id}/review", json={"content_signature": row["content_signature"]}).status_code == 409


def test_due_and_unsearchable_reviews(insights):
    client, db, mine, _ = insights
    doc = file(db, mine)
    db.add(DocumentReview(file_id=doc.id, project_id=mine.id, content_signature=service.content_signature(doc),
        reviewed_at=NOW-timedelta(days=91), reviewed_by=mine.owner_id)); db.commit()
    assert get(client, mine)["items"][0]["freshness"] == "review_due"
    doc.status = "failed"; db.commit()
    assert get(client, mine)["items"][0]["freshness"] == "not_searchable"
    assert client.put(f"{BASE}/{doc.id}/review", json={"content_signature": service.content_signature(doc)}).status_code == 409


def test_window_cap_and_bad_telemetry(insights, monkeypatch):
    client, db, mine, _ = insights
    doc = file(db, mine)
    query(db, mine, [{"file_id": str(doc.id), "cited": True}], created_at=NOW-timedelta(days=91))
    query(db, mine, [{"file_id": str(doc.id), "cited": True}], created_at=NOW+timedelta(days=1))
    query(db, mine, [{"file_id": "invalid", "cited": True}])
    query(db, mine, [{"file_id": str(doc.id), "cited": "yes"}])
    assert get(client, mine)["tracked_queries"] == 0
    query(db, mine, [])
    monkeypatch.setattr(service, "SCAN_LIMIT", 2)
    result = get(client, mine)
    assert result["limited"] and result["query_count"] == 2
    assert client.get(BASE, params={"project_id": mine.id, "days": 1}).status_code == 422
    assert client.get(BASE, params={"project_id": mine.id, "offset": -1}).status_code == 422


def test_authentication_required(insights):
    client, db, mine, _ = insights
    doc = file(db, mine)
    client.app.dependency_overrides.pop(get_current_user)
    assert client.get(BASE, params={"project_id": mine.id}).status_code == 401
    assert client.put(f"{BASE}/{doc.id}/review", json={"content_signature": service.content_signature(doc)}).status_code == 401


def test_attribution_memory_legacy_and_duplicates():
    identity = str(uuid.uuid4())
    assert service.source_attribution([]) == []
    assert service.source_attribution([{"filename": "memory", "chunk_index": -1}]) == []
    assert service.source_attribution([{"filename": "legacy.pdf", "chunk_index": 0}]) is None
    assert service.source_attribution([{"filename": "memory", "chunk_index": 0}]) is None
    sources = [{"filename": "same.pdf", "file_id": identity, "cited": False},
        {"filename": "same.pdf", "file_id": identity, "cited": True}]
    assert service.source_attribution(sources) == [{"file_id": identity, "cited": True}]


@pytest.mark.parametrize("streaming", [False, True])
def test_fresh_and_cached_queries_record_the_same_document_identity(monkeypatch, streaming):
    from app.services import query as engine
    from tests.test_query import FakeDB, _project, _src
    doc_id = str(uuid.uuid4())
    source = {**_src("source", 0.99), "file_id": doc_id}
    monkeypatch.setattr(engine.retrieval, "retrieve", lambda *a, **kw: [source])
    monkeypatch.setattr(engine.semantic_cache, "lookup", lambda *a, **kw: (None, None, None))
    monkeypatch.setattr(engine.semantic_cache, "store", lambda *a, **kw: None)
    monkeypatch.setattr(engine.generation, "generate_answer", lambda *a, **kw: "An answer [1].")
    monkeypatch.setattr(engine.generation, "generate_answer_stream", lambda *a, **kw: iter(["An answer [1]."]))
    project = _project()
    for expected_layer in [None, "l1"]:
        db = FakeDB([10, 0])
        if streaming:
            events = list(engine.run_query_stream(db, project, "What is X?", None))
            assert events[-1]["type"] == "done"
        else:
            engine.run_query(db, project, "What is X?", None, None)
        log = next(row for row in db.added if isinstance(row, QueryLog))
        assert log.document_sources == [{"file_id": doc_id, "cited": True}]
        assert log.cache_layer == expected_layer
