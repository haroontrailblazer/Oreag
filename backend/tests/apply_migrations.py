"""Apply all supabase/migrations/*.sql in order (idempotent).

Run from backend/: python -m tests.apply_migrations
Reads DATABASE_URL from backend/.env. No secrets in this file.
"""
import pathlib
import sys

import psycopg

from app.config import settings

dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
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

print("OK — migrations applied")
sys.exit(0)
