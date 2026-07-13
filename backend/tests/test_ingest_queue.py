"""Durable ingestion queue: claim/lease/attempt-cap behavior.

Uses a fake session that mimics the two claim outcomes (a runnable candidate
or an empty queue) - the FOR UPDATE SKIP LOCKED concurrency is Postgres's job;
what's ours is the state machine around it.
"""
import threading
import uuid
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models import File
from app.services import ingest_queue


class _FakeScalars:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeDB:
    """Feeds claim_next a sequence of candidate rows (None = empty queue)."""

    def __init__(self, rows):
        self._rows = list(rows)
        self.commits = 0
        self.rollbacks = 0

    def scalars(self, stmt):
        return _FakeScalars(self._rows.pop(0) if self._rows else None)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _file(status="pending", attempts=0, lease=None):
    return File(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        filename="doc.pdf",
        storage_path="p/x.pdf",
        status=status,
        attempts=attempts,
        lease_expires_at=lease,
    )


class TestClaimNext:
    def test_empty_queue_returns_none(self):
        db = _FakeDB([])
        assert ingest_queue.claim_next(db) is None

    def test_claims_pending_file_with_lease_and_attempt(self):
        f = _file()
        db = _FakeDB([f])
        claimed = ingest_queue.claim_next(db)
        assert claimed == f.id
        assert f.status == "processing"
        assert f.attempts == 1
        assert f.lease_expires_at is not None
        assert f.lease_expires_at > datetime.now(timezone.utc)
        assert db.commits == 1

    def test_expired_lease_is_reclaimed(self):
        """A worker that died mid-file leaves status='processing' with a stale
        lease - the row must be claimable again, not lost."""
        stale = _file(
            status="processing",
            attempts=1,
            lease=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db = _FakeDB([stale])
        assert ingest_queue.claim_next(db) == stale.id
        assert stale.attempts == 2

    def test_attempt_cap_fails_the_file_and_moves_on(self, monkeypatch):
        """A poison file can't loop forever: past the cap it's failed (chunks
        dropped via mark_file_failed) and the next candidate is claimed."""
        poison = _file(attempts=settings.ingest_max_attempts)
        healthy = _file()
        db = _FakeDB([poison, healthy])
        failed: list[tuple] = []
        monkeypatch.setattr(
            ingest_queue,
            "mark_file_failed",
            lambda session, file_id, message: failed.append((file_id, message)),
        )
        claimed = ingest_queue.claim_next(db)
        assert claimed == healthy.id
        assert failed and failed[0][0] == poison.id
        assert "attempts" in failed[0][1]


class TestWorkerLoop:
    def test_worker_ingests_claimed_files_and_stops(self, monkeypatch):
        claimed_ids = [uuid.uuid4(), uuid.uuid4()]
        remaining = list(claimed_ids)
        ingested = []
        stop = threading.Event()

        monkeypatch.setattr(ingest_queue, "SessionLocal", lambda: _FakeDB([]))
        monkeypatch.setattr(
            ingest_queue,
            "claim_next",
            lambda db: remaining.pop(0) if remaining else stop.set() or None,
        )
        monkeypatch.setattr(ingest_queue, "ingest_file", ingested.append)

        ingest_queue.worker_loop(stop)
        assert ingested == claimed_ids

    def test_worker_survives_iteration_errors(self, monkeypatch):
        calls = {"n": 0}
        stop = threading.Event()

        def flaky_claim(db):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db blip")
            stop.set()
            return None

        monkeypatch.setattr(ingest_queue, "SessionLocal", lambda: _FakeDB([]))
        monkeypatch.setattr(ingest_queue, "claim_next", flaky_claim)
        monkeypatch.setattr(ingest_queue.settings, "ingest_poll_seconds", 0.01)

        ingest_queue.worker_loop(stop)  # must not raise
        assert calls["n"] == 2
