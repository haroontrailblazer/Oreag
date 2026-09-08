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


def refresh_prices() -> None:
    """Pull the LLM price feed. Never raises - a stale price is not an outage.

    Rides this sweep rather than getting its own thread: the cadence that suits
    row pruning (hours) also suits vendor price changes, which move on the
    order of months.
    """
    try:
        from ..providers import pricing

        pricing.refresh()
    except Exception:
        logger.warning("Price refresh failed", exc_info=True)


def maintenance_loop(stop: threading.Event) -> None:
    # Once before the first wait, so a fresh process is not stuck on the
    # bundled snapshot for a whole interval.
    refresh_prices()
    while not stop.is_set():
        prune_old_rows()
        refresh_prices()
        stop.wait(settings.maintenance_interval_seconds)
