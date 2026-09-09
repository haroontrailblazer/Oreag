"""Real SQL checks for ownership, document versions, duplicate scope and NULLs."""
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
from app.models import ApiKey, Base, File, Project, QueryLog
from app.routers.knowledge_health import router


@compiles(sa.BigInteger, "sqlite")
def _bigint(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture()
def health():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[Project.__table__, File.__table__, ApiKey.__table__, QueryLog.__table__])
    with Session(engine) as db:
        owner = uuid.uuid4()
        mine = Project(owner_id=owner, name="Mine")
        other = Project(owner_id=uuid.uuid4(), name="Other")
        db.add_all([mine, other])
        db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: owner
        with TestClient(app) as client:
            yield client, db, mine, other
    engine.dispose()


URL = "/api/account/knowledge-health"


def file(db, project, **values):
    values.setdefault("filename", "document.pdf")
    values.setdefault("storage_path", "private/path")
    row = File(project_id=project.id, **values)
    db.add(row)
    db.commit()
    return row


def query(db, project, **values):
    values.setdefault("created_at", datetime.now(timezone.utc))
    db.add(QueryLog(project_id=project.id, question="Private question", **values))
    db.commit()


def test_owner_isolation_and_empty_defaults(health):
    client, db, mine, other = health
    file(db, other, status="failed")
    query(db, other, retrieval_similarity=0.9)
    response = client.get(URL)
    assert response.status_code == 200, response.text
    rows = response.json()["projects"]
    assert len(rows) == 1 and rows[0]["id"] == str(mine.id)
    assert rows[0]["current_files"] == 0
    assert rows[0]["fresh_queries"] == 0
    assert rows[0]["avg_retrieval_similarity"] is None
    assert rows[0]["last_indexed_at"] is None
    assert "private" not in response.text.lower()
    assert "key_encrypted" not in response.text


def test_current_file_states_and_superseded_exclusion(health):
    client, db, mine, _ = health
    stamp = datetime.now(timezone.utc)
    file(db, mine, status="indexed", chunk_count=8, indexed_at=stamp)
    file(db, mine, status="indexed", chunk_count=0)
    for status in ["pending", "processing", "review", "failed", "future-status"]:
        file(db, mine, status=status)
    file(db, mine, status="failed", in_force_to=stamp.date(), chunk_count=50)
    result = client.get(URL).json()["projects"][0]
    assert result["current_files"] == 7
    assert result["searchable_files"] == 1 and result["indexed_chunks"] == 8
    assert result["indexing_files"] == 2
    assert result["failed_files"] == result["review_files"] == result["empty_indexed_files"] == result["unknown_files"] == 1
    assert result["last_indexed_at"] is not None


def test_duplicate_extra_copies_are_scoped_and_ignore_missing_hashes(health):
    client, db, mine, other = health
    for _ in range(3):
        file(db, mine, content_sha256="same")
    file(db, other, content_sha256="same")
    sibling = Project(owner_id=mine.owner_id, name="Sibling")
    db.add(sibling)
    db.commit()
    file(db, sibling, content_sha256="same")
    file(db, mine, content_sha256="same", in_force_to=datetime.now().date())
    for digest in [None, None, "", ""]:
        file(db, mine, content_sha256=digest)
    results = {row["id"]: row for row in client.get(URL).json()["projects"]}
    assert results[str(mine.id)]["duplicate_copies"] == 2
    assert results[str(sibling.id)]["duplicate_copies"] == 0


def test_retrieval_is_recent_uncached_and_preserves_unknown(health):
    client, db, mine, _ = health
    query(db, mine, retrieval_similarity=None)
    query(db, mine, retrieval_similarity=0.0)
    query(db, mine, retrieval_similarity=0.6)
    query(db, mine, cache_layer="l1", retrieval_similarity=1.0)
    query(db, mine, cache_layer="l2", retrieval_similarity=1.0)
    query(db, mine, retrieval_similarity=1.0, created_at=datetime.now(timezone.utc) - timedelta(days=31))
    result = client.get(URL).json()["projects"][0]
    assert result["fresh_queries"] == 3
    assert result["measured_queries"] == 2
    assert result["avg_retrieval_similarity"] == pytest.approx(0.3)


def test_all_unknown_measurements_remain_null(health):
    client, db, mine, _ = health
    query(db, mine, retrieval_similarity=None)
    result = client.get(URL).json()["projects"][0]
    assert result["fresh_queries"] == 1
    assert result["measured_queries"] == 0
    assert result["avg_retrieval_similarity"] is None


def test_constant_query_count_and_no_writes(health):
    client, db, mine, _ = health
    for i in range(12):
        db.add(Project(owner_id=mine.owner_id, name=f"Project {i}"))
    db.commit()
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())
    sa.event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        assert client.get(URL).status_code == 200
    finally:
        sa.event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert statements == ["SELECT"] * 4


def test_no_projects(health):
    client, db, mine, _ = health
    db.delete(mine)
    db.commit()
    assert client.get(URL).json()["projects"] == []


def test_authentication_required():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as client:
        assert client.get(URL).status_code in (401, 403)
