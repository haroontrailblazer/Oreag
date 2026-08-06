"""Every table in `public` must have RLS enabled.

This exists because it was actually missed. Migration 0025 shipped
`memory_chunks` without RLS, and nothing caught it - not review, not the 568
passing tests, not the docs-sync harness. Supabase's own linter did, on the way
into the dashboard, which is the last place you want to be finding it.

The stake is higher for a DERIVED table than the omission looks. Every
memory_chunks row holds a verbatim copy of a slice of memories.content, so an
unprotected copy is a readable mirror of text the parent table gates carefully -
the derived table quietly becomes the way around the policy on the table it
derives from. The same argument applies to any future chunk/cache/shadow table,
which is exactly why this is a scan over all migrations rather than one
assertion about one table.

Note the backend connects with the service role and BYPASSES RLS entirely,
enforcing ownership in application code (see 0002_rls.sql). So none of these
policies are load-bearing for the app, and none of them will fail a test if
they are wrong - they are defence-in-depth against direct PostgREST/anon
access. Protection that is invisible when absent is precisely the kind that
needs a mechanical check.
"""
import pathlib
import re

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def _sql() -> str:
    """All migrations concatenated, with comments stripped.

    Comments are removed first so a table NAMED in prose (this file's own
    subject matter appears in several long headers) cannot satisfy - or trip -
    the scan. A test that passes because of a comment is worse than no test.
    """
    joined = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(MIGRATIONS.glob("*.sql"))
    )
    return re.sub(r"--[^\n]*", "", joined).lower()


def test_migrations_are_present():
    """Guards the guard: a wrong path would make every assertion below vacuous."""
    assert list(MIGRATIONS.glob("*.sql")), f"no migrations found at {MIGRATIONS}"


def test_every_public_table_enables_rls():
    sql = _sql()
    # `if not exists` is optional and the schema qualifier is sometimes omitted
    # (0016 creates unqualified tables), so both are tolerated on either side.
    created = set(
        re.findall(r"create table (?:if not exists )?(?:public\.)?(\w+)", sql)
    )
    protected = set(
        re.findall(r"alter table (?:public\.)?(\w+)\s+enable row level security", sql)
    )
    missing = sorted(created - protected)
    assert not missing, (
        "tables created without RLS: "
        + ", ".join(missing)
        + " - add `alter table public.<t> enable row level security;` and a policy "
        "in the same migration that creates it"
    )


def test_memory_chunks_policy_matches_its_siblings():
    """The specific regression. RLS ENABLED with no policy denies everything,
    which would look fine to the linter and to the app (service role bypasses
    it) while being a different posture from every sibling table."""
    sql = _sql()
    assert "enable row level security" in sql.split("memory_chunks", 1)[1][:2000]
    policy = re.search(
        r'create policy "owner full access" on public\.memory_chunks\s+'
        r"for all using \(exists \(select 1 from public\.projects p\s+"
        r"where p\.id = project_id and p\.owner_id = auth\.uid\(\)\)\)",
        sql,
    )
    assert policy, "memory_chunks needs the same owner policy as chunks/memories"
