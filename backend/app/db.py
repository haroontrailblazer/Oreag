from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings


def _make_engine():
    if not settings.database_url:
        return None
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        # Explicit pool sizing (defaults are 5+10): sized against the request
        # threadpool so concurrent queries aren't capped at 15 connections, and
        # failing checkout fast (5s, not 30s) so overload surfaces as a quick
        # error instead of a pile-up of stalled threads.
        pool_size=10,
        max_overflow=30,
        pool_timeout=5,
        # Supabase's pooler (pgbouncer) does not support prepared statements
        connect_args={"prepare_threshold": None},
    )


engine = _make_engine()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
