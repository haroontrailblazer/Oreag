from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from .config import settings


def _connect_args() -> dict:
    """libpq/psycopg options. Every value is valid on the direct host, the
    session pooler and the transaction pooler alike, so nothing here has to
    change when DATABASE_URL moves between them.
    """
    return {
        # NEVER remove this. Under the session pooler it was belt-and-braces;
        # under TRANSACTION pooling it is load-bearing, because a named prepared
        # statement is created on one server backend and the next transaction
        # can be routed to a different one - which surfaces intermittently under
        # load as 'prepared statement "_pg3_0" does not exist'.
        "prepare_threshold": None,
        # Without a connect timeout a pooler outage hangs a threadpool thread
        # indefinitely instead of erroring. Note a failed CONNECT raises
        # OperationalError, not PoolTimeoutError, so it does NOT reach the 503
        # handler in main.py - it is a 500.
        "connect_timeout": settings.db_connect_timeout,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }


def _make_engine():
    if not settings.database_url:
        return None
    if settings.db_use_null_pool:
        # Escape hatch for several Render instances or a separate ingest
        # service. Deliberately a separate branch: create_engine raises
        # TypeError if pool_size / max_overflow / pool_timeout / pool_recycle
        # are passed alongside NullPool. pool_pre_ping is pointless here too - a
        # brand new connection is alive by definition.
        return create_engine(
            settings.database_url,
            poolclass=NullPool,
            connect_args=_connect_args(),
        )
    return create_engine(
        settings.database_url,
        # Cheapest defense against the pooler recycling or restarting under us;
        # without it that arrives as "server closed the connection unexpectedly"
        # mid-query, which SQLAlchemy does not retry.
        pool_pre_ping=True,
        # Pool sizing lives in config so it can be aligned with Supavisor's
        # per-tenant Pool Size without a code deploy. Keep the total at or below
        # that number: connections above it do not fail, they queue INSIDE
        # Supavisor, where pool_timeout cannot see them - which would silently
        # destroy the fast-fail PoolTimeoutError -> 503 path in main.py.
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        # Drop sockets proactively, before Render's NAT or Supavisor's idle
        # handling kills them, so pool_pre_ping rarely has to catch a dead one.
        pool_recycle=settings.db_pool_recycle,
        connect_args=_connect_args(),
    )


engine = _make_engine()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
