"""Apply all supabase/migrations/*.sql in order (idempotent).

Run from backend/: python -m tests.apply_migrations
Reads MIGRATION_DATABASE_URL (else DATABASE_URL) from backend/.env. No secrets
in this file.
"""
import pathlib
import sys

import psycopg

from app.config import settings

# DDL belongs on the SESSION pooler (port 5432) when one is configured: the
# transaction pooler multiplexes statements across backends, so session state
# (SET maintenance_work_mem, advisory locks) does not survive. Falls back to
# DATABASE_URL so a single-URL setup keeps working unchanged.
dsn = (settings.migration_database_url or settings.database_url).replace(
    "postgresql+psycopg://", "postgresql://", 1
)
migrations_dir = pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations"

conn = psycopg.connect(dsn, autocommit=True, connect_timeout=15)
try:
    for sql_file in sorted(migrations_dir.glob("*.sql")):
        try:
            conn.execute(sql_file.read_text(encoding="utf-8"))
            print(f"applied {sql_file.name}")
        except (psycopg.errors.DuplicateTable, psycopg.errors.DuplicateObject):
            # already applied (CREATE TABLE / CREATE POLICY are not idempotent)
            print(f"skipped {sql_file.name} (already applied)")
finally:
    conn.close()

print("OK - migrations applied")
sys.exit(0)
