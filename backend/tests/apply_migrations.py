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

current_file = [""]  # the migration being applied, for attributing a notice
notices: list[str] = []


def print_notice(diag) -> None:
    """Print every NOTICE / WARNING the server raises.

    Load-bearing, not decoration. The guarded migrations - 0018 above all - are
    written so that NOTHING raises: a missing table, an old pgvector, a
    cancelled index build, a role that may not index the table, all degrade to a
    RAISE NOTICE that names what was skipped and points at the runbook. psycopg3
    replaces libpq's default stderr notice processor with its own, and that one
    DISCARDS every notice while no handler is registered - so without this the
    runner printed "applied 0018_hnsw_vector_indexes.sql" and "OK" for a run
    that created zero indexes, and the operator had no way to tell.
    """
    severity = diag.severity_nonlocalized or diag.severity or "NOTICE"
    line = f"    [{current_file[0]}] {severity}: {diag.message_primary}"
    notices.append(line)
    print(line, flush=True)


conn = psycopg.connect(dsn, autocommit=True, connect_timeout=15)
conn.add_notice_handler(print_notice)
try:
    for sql_file in sorted(migrations_dir.glob("*.sql")):
        current_file[0] = sql_file.name
        try:
            conn.execute(sql_file.read_text(encoding="utf-8"))
            print(f"applied {sql_file.name}")
        except (psycopg.errors.DuplicateTable, psycopg.errors.DuplicateObject):
            # already applied (CREATE TABLE / CREATE POLICY are not idempotent)
            print(f"skipped {sql_file.name} (already applied)")
finally:
    conn.close()

if notices:
    # A skipped step is a SUCCESSFUL run of a defensive migration, so the exit
    # code cannot carry it - say it in words instead, right next to the OK.
    print(
        f"OK - migrations applied, with {len(notices)} server notice(s) above. "
        "Read them: a guarded migration reports everything it SKIPPED that way."
    )
else:
    print("OK - migrations applied")
sys.exit(0)
