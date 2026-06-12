"""One-off DB verification helper (run from backend/: python -m tests.verify_db).

Reads credentials from backend/.env — no secrets in this file.
"""
import sys

import psycopg

from app.config import settings


def plain_dsn() -> str:
    # SQLAlchemy URL -> plain libpq URL for psycopg.connect
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


conn = psycopg.connect(plain_dsn(), connect_timeout=15)
tables = [
    r[0]
    for r in conn.execute(
        "select tablename from pg_tables where schemaname='public' order by 1"
    )
]
buckets = [r[0] for r in conn.execute("select id from storage.buckets")]
vector = conn.execute(
    "select extversion from pg_extension where extname='vector'"
).fetchone()
rls = conn.execute(
    "select relname, relrowsecurity from pg_class c join pg_namespace n on n.oid=c.relnamespace "
    "where n.nspname='public' and relkind='r' order by 1"
).fetchall()
conn.close()

print("tables:", tables)
print("buckets:", buckets)
print("pgvector:", vector)
print("rls:", rls)

expected = {"api_keys", "chunks", "files", "projects", "query_logs"}
ok = expected.issubset(set(tables)) and "project-files" in buckets and vector
sys.exit(0 if ok else 1)
