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
"""
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select

from ..config import settings
from ..db import SessionLocal
from ..models import File
from .ingestion import ingest_file, mark_file_failed

logger = logging.getLogger(__name__)


def claim_next(db) -> uuid.UUID | None:
    """Claim the oldest runnable file: status='pending', or 'processing' with
    an expired lease (its worker died). Returns the claimed id, or None when
    the queue is empty. Files past the attempt cap are failed permanently
    (with their partial chunks dropped) instead of claimed."""
    while True:
        now = datetime.now(timezone.utc)
        candidate = db.scalars(
            select(File)
            .where(
                or_(
                    File.status == "pending",
                    and_(
                        File.status == "processing",
                        File.lease_expires_at.isnot(None),
                        File.lease_expires_at < now,
                    ),
                )
            )
            .order_by(File.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
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
        candidate.status = "processing"
        candidate.attempts += 1
        candidate.lease_expires_at = now + timedelta(
            seconds=settings.ingest_lease_seconds
        )
        db.commit()
        return candidate.id


def worker_loop(stop: threading.Event) -> None:
    """One worker: claim -> ingest -> repeat; idle-poll when the queue is empty.

    Raw daemon threads, NOT the request threadpool - document conversion and
    embedding no longer steal threads from live query traffic.
    """
    logger.info("Ingest worker started")
    while not stop.is_set():
        file_id = None
        try:
            db = SessionLocal()
            try:
                file_id = claim_next(db)
            finally:
                db.close()
            if file_id is not None:
                ingest_file(file_id)
        except Exception:
            logger.exception("Ingest worker iteration failed")
        if file_id is None:
            # Empty queue (or an error): back off one poll interval. stop.wait
            # doubles as a fast shutdown signal.
            stop.wait(settings.ingest_poll_seconds)
    logger.info("Ingest worker stopped")


def start_workers(stop: threading.Event) -> list[threading.Thread]:
    workers = []
    for index in range(settings.ingest_worker_count):
        thread = threading.Thread(
            target=worker_loop,
            args=(stop,),
            name=f"ingest-worker-{index}",
            daemon=True,
        )
        thread.start()
        workers.append(thread)
    return workers
