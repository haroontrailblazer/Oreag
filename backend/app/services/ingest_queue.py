"""Durable ingestion queue - the files table IS the queue.

Before this, uploads scheduled ingestion via Starlette BackgroundTasks: the
queue lived in the web process's memory, competed with live queries for the
same request threadpool, and every deploy/restart/crash destroyed it - a boot
hook then bulk-failed all pending/processing files platform-wide, requiring
manual per-file retries.

Now upload routes just leave rows in status='pending'. Dedicated worker
threads (started in the app lifespan; a separate worker service can run the
same loop later) claim rows with FOR UPDATE SKIP LOCKED, take a lease, and
run the existing ingest_file. Interruption is recoverable by design:

  * a worker dying mid-file simply lets the lease expire - the claim query
    picks the row up again (attempts capped, so a poison file can't loop
    forever);
  * a restart loses nothing: pending rows are re-claimed within one poll
    interval, leased rows after their lease runs out.

Several instances may run this loop at once, so claims are INSTANCE-SCOPED.
"Expired lease" is the only signal that a file is up for grabs, and it says
nothing about who dropped it, so two things keep a live worker's file from
being stolen mid-ingest:

  * ``_ACTIVE`` - files this process is ingesting right now are excluded from
    its own claim query, so a second worker thread here can't re-claim a file
    the first is still working on (the claim transaction commits immediately;
    the row lock is long gone by the time ingestion finishes);
  * ``renew_lease`` - a heartbeat pushes the lease forward while ingestion
    runs, so a file that legitimately takes longer than one lease stays ours
    and other INSTANCES keep their hands off. Stop renewing (crash, deploy,
    OOM) and the lease lapses on its own - which is exactly the recovery path
    that already existed.
"""
import logging
import os
import random
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, update

from ..config import settings
from ..db import SessionLocal
from ..models import File
from .ingestion import ingest_file, mark_file_failed

logger = logging.getLogger(__name__)


def _instance_id() -> str:
    """Stable, human-readable id for THIS process.

    Queue activity across a fleet is otherwise unattributable: every instance
    logs the same "claimed file X" line. Render exposes RENDER_INSTANCE_ID,
    other hosts a hostname/dyno; the pid keeps two processes on one host
    apart.
    """
    host = (
        os.getenv("RENDER_INSTANCE_ID")
        or os.getenv("DYNO")
        or os.getenv("HOSTNAME")
        or socket.gethostname()
        or "local"
    )
    return f"{host[:24]}:{os.getpid()}"


INSTANCE_ID = _instance_id()

# file_id -> monotonic deadline. Files this process has claimed and not yet
# finished. Entries are pruned past one lease so a worker that died between the
# claim and the ingest can't wedge a file out of its own queue forever (the row
# itself is still protected by the DB lease).
_ACTIVE: dict[uuid.UUID, float] = {}
_ACTIVE_GUARD = threading.Lock()


def _register_claim(file_id: uuid.UUID) -> None:
    with _ACTIVE_GUARD:
        _ACTIVE[file_id] = time.monotonic() + settings.ingest_lease_seconds


def _release_claim(file_id: uuid.UUID) -> None:
    with _ACTIVE_GUARD:
        _ACTIVE.pop(file_id, None)


def active_file_ids() -> list[uuid.UUID]:
    """Files this instance is ingesting right now (expired entries dropped)."""
    now = time.monotonic()
    with _ACTIVE_GUARD:
        for file_id, deadline in list(_ACTIVE.items()):
            if deadline <= now:
                _ACTIVE.pop(file_id, None)
        return list(_ACTIVE)


def claim_next(db) -> uuid.UUID | None:
    """Claim the oldest runnable file: status='pending', or 'processing' with
    an expired lease (its worker died). Returns the claimed id, or None when
    the queue is empty. Files past the attempt cap are failed permanently
    (with their partial chunks dropped) instead of claimed.

    Files this instance is already ingesting are excluded in SQL: the claim
    commits straight away, so FOR UPDATE SKIP LOCKED stops protecting the row
    the moment ingestion actually starts."""
    while True:
        now = datetime.now(timezone.utc)
        stmt = select(File).where(
            or_(
                File.status == "pending",
                and_(
                    File.status == "processing",
                    File.lease_expires_at.isnot(None),
                    File.lease_expires_at < now,
                ),
            )
        )
        mine = active_file_ids()
        if mine:
            stmt = stmt.where(File.id.notin_(mine))
        candidate = db.scalars(
            stmt.order_by(File.created_at).limit(1).with_for_update(skip_locked=True)
        ).first()
        if candidate is None:
            return None
        if candidate.attempts >= settings.ingest_max_attempts:
            file_id = candidate.id
            db.rollback()  # release the row lock before the failure session
            mark_file_failed(
                db,
                file_id,
                f"Ingestion failed after {settings.ingest_max_attempts} attempts "
                "- retry from the Files tab",
            )
            continue  # look for the next runnable file
        if candidate.status == "processing":
            # Only reachable via an expired lease: some worker (here or on
            # another instance) dropped this file. Worth a line - it's the one
            # symptom of a crashed or wedged ingest.
            logger.warning(
                "Instance %s re-claiming file %s after a lapsed lease (attempt %s)",
                INSTANCE_ID,
                candidate.id,
                candidate.attempts + 1,
            )
        candidate.status = "processing"
        candidate.attempts += 1
        candidate.lease_expires_at = now + timedelta(
            seconds=settings.ingest_lease_seconds
        )
        db.commit()
        _register_claim(candidate.id)
        return candidate.id


def renew_lease(file_id: uuid.UUID) -> bool | None:
    """Push a claimed file's lease forward.

    Three outcomes, and they are NOT interchangeable:

      * ``True``  - renewed, the file is still ours;
      * ``False`` - the UPDATE matched nothing, so the row genuinely stopped
        being ours (finished, failed, deleted, or re-claimed elsewhere);
      * ``None``  - the renewal could not be attempted at all (a dropped
        pooler connection, a pool checkout timeout). That says nothing about
        ownership, so a caller must never read it as False - one database
        blip is not a hand-over.

    Scoped to status='processing' so a file that finished, failed or was
    deleted while we were mid-ingest is never resurrected by the heartbeat.
    Runs on its own short-lived session: the ingest holds one of its own, and
    these two must not share (or serialize on) a connection.
    """
    db = None
    try:
        # SessionLocal() is INSIDE the try: on a saturated pool the checkout
        # itself is what fails, and an exception escaping here would kill the
        # heartbeat thread outright - the very thing this function exists to
        # keep alive.
        db = SessionLocal()
        result = db.execute(
            update(File)
            .where(File.id == file_id, File.status == "processing")
            .values(
                lease_expires_at=datetime.now(timezone.utc)
                + timedelta(seconds=settings.ingest_lease_seconds)
            )
        )
        db.commit()
        return bool(result.rowcount)
    except Exception:
        logger.warning("Instance %s could not renew the lease on file %s",
                       INSTANCE_ID, file_id)
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass  # a dead connection is the pool's problem, not ours
        return None
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


# Floor on the heartbeat interval - a misconfigured (tiny) lease must not turn
# into an UPDATE-per-millisecond loop against the database.
_MIN_HEARTBEAT_SECONDS = 1.0

# Consecutive renewals that may fail before the heartbeat gives up. The
# interval is a third of the lease, so two failures still leave a third attempt
# inside the lease window; past that the lease has lapsed anyway and another
# instance may already own the row - renewing then would silently steal back a
# file someone else is ingesting.
_MAX_RENEWAL_FAILURES = 2


def _heartbeat_loop(file_id: uuid.UUID, stop: threading.Event) -> None:
    # A third of the lease: two renewals can fail before anyone else can
    # consider the file abandoned - and that budget is honoured below, because
    # one transient database error must not end the heartbeat for the whole
    # rest of the ingest (that is the exact failure this loop prevents).
    interval = max(settings.ingest_lease_seconds / 3.0, _MIN_HEARTBEAT_SECONDS)
    failures = 0
    while not stop.wait(interval):
        renewed = renew_lease(file_id)
        if renewed is False:
            return  # no longer ours - stop touching the row
        if renewed is None:
            failures += 1
            if failures > _MAX_RENEWAL_FAILURES:
                logger.warning(
                    "Instance %s gave up renewing the lease on file %s after "
                    "%s consecutive failures - the lease has lapsed",
                    INSTANCE_ID,
                    file_id,
                    failures,
                )
                return
            continue  # a blip, not a verdict: keep beating
        failures = 0
        _register_claim(file_id)  # keep the in-process guard in step with it


@contextmanager
def lease_heartbeat(file_id: uuid.UUID):
    """Keep ``file_id``'s lease fresh while THIS instance ingests it.

    Without this, an ingest slower than one lease (a long audio transcription,
    a throttled embedding provider) looks abandoned to every other instance
    and gets picked up a second time - duplicate chunks, duplicate spend, and
    the attempt cap burned on a file that was never actually failing.
    """
    stop = threading.Event()
    thread = threading.Thread(
        target=_heartbeat_loop,
        args=(file_id, stop),
        name=f"ingest-lease-{file_id}",
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5.0)


def worker_loop(stop: threading.Event) -> None:
    """One worker: claim -> ingest -> repeat; idle-poll when the queue is empty.

    Raw daemon threads, NOT the request threadpool - document conversion and
    embedding no longer steal threads from live query traffic.
    """
    logger.info("Ingest worker started on instance %s", INSTANCE_ID)
    while not stop.is_set():
        file_id = None
        try:
            db = SessionLocal()
            try:
                file_id = claim_next(db)
            finally:
                db.close()
            if file_id is not None:
                try:
                    # The lease is renewed for as long as we're actually
                    # working, so "expired" keeps meaning "abandoned".
                    with lease_heartbeat(file_id):
                        ingest_file(file_id)
                finally:
                    _release_claim(file_id)
        except Exception:
            logger.exception("Ingest worker iteration failed")
        if file_id is None:
            # Empty queue (or an error): back off one poll interval. stop.wait
            # doubles as a fast shutdown signal. Jittered so a fleet of
            # instances doesn't poll the database in lockstep after a deploy.
            stop.wait(settings.ingest_poll_seconds * random.uniform(0.8, 1.2))
    logger.info("Ingest worker stopped on instance %s", INSTANCE_ID)


def start_workers(stop: threading.Event) -> list[threading.Thread]:
    workers = []
    for index in range(settings.ingest_worker_count):
        thread = threading.Thread(
            target=worker_loop,
            args=(stop,),
            name=f"ingest-worker-{INSTANCE_ID}-{index}",
            daemon=True,
        )
        thread.start()
        workers.append(thread)
    return workers
