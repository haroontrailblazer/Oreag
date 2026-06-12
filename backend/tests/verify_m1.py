"""M1 verification: Supabase auth -> JWT -> FastAPI project CRUD.

Run with the backend serving on :8000 (run from backend/: python -m tests.verify_m1).
Seeds throwaway users directly in auth.users (avoids the e-mail rate limit),
signs in via the password grant, and exercises the dashboard API.
"""
import secrets
import sys

import httpx
import psycopg

from app.config import settings

SUPABASE_URL = settings.supabase_url
ANON_KEY = settings.supabase_anon_key
DSN = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
API = "http://localhost:8000"

ok = True


def check(label: str, condition: bool, extra: str = ""):
    global ok
    print(("PASS" if condition else "FAIL"), label, extra)
    ok = ok and condition


def seed_user(email: str, password: str) -> None:
    """Insert a confirmed user the way GoTrue expects (no e-mail involved)."""
    with psycopg.connect(DSN, autocommit=True) as conn:
        row = conn.execute(
            """
            insert into auth.users (
                instance_id, id, aud, role, email, encrypted_password,
                email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
                created_at, updated_at, confirmation_token, recovery_token,
                email_change, email_change_token_new, email_change_token_current
            ) values (
                '00000000-0000-0000-0000-000000000000', gen_random_uuid(),
                'authenticated', 'authenticated', %s,
                extensions.crypt(%s, extensions.gen_salt('bf')), now(),
                '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb,
                now(), now(), '', '', '', '', ''
            ) returning id
            """,
            (email, password),
        ).fetchone()
        uid = str(row[0])
        conn.execute(
            """
            insert into auth.identities (
                id, user_id, provider_id, identity_data, provider,
                last_sign_in_at, created_at, updated_at
            ) values (
                gen_random_uuid(), %s, %s,
                jsonb_build_object('sub', %s::text, 'email', %s::text, 'email_verified', true),
                'email', now(), now(), now()
            )
            """,
            (uid, uid, uid, email),
        )


def sign_in(email: str, password: str) -> str:
    r = httpx.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        json={"email": email, "password": password},
        headers={"apikey": ANON_KEY},
        timeout=30,
    )
    check(f"sign-in {email}", r.status_code == 200, f"({r.status_code}) {r.text[:200]}")
    return r.json().get("access_token", "")


PASSWORD = "Oreag-test-" + secrets.token_hex(8)
EMAIL = f"oreag-test-{secrets.token_hex(4)}@closefuture.io"
EMAIL2 = f"oreag-test-{secrets.token_hex(4)}@closefuture.io"

seed_user(EMAIL, PASSWORD)
token = sign_in(EMAIL, PASSWORD)
auth = {"Authorization": f"Bearer {token}"}

# create project
r = httpx.post(
    f"{API}/api/projects",
    json={"name": "M1 verify project", "chunk_size": 800, "chunk_overlap": 100},
    headers=auth,
    timeout=30,
)
check("create project", r.status_code == 201, f"({r.status_code}) {r.text[:200]}")
project = r.json()

# list shows it
r = httpx.get(f"{API}/api/projects", headers=auth, timeout=30)
check(
    "list contains project",
    r.status_code == 200 and any(p["id"] == project["id"] for p in r.json()),
)

# invalid config rejected
r = httpx.post(
    f"{API}/api/projects",
    json={"name": "bad", "embedding_model": "made-up"},
    headers=auth,
    timeout=30,
)
check("invalid embedding model rejected", r.status_code == 422, f"({r.status_code})")

# tampered token rejected
r = httpx.get(
    f"{API}/api/projects", headers={"Authorization": f"Bearer {token}x"}, timeout=30
)
check("tampered token rejected", r.status_code == 401, f"({r.status_code})")

# second user cannot fetch first user's project
seed_user(EMAIL2, PASSWORD)
token2 = sign_in(EMAIL2, PASSWORD)
r = httpx.get(
    f"{API}/api/projects/{project['id']}",
    headers={"Authorization": f"Bearer {token2}"},
    timeout=30,
)
check("cross-tenant access returns 404", r.status_code == 404, f"({r.status_code})")

# PATCH + DELETE round-trip
r = httpx.patch(
    f"{API}/api/projects/{project['id']}",
    json={"name": "M1 renamed", "top_k": 7},
    headers=auth,
    timeout=30,
)
check("update project", r.status_code == 200 and r.json().get("top_k") == 7)
r = httpx.delete(f"{API}/api/projects/{project['id']}", headers=auth, timeout=30)
check("delete project", r.status_code == 204, f"({r.status_code})")

print()
print("M1 VERIFICATION:", "ALL PASS" if ok else "FAILURES — see above")
sys.exit(0 if ok else 1)
