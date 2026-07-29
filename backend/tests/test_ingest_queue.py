"""Durable ingestion queue: claim/lease/attempt-cap behavior, and the
instance scoping that lets several instances run the loop at once.

Uses a fake session that mimics the two claim outcomes (a runnable candidate
or an empty queue) - the FOR UPDATE SKIP LOCKED concurrency is Postgres's job;
what's ours is the state machine around it. The instance-scoping tests assert
on the emitted statement, since "which rows this instance excludes" is a
property of the SQL, not of the fake.
"""
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.models import File
from app.services import ingest_queue


@pytest.fixture(autouse=True)
def _clear_active_claims():
    """_ACTIVE is module state: one test's claim must not leak into the next."""
    ingest_queue._ACTIVE.clear()
    yield
    ingest_queue._ACTIVE.clear()


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
        self.statements = []

    def scalars(self, stmt):
        self.statements.append(stmt)
        return _FakeScalars(self._rows.pop(0) if self._rows else None)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class _FakeResult:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class _FakeUpdateDB:
    """Session stand-in for renew_lease: records the UPDATE it was given."""

    def __init__(self, rowcount=1, explode=False):
        self._rowcount = rowcount
        self._explode = explode
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def execute(self, stmt):
        self.statements.append(stmt)
        if self._explode:
            raise RuntimeError("connection reset")
        return _FakeResult(self._rowcount)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


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

    def test_worker_releases_its_claim_even_when_the_ingest_explodes(
        self, monkeypatch
    ):
        """A crashed ingest must not leave the file wedged out of this
        instance's own queue - only the DB lease should decide."""
        stop = threading.Event()
        pending = [uuid.uuid4()]

        def claim(db):
            if pending:
                claimed = pending.pop(0)
                ingest_queue._register_claim(claimed)  # as the real claim does
                return claimed
            stop.set()
            return None

        monkeypatch.setattr(ingest_queue, "SessionLocal", lambda: _FakeDB([]))
        monkeypatch.setattr(ingest_queue, "claim_next", claim)
        monkeypatch.setattr(ingest_queue, "ingest_file", _explode)
        monkeypatch.setattr(ingest_queue.settings, "ingest_poll_seconds", 0.01)

        ingest_queue.worker_loop(stop)
        assert ingest_queue.active_file_ids() == []

    def test_worker_keeps_the_lease_fresh_while_the_ingest_runs(self, monkeypatch):
        """The renewal has to happen DURING ingestion - that's the whole point:
        a file slower than one lease must not look abandoned to another
        instance."""
        stop = threading.Event()
        file_id = uuid.uuid4()
        pending = [file_id]
        renewals = []
        monkeypatch.setattr(ingest_queue, "_MIN_HEARTBEAT_SECONDS", 0.01)
        monkeypatch.setattr(ingest_queue.settings, "ingest_lease_seconds", 0.03)
        monkeypatch.setattr(ingest_queue.settings, "ingest_poll_seconds", 0.01)
        monkeypatch.setattr(
            ingest_queue, "renew_lease", lambda fid: renewals.append(fid) or True
        )

        def claim(db):
            if pending:
                return pending.pop(0)
            stop.set()
            return None

        def slow_ingest(fid):
            time.sleep(0.1)  # longer than the (shrunken) heartbeat interval

        monkeypatch.setattr(ingest_queue, "SessionLocal", lambda: _FakeDB([]))
        monkeypatch.setattr(ingest_queue, "claim_next", claim)
        monkeypatch.setattr(ingest_queue, "ingest_file", slow_ingest)

        ingest_queue.worker_loop(stop)
        assert renewals and set(renewals) == {file_id}


def _explode(file_id):
    raise RuntimeError("ingest exploded")


class TestInstanceScopedClaims:
    """Several instances share this queue. FOR UPDATE SKIP LOCKED only covers
    the claim transaction, which commits immediately - so what keeps a file
    from being grabbed twice while it is actually being ingested is the
    in-process active set (same instance) plus the renewed lease (others)."""

    def test_claiming_marks_the_file_as_in_flight_here(self):
        db = _FakeDB([_file()])
        claimed = ingest_queue.claim_next(db)
        assert ingest_queue.active_file_ids() == [claimed]

    def test_files_this_instance_is_ingesting_are_excluded_from_its_claim(self):
        in_flight = uuid.uuid4()
        ingest_queue._register_claim(in_flight)
        db = _FakeDB([_file()])
        ingest_queue.claim_next(db)
        statement = db.statements[0]
        assert "NOT IN" in str(statement).upper()
        assert [in_flight] in statement.compile().params.values()

    def test_no_exclusion_clause_when_nothing_is_in_flight(self):
        db = _FakeDB([_file()])
        ingest_queue.claim_next(db)
        assert "NOT IN" not in str(db.statements[0]).upper()

    def test_a_live_lease_keeps_another_instances_file_out_of_the_claim(self):
        """_ACTIVE only covers THIS process. What stops us taking a file
        another instance is mid-ingest on is the lease predicate: a
        'processing' row is a candidate only once its lease is in the past."""
        db = _FakeDB([_file()])
        before = datetime.now(timezone.utc)
        ingest_queue.claim_next(db)
        params = db.statements[0].compile().params

        assert params["status_1"] == "pending"
        assert params["status_2"] == "processing"
        # The cutoff is "now", so a lease renewed into the future never matches
        # and a heartbeating instance keeps its file.
        cutoff = params["lease_expires_at_1"]
        assert before <= cutoff <= datetime.now(timezone.utc)
        sql = str(db.statements[0]).upper()
        assert "LEASE_EXPIRES_AT IS NOT NULL" in sql  # never a NULL-lease grab
        assert "LEASE_EXPIRES_AT <" in sql

    def test_the_claim_skips_rows_another_instance_has_locked(self):
        """Two instances polling the same queue must not queue up behind one
        another on the oldest row: SKIP LOCKED makes the loser take the next
        file instead of blocking."""
        db = _FakeDB([_file()])
        ingest_queue.claim_next(db)
        for_update = db.statements[0]._for_update_arg
        assert for_update is not None
        assert for_update.skip_locked is True

    def test_in_flight_entries_expire_so_a_lost_worker_cannot_wedge_a_file(
        self, monkeypatch
    ):
        monkeypatch.setattr(ingest_queue.settings, "ingest_lease_seconds", 0)
        ingest_queue._register_claim(uuid.uuid4())
        assert ingest_queue.active_file_ids() == []

    def test_releasing_a_claim_lets_the_file_be_claimed_again(self):
        db = _FakeDB([_file()])
        claimed = ingest_queue.claim_next(db)
        ingest_queue._release_claim(claimed)
        assert ingest_queue.active_file_ids() == []

    def test_instance_id_prefers_the_platform_identifier(self, monkeypatch):
        monkeypatch.setenv("RENDER_INSTANCE_ID", "srv-abc123")
        assert ingest_queue._instance_id() == f"srv-abc123:{os.getpid()}"

    def test_instance_id_falls_back_to_the_host_and_pid(self, monkeypatch):
        monkeypatch.delenv("RENDER_INSTANCE_ID", raising=False)
        monkeypatch.delenv("DYNO", raising=False)
        monkeypatch.delenv("HOSTNAME", raising=False)
        assert ingest_queue._instance_id().endswith(f":{os.getpid()}")
        assert str(os.getpid()) in ingest_queue.INSTANCE_ID


class TestRenewLease:
    def test_renewal_pushes_the_lease_forward_for_a_processing_row(
        self, monkeypatch
    ):
        db = _FakeUpdateDB(rowcount=1)
        monkeypatch.setattr(ingest_queue, "SessionLocal", lambda: db)
        assert ingest_queue.renew_lease(uuid.uuid4()) is True
        params = db.statements[0].compile().params
        # Scoped to 'processing': a file that finished or failed mid-ingest
        # must never be resurrected by its own heartbeat.
        assert params["status_1"] == "processing"
        assert params["lease_expires_at"] > datetime.now(timezone.utc)
        assert db.commits == 1
        assert db.closed

    def test_renewal_reports_false_when_the_row_is_no_longer_ours(self, monkeypatch):
        db = _FakeUpdateDB(rowcount=0)
        monkeypatch.setattr(ingest_queue, "SessionLocal", lambda: db)
        assert ingest_queue.renew_lease(uuid.uuid4()) is False

    def test_a_database_blip_never_breaks_the_ingest(self, monkeypatch):
        """A blip reports None, NOT False. False is a verdict ('the row stopped
        being ours') and ends the heartbeat; a dropped connection says nothing
        about ownership and must stay distinguishable from it."""
        db = _FakeUpdateDB(explode=True)
        monkeypatch.setattr(ingest_queue, "SessionLocal", lambda: db)
        assert ingest_queue.renew_lease(uuid.uuid4()) is None  # not an exception
        assert db.rollbacks == 1
        assert db.closed

    def test_a_failed_session_checkout_is_a_blip_too(self, monkeypatch):
        """The pool can be the thing that fails: under saturation the CHECKOUT
        raises, not the UPDATE. That must still be a None, not an exception
        escaping into (and ending) the heartbeat thread."""

        def _no_connection():
            raise RuntimeError("QueuePool limit reached")

        monkeypatch.setattr(ingest_queue, "SessionLocal", _no_connection)
        assert ingest_queue.renew_lease(uuid.uuid4()) is None


class TestLeaseHeartbeat:
    def _fast(self, monkeypatch):
        monkeypatch.setattr(ingest_queue, "_MIN_HEARTBEAT_SECONDS", 0.01)
        monkeypatch.setattr(ingest_queue.settings, "ingest_lease_seconds", 0.03)

    def test_renews_repeatedly_while_held_and_stops_on_exit(self, monkeypatch):
        self._fast(monkeypatch)
        renewals = []
        monkeypatch.setattr(
            ingest_queue, "renew_lease", lambda fid: renewals.append(fid) or True
        )
        file_id = uuid.uuid4()

        with ingest_queue.lease_heartbeat(file_id):
            time.sleep(0.1)
        settled = len(renewals)

        assert settled >= 2
        assert set(renewals) == {file_id}
        time.sleep(0.05)
        assert len(renewals) == settled  # the thread really stopped

    def test_gives_up_as_soon_as_the_file_stops_being_ours(self, monkeypatch):
        self._fast(monkeypatch)
        renewals = []

        def refuse(file_id):
            renewals.append(file_id)
            return False

        monkeypatch.setattr(ingest_queue, "renew_lease", refuse)

        with ingest_queue.lease_heartbeat(uuid.uuid4()):
            time.sleep(0.1)

        assert len(renewals) == 1  # one refusal is enough - no retry storm

    def test_a_blip_then_recovery_keeps_the_heartbeat_beating(self, monkeypatch):
        """The failure this whole loop exists to prevent: ONE transient
        database error used to end the heartbeat for the rest of the ingest,
        so a long file lapsed its lease and was re-claimed (and re-ingested)
        by another instance while it was still running here."""
        monkeypatch.setattr(ingest_queue, "_MIN_HEARTBEAT_SECONDS", 0.01)
        monkeypatch.setattr(ingest_queue.settings, "ingest_lease_seconds", 0.09)
        attempts = []

        def blip_once(file_id):
            attempts.append(file_id)
            return None if len(attempts) == 1 else True  # healthy afterwards

        monkeypatch.setattr(ingest_queue, "renew_lease", blip_once)
        file_id = uuid.uuid4()

        with ingest_queue.lease_heartbeat(file_id):
            time.sleep(0.2)
            # the in-process guard is refreshed again too, so both protections
            # survive the blip together
            assert ingest_queue.active_file_ids() == [file_id]

        assert len(attempts) >= 3  # kept beating instead of exiting on the blip

    def test_gives_up_once_the_failure_budget_is_exhausted(self, monkeypatch):
        """Unbounded retrying is wrong too: after three consecutive failures
        the lease (three heartbeat intervals long) has lapsed, and another
        instance may already own the row - renewing then would steal it back."""
        self._fast(monkeypatch)
        attempts = []

        def always_blip(file_id):
            attempts.append(file_id)
            return None

        monkeypatch.setattr(ingest_queue, "renew_lease", always_blip)

        with ingest_queue.lease_heartbeat(uuid.uuid4()):
            time.sleep(0.15)

        assert len(attempts) == ingest_queue._MAX_RENEWAL_FAILURES + 1

    def test_a_renewal_keeps_the_in_flight_marker_alive_too(self, monkeypatch):
        """The in-process guard and the DB lease must expire together, or the
        guard would lapse while this instance is still ingesting."""
        monkeypatch.setattr(ingest_queue, "_MIN_HEARTBEAT_SECONDS", 0.01)
        monkeypatch.setattr(ingest_queue.settings, "ingest_lease_seconds", 0.09)
        monkeypatch.setattr(ingest_queue, "renew_lease", lambda fid: True)
        file_id = uuid.uuid4()
        ingest_queue._register_claim(file_id)  # marker good for 0.09s from here

        with ingest_queue.lease_heartbeat(file_id):
            time.sleep(0.12)  # past that, so only a refresh can keep it alive
            assert ingest_queue.active_file_ids() == [file_id]
