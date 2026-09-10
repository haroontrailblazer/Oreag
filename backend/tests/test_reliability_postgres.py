"""Real row-lock/unique-index races. Uses a disposable schema, never live data."""
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models import Base, Project, ApiKey, SuspendedAccount, IdempotencyRequest
from app.services import idempotency


@pytest.fixture
def postgres(monkeypatch):
    url = os.environ.get("RELIABILITY_DATABASE_URL")
    if not url:
        pytest.skip("Set RELIABILITY_DATABASE_URL to a disposable PostgreSQL database")
    schema = "reliability_" + uuid.uuid4().hex
    root = sa.create_engine(url)
    with root.begin() as c:
        c.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = sa.create_engine(url, connect_args={"options": f"-csearch_path={schema},public"})
    try:
        Base.metadata.create_all(engine, tables=[m.__table__ for m in (Project, ApiKey, SuspendedAccount, IdempotencyRequest)])
        monkeypatch.setattr(idempotency, "encrypt", lambda s: "fixture:" + s)
        monkeypatch.setattr(idempotency, "decrypt", lambda s: s.removeprefix("fixture:"))
        with Session(engine) as db:
            project = Project(owner_id=uuid.uuid4(), name="Isolated concurrency fixture")
            db.add(project); db.flush()
            key = ApiKey(project_id=project.id, key_hash="fixture", key_prefix="fixture")
            db.add(key); db.flush()
            ids = project.id, key.id
            db.commit()
        yield engine, ids
    finally:
        engine.dispose()
        # Only the randomly named schema created by this fixture is removed.
        with root.begin() as c:
            c.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        root.dispose()


def test_concurrent_claim_has_one_winner_and_survives_new_session(postgres):
    engine, (project, key) = postgres
    barrier = threading.Barrier(12)
    def attempt(_):
        with Session(engine) as db:
            barrier.wait(timeout=15)
            try:
                row, _ = idempotency.claim(db, project, key, "query", "same-request", "same-content")
                return row
            except HTTPException as exc:
                assert exc.status_code == 409
                return None
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(attempt, range(12)))
    winners = [r for r in results if r]
    assert len(winners) == 1
    # A worker process can disappear after claiming; a new session must not pay again.
    with Session(engine) as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(IdempotencyRequest)) == 1
        with pytest.raises(HTTPException) as error:
            idempotency.claim(db, project, key, "query", "same-request", "same-content")
        assert error.value.status_code == 409
        row = db.get(IdempotencyRequest, winners[0])
        row.status = "completed"
        row.status_code = 200
        row.response_encrypted = 'fixture:{"answer":"Original"}'
        db.commit()
    with Session(engine) as db:
        _, replay = idempotency.claim(db, project, key, "query", "same-request", "same-content")
        assert replay.status_code == 200 and b"Original" in replay.body


def test_expired_key_can_be_reused(postgres):
    engine, (project, key) = postgres
    with Session(engine) as db:
        first, _ = idempotency.claim(db, project, key, "query", "expired", "old")
        db.get(IdempotencyRequest, first).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        second, replay = idempotency.claim(db, project, key, "query", "expired", "new")
        assert second != first and replay is None
