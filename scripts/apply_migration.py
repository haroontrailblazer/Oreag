#!/usr/bin/env python3
"""Apply one numbered migration from supabase/migrations to the database.

Until now migrations were pasted into the Supabase SQL editor by hand, which
works but leaves no record of WHICH ones ran - and the answer drifted (0027 was
believed unapplied for a while when it had in fact been run). This applies a
single file inside one transaction and reports what changed.

    python scripts/apply_migration.py 0028              # show the SQL only
    python scripts/apply_migration.py 0028 --apply      # run it

The connection comes from backend/.env's DATABASE_URL, the same one the API
uses, so there is no second place for the credential to live. Every migration
in this repo is written to be re-runnable (`if not exists`, `or replace`), so
applying one twice is safe - but --apply is still opt-in rather than default.
"""
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "supabase" / "migrations"


def load_database_url() -> str:
    env = ROOT / "backend" / ".env"
    if not env.exists():
        sys.exit(f"No {env} - cannot find DATABASE_URL.")
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            url = line.split("=", 1)[1].strip().strip('"').strip("'")
            # psycopg3 driver, matching what the backend actually connects with.
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
    sys.exit("DATABASE_URL is not set in backend/.env")


def find(prefix: str) -> pathlib.Path:
    matches = sorted(MIGRATIONS.glob(f"{prefix}*.sql"))
    if not matches:
        sys.exit(f"No migration starting with {prefix} in {MIGRATIONS}")
    if len(matches) > 1:
        sys.exit(f"{prefix} is ambiguous: {[m.name for m in matches]}")
    return matches[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix", help="migration number, e.g. 0028")
    ap.add_argument("--apply", action="store_true", help="actually run it")
    args = ap.parse_args()

    path = find(args.prefix)
    sql = path.read_text(encoding="utf-8")
    print(f"--- {path.name} ---")
    print(sql)

    if not args.apply:
        print("Dry run. Re-run with --apply to execute.")
        return

    sys.path.insert(0, str(ROOT / "backend"))
    import sqlalchemy as sa

    engine = sa.create_engine(load_database_url())
    # One transaction: a migration that fails halfway must leave nothing
    # behind, or the next run starts from a state no file describes.
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)
    print(f"Applied {path.name}")


if __name__ == "__main__":
    main()
