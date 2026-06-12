from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings


def _make_engine():
    if not settings.database_url:
        return None
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
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
