"""Real SQL/API checks for grouping, tenant boundaries and durable triage."""
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
from app.models import ApiKey, Base, EvaluationRun, KnowledgeGapReview, Project, QueryLog
from app.routers.knowledge_gaps import router
from app.services import knowledge_gaps as service

URL = "/api/account/knowledge-gaps"


@compiles(sa.BigInteger, "sqlite")
def _bigint(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture()
def gaps():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool, connect_args={"check_same_thread": False})
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine, tables=[Project.__table__, ApiKey.__table__, QueryLog.__table__, EvaluationRun.__table__, KnowledgeGapReview.__table__])
    with Session(engine) as db:
        owner = uuid.uuid4()
        mine, other = Project(owner_id=owner, name="Mine"), Project(owner_id=uuid.uuid4(), name="Other")
        db.add_all([mine, other]); db.commit()
        app = FastAPI(); app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: owner
        with TestClient(app) as client:
            yield client, db, mine, other
    engine.dispose()


def query(db, project, question="How do I get a refund?", **values):
    values.setdefault("created_at", datetime.now(timezone.utc) - timedelta(seconds=1))
    values.setdefault("retrieval_similarity", 0.2)
    row = QueryLog(project_id=project.id, question=question, **values)
    db.add(row); db.commit()
    return row


def path(project, question="How do I get a refund?"):
    return f"{URL}/{project.id}/{service.question_key(question)}"


def review(client, endpoint, status="resolved", **overrides):
    item = client.get(endpoint).json()["item"]
    body = dict(status=status, note="Updated the refund guide", revision=item["revision"], evidence_version=item["evidence_version"])
    body.update(overrides)
    return client.put(endpoint, json=body)


def test_grouping_preserves_meaning_and_normalizes_only_wording():
    key = service.question_key
    assert key(" HOW do I get a refund?\n") == key("how  do I get a refund？！")
    assert key("cafe\u0301?") == key("café?")
    assert key("refund in 14 days?") != key("refund in 30 days?")
    assert key("can I cancel?") != key("can I not cancel?")
    assert key("a then b") != key("b then a")
    assert key("version 1.2") != key("version 12")
    assert key("C++ support?") != key("C support?")


def test_owner_isolation_on_list_detail_and_writes(gaps):
    client, db, mine, other = gaps
    query(db, mine)
    query(db, other, question="Other tenant secret", feedback_note="Private feedback")
    result = client.get(URL).json()
    assert len(result["items"]) == 1
    assert result["items"][0]["project_id"] == str(mine.id)
    assert "Other tenant secret" not in str(result)
    assert client.get(URL, params={"project_id": other.id}).status_code == 404
    endpoint = path(other, "Other tenant secret")
    assert client.get(endpoint).status_code == 404
    assert client.put(endpoint, json={"status": "resolved", "revision": 0, "evidence_version": "a" * 64}).status_code == 404
    assert db.scalar(sa.select(sa.func.count()).select_from(KnowledgeGapReview)) == 0


def test_project_scoped_recurrence_counts_and_overlapping_signals(gaps):
    client, db, mine, _ = gaps
    sibling = Project(owner_id=mine.owner_id, name="Sibling"); db.add(sibling); db.commit()
    query(db, mine, question="How do I get a refund?", feedback_rating="not_helpful")
    query(db, mine, question="  HOW do I get a refund  ? ", retrieval_similarity=0.8, feedback_rating="helpful")
    query(db, mine, retrieval_similarity=None)
    query(db, sibling)
    result = client.get(URL).json()
    assert len(result["items"]) == 2
    item = result["items"][0]
    assert item["query_count"] == 3 and item["flagged_count"] == 1
    assert item["weak_evidence_count"] == item["not_helpful_count"] == 1
    assert item["helpful_count"] == item["unmeasured_count"] == 1
    assert result["flagged_queries"] == 2
    assert len(client.get(URL, params={"recurring": "true"}).json()["items"]) == 1


def test_cached_and_unknown_similarity_do_not_flag_and_boundary_is_strict(gaps):
    client, db, mine, _ = gaps
    query(db, mine, "Unknown", retrieval_similarity=None)
    query(db, mine, "Cached", cache_layer="l2", retrieval_similarity=0.0)
    query(db, mine, "Boundary", retrieval_similarity=0.35)
    query(db, mine, "Zero", retrieval_similarity=0.0)
    query(db, mine, "Rated cache", cache_layer="l1", retrieval_similarity=None, feedback_rating="not_helpful")
    result = client.get(URL).json()
    assert {item["question"] for item in result["items"]} == {"Zero", "Rated cache"}
    cached = next(item for item in result["items"] if item["question"] == "Rated cache")
    assert cached["weak_evidence_count"] == 0


@pytest.mark.parametrize("question", [
    "hi", " HI! ", "Hello?!", "👋 hi 👋", "hey there", "Good\n morning!",
    "Thanks.", "thank you very much", "Bye!", "How are you?", "How’s it going?",
])
def test_conversation_without_negative_feedback_is_not_a_document_gap(gaps, question):
    client, db, mine, _ = gaps
    row = query(db, mine, question, retrieval_similarity=0.201)
    result = client.get(URL).json()
    assert result["scanned_queries"] == 1
    assert result["items"] == [] and result["flagged_queries"] == 0
    assert client.get(path(mine, question)).status_code == 404
    db.refresh(row)
    assert row.retrieval_similarity == 0.201 and row.question == question


def test_negative_feedback_on_a_greeting_still_needs_review(gaps):
    client, db, mine, _ = gaps
    query(db, mine, "hi", retrieval_similarity=0.201, feedback_rating="not_helpful")
    detail = client.get(path(mine, "hi")).json()
    assert detail["item"]["not_helpful_count"] == detail["item"]["flagged_count"] == 1
    assert detail["item"]["weak_evidence_count"] == 0
    assert detail["evidence"][0]["not_helpful"] and not detail["evidence"][0]["weak_evidence"]


@pytest.mark.parametrize("question", [
    "hey hi", "hey hiiiiiiiiiiiiii", "heeeeeeeey", "hell nah",
    "]08]-9j4\\=9j24-9ujg0okl3ref", "👋😂", "?!?", "heyyy, hello!!!",
    "heeeelloooo there", "HEY\nHIIII 👋", "hey bro", "hahahahaha", "loooool",
    "hell naaaah", "ok thanks", "just kidding",
])
def test_casual_variations_and_obvious_noise_do_not_create_document_gaps(gaps, question):
    client, db, mine, _ = gaps
    query(db, mine, question, retrieval_similarity=0.188)
    result = client.get(URL).json()
    assert result["scanned_queries"] == 1
    assert result["flagged_queries"] == 0 and result["items"] == []


@pytest.mark.parametrize("question", ["heeeeeeeey", "hey hiiiiiiiiiiiiii", "hell nah", "]08]-9j4\\=9j24-9ujg0okl3ref", "😂"])
def test_negative_feedback_is_preserved_even_for_casual_or_noisy_input(gaps, question):
    client, db, mine, _ = gaps
    query(db, mine, question, retrieval_similarity=0.188, feedback_rating="not_helpful")
    item = client.get(URL).json()["items"][0]
    assert item["not_helpful_count"] == item["flagged_count"] == 1
    assert item["weak_evidence_count"] == 0


@pytest.mark.parametrize("question", [
    "heyyy, how do refunds work?", "hey hi where is my order", "lol why did payment fail?",
    "hell nah that refund answer is incorrect", "hey SKU A1234 missing", "ERR_503",
    "a12b34c56d78", "123e4567-e89b-12d3-a456-426614174000", "C++", "1+1?",
    "https://example.com/a12?b=345", "x[0]=a12+b34", "What does ]08]-9j4 mean?",
    "订单退款", "hi 404", "greeting policy",
])
def test_casual_detection_preserves_real_questions_code_and_identifiers(gaps, question):
    client, db, mine, _ = gaps
    query(db, mine, question, retrieval_similarity=0.188)
    assert client.get(URL).json()["items"][0]["weak_evidence_count"] == 1


def test_old_casual_queries_drop_out_without_deleting_logs_or_creating_reviews(gaps):
    client, db, mine, _ = gaps
    for question in ["hey hi", "hey hiiiiiiiiiiiiii", "heeeeeeeey", "hell nah", "]08]-9j4\\=9j24-9ujg0okl3ref"]:
        query(db, mine, question, created_at=datetime.now(timezone.utc)-timedelta(minutes=5))
    result = client.get(URL).json()
    assert result["open_groups"] == result["flagged_queries"] == 0
    assert db.scalar(sa.select(sa.func.count()).select_from(QueryLog)) == 5
    assert db.scalar(sa.select(sa.func.count()).select_from(KnowledgeGapReview)) == 0


@pytest.mark.parametrize("question", [
    "Hi, how do refunds work?", "Hello\nWhere is my order?", "Thanks, but that is wrong",
    "What is HI?", "refund", "C++?", "Thank you policy", "Hi there, explain billing",
])
def test_substantive_questions_are_not_hidden_by_greeting_filter(gaps, question):
    client, db, mine, _ = gaps
    query(db, mine, question, retrieval_similarity=0.201)
    assert client.get(URL).json()["items"][0]["weak_evidence_count"] == 1


def test_reviewed_greetings_keep_history_without_reopening_for_low_similarity(gaps):
    client, db, mine, _ = gaps
    row = query(db, mine, "hi", feedback_rating="not_helpful")
    assert review(client, path(mine, "hi"), note="Correct greeting; no document needed").status_code == 200
    row.feedback_rating = None
    db.commit()
    query(db, mine, "hi", retrieval_similarity=0.201)
    assert client.get(URL).json()["items"] == []
    item = client.get(path(mine, "hi")).json()["item"]
    assert item["status"] == "resolved" and not item["reopened"]
    assert item["flagged_count"] == 0
    assert item["note"] == "Correct greeting; no document needed"
    query(db, mine, "hi", feedback_rating="not_helpful")
    assert client.get(path(mine, "hi")).json()["item"]["reopened"]


def test_windows_exclude_future_and_old_queries(gaps):
    client, db, mine, _ = gaps
    now = datetime.now(timezone.utc)
    query(db, mine, "Recent")
    query(db, mine, "Month", created_at=now - timedelta(days=10))
    query(db, mine, "Quarter", created_at=now - timedelta(days=50))
    query(db, mine, "Expired", created_at=now - timedelta(days=91))
    query(db, mine, "Future", created_at=now + timedelta(days=1))
    assert client.get(URL, params={"days": 7}).json()["matched_groups"] == 1
    assert client.get(URL).json()["matched_groups"] == 2
    assert client.get(URL, params={"days": 90}).json()["matched_groups"] == 3


def test_resolution_persists_across_windows_and_manual_reopen(gaps):
    client, db, mine, _ = gaps
    query(db, mine)
    response = review(client, path(mine))
    assert response.status_code == 200, response.text
    item = response.json()["item"]
    assert item["status"] == "resolved" and item["revision"] == 1
    assert item["note"] == "Updated the refund guide" and item["resolved_at"] is not None
    assert client.get(URL).json()["items"] == []
    assert client.get(URL, params={"status": "resolved", "days": 7}).json()["items"][0]["status"] == "resolved"
    reopened = review(client, path(mine), "open").json()["item"]
    assert reopened["status"] == "open" and reopened["revision"] == 2
    assert reopened["resolved_at"] is None


def test_new_flagged_query_reopens_but_healthy_traffic_does_not(gaps):
    client, db, mine, _ = gaps
    query(db, mine); assert review(client, path(mine)).status_code == 200
    query(db, mine, retrieval_similarity=0.9, feedback_rating="helpful")
    assert client.get(path(mine)).json()["item"]["status"] == "resolved"
    query(db, mine, cache_layer="l1", retrieval_similarity=None, feedback_rating="not_helpful")
    item = client.get(path(mine)).json()["item"]
    assert item["status"] == "open" and item["reopened"]
    assert item["note"] == "Updated the refund guide"
    assert review(client, path(mine)).json()["item"]["status"] == "resolved"


def test_negative_feedback_on_an_old_query_reopens(gaps):
    client, db, mine, _ = gaps
    row = query(db, mine)
    assert review(client, path(mine)).status_code == 200
    row.feedback_rating = "not_helpful"
    row.feedback_updated_at = datetime.now(timezone.utc)
    db.commit()
    assert client.get(path(mine)).json()["item"]["reopened"] is True


def test_stale_evidence_and_concurrent_review_are_rejected(gaps):
    client, db, mine, _ = gaps
    query(db, mine)
    item = client.get(path(mine)).json()["item"]
    query(db, mine)
    stale = {"status": "resolved", "revision": item["revision"], "evidence_version": item["evidence_version"]}
    assert client.put(path(mine), json=stale).status_code == 409
    assert db.scalar(sa.select(sa.func.count()).select_from(KnowledgeGapReview)) == 0
    item = client.get(path(mine)).json()["item"]
    assert review(client, path(mine)).status_code == 200
    stale["evidence_version"] = item["evidence_version"]
    assert client.put(path(mine), json=stale).status_code == 409
    assert client.get(path(mine)).json()["item"]["status"] == "resolved"


def test_feedback_removal_invalidates_snapshot_without_overwriting_feedback(gaps):
    client, db, mine, _ = gaps
    row = query(db, mine, feedback_rating="not_helpful", feedback_note="Bad source")
    item = client.get(path(mine)).json()["item"]
    row.feedback_rating = None; row.feedback_note = None; db.commit()
    response = client.put(path(mine), json={"status": "resolved", "revision": 0, "evidence_version": item["evidence_version"]})
    assert response.status_code == 409
    assert review(client, path(mine), note="Reviewed").status_code == 200
    db.refresh(row)
    assert row.feedback_rating is None and row.feedback_note is None
    assert row.question == "How do I get a refund?"


def test_bounded_history_and_evidence_pagination_use_bigint_strings(gaps, monkeypatch):
    client, db, mine, _ = gaps
    for i in range(5):
        query(db, mine, id=9_007_199_254_740_990 + i)
    monkeypatch.setattr(service, "SCAN_LIMIT", 3)
    result = client.get(URL).json()
    assert result["limited"] and result["scanned_queries"] == 3
    assert result["items"][0]["query_count"] == 3
    first = client.get(path(mine), params={"limit": 2}).json()
    assert first["limited"] and first["next_offset"] == 2
    assert first["evidence"][0]["id"] == "9007199254740994"
    second = client.get(path(mine), params={"limit": 2, "offset": 2}).json()
    assert len(second["evidence"]) == 1 and second["next_offset"] is None


def test_search_sort_and_list_pagination(gaps):
    client, db, mine, _ = gaps
    query(db, mine, "Refund alpha"); query(db, mine, "Refund alpha")
    query(db, mine, "Refund beta"); query(db, mine, "Unrelated")
    first = client.get(URL, params={"search": "REFUND", "limit": 1}).json()
    assert first["matched_groups"] == 2 and first["next_offset"] == 1
    assert first["items"][0]["question"] == "Refund alpha"
    second = client.get(URL, params={"search": "REFUND", "limit": 1, "offset": 1}).json()
    assert second["items"][0]["question"] == "Refund beta"
    assert client.get(URL, params={"search": "%_"}).json()["items"] == []


def test_retention_hides_groups_but_does_not_delete_review_state(gaps):
    client, db, mine, _ = gaps
    row = query(db, mine); assert review(client, path(mine)).status_code == 200
    db.delete(row); db.commit()
    assert client.get(URL, params={"status": "all"}).json()["items"] == []
    assert client.get(path(mine)).status_code == 404
    assert db.scalar(sa.select(sa.func.count()).select_from(KnowledgeGapReview)) == 1
    db.delete(mine); db.commit()
    assert db.scalar(sa.select(sa.func.count()).select_from(KnowledgeGapReview)) == 0


def test_reads_have_no_writes(gaps):
    client, db, mine, _ = gaps
    query(db, mine)
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())
    sa.event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        assert client.get(URL).status_code == 200
        assert client.get(path(mine)).status_code == 200
    finally:
        sa.event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert statements and set(statements) == {"SELECT"}


def test_validation_and_empty_results(gaps):
    client, db, mine, _ = gaps
    assert client.get(URL).json()["items"] == []
    for params in [{"days": 8}, {"status": "bad"}, {"offset": -1}, {"limit": 101}, {"search": "x" * 201}]:
        assert client.get(URL, params=params).status_code == 422
    query(db, mine)
    assert review(client, path(mine), note="x" * 2001).status_code == 422
    assert review(client, path(mine), note="bad\x00note").status_code == 422
    assert client.get(f"{URL}/{mine.id}/not-a-hash").status_code == 422


def test_authentication_required():
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as client:
        assert client.get(URL).status_code in (401, 403)
