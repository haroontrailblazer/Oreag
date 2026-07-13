"""Periodic housekeeping: retention pruning for append-only tables.

query_logs and usage_events grow monotonically (one row per request - the
dashboard re-aggregates query_logs on every load, so unbounded growth means a
forever-slowing dashboard), and semantic_query_cache rows previously expired
only when the SAME project's next fresh question happened to trigger a lazy
purge - idle projects accumulated dead vectors indefinitely.

One daemon thread (started in the app lifespan) sweeps every few hours.
"""
import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete as sql_delete
from sqlalchemy import text as sql_text

from ..config import settings
from ..db import SessionLocal
from ..models import QueryLog, UsageEvent

logger = logging.getLogger(__name__)


def prune_old_rows() -> None:
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=settings.log_retention_days
        )
        logs = db.execute(sql_delete(QueryLog).where(QueryLog.created_at < cutoff))
        events = db.execute(sql_delete(UsageEvent).where(UsageEvent.created_at < cutoff))
        expired = db.execute(
            sql_text("DELETE FROM semantic_query_cache WHERE expires_at <= now()")
        )
        db.commit()
        logger.info(
            "Retention sweep: %d query_logs, %d usage_events, %d expired cache rows",
            logs.rowcount,
            events.rowcount,
            expired.rowcount,
        )
    except Exception:
        logger.exception("Retention sweep failed")
        db.rollback()
    finally:
        db.close()


def maintenance_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        prune_old_rows()
        stop.wait(settings.maintenance_interval_seconds)
