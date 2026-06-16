"""Verify the Add-files endpoint honours per-file chunk size + top_k.

Run from backend/ with the server on :8000 and Ollama running:
    python -m tests.verify_add_config
"""
import secrets
import sys
import time
import uuid
from pathlib import Path

import httpx
import psycopg

from app.config import settings
from app.db import SessionLocal
from app.models import File

SUPABASE_URL = settings.supabase_url
ANON = settings.supabase_anon_key
DSN = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
API = "http://localhost:8000"
PDF = Path(__file__).resolve().parent / "fixtures" / "RAG With LangGraph.pdf"

ok = True


def check(label, cond, extra=""):
    global ok
    print(("PASS" if cond else "FAIL"), label, extra)
    ok = ok and cond


def seed_user(email, password):
    with psycopg.connect(DSN, autocommit=True) as conn:
        uid = str(
            conn.execute(
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
            ).fetchone()[0]
        )
        conn.execute(
            """
            insert into auth.identities (id, user_id, provider_id, identity_data,
                provider, last_sign_in_at, created_at, updated_at)
            values (gen_random_uuid(), %s, %s,
                jsonb_build_object('sub', %s::text, 'email', %s::text, 'email_verified', true),
                'email', now(), now(), now())
            """,
            (uid, uid, uid, email),
        )
    return uid


email = f"oreag-cfg-{secrets.token_hex(4)}@closefuture.io"
password = "Oreag-" + secrets.token_hex(8)
seed_user(email, password)
token = httpx.post(
    f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
    json={"email": email, "password": password},
    headers={"apikey": ANON},
    timeout=30,
).json()["access_token"]
auth = {"Authorization": f"Bearer {token}"}

# create an Ollama-backed project (so ingestion works without an OpenAI key)
project = httpx.post(
    f"{API}/api/projects",
    json={
        "name": "Add-config verify",
        "chunk_size": 1000,
        "chunk_overlap": 200,
        "embedding_provider": "ollama",
        "embedding_model": "nomic-embed-text",
        "llm_provider": "ollama",
        "llm_model": "llama3.1",
        "top_k": 5,
    },
    headers=auth,
    timeout=30,
).json()
pid = project["id"]
check("project created with top_k=5", project["top_k"] == 5)

# upload with per-file chunk overrides + a new top_k
r = httpx.post(
    f"{API}/api/projects/{pid}/files",
    files={"uploads": (PDF.name, PDF.read_bytes(), "application/pdf")},
    data={"chunk_size": "400", "chunk_overlap": "40", "top_k": "9"},
    headers=auth,
    timeout=300,
)
check("upload accepted", r.status_code == 201, f"({r.status_code}) {r.text[:160]}")
file_id = uuid.UUID(r.json()[0]["id"])

# project top_k should now be 9
proj = httpx.get(f"{API}/api/projects/{pid}", headers=auth, timeout=30).json()
check("top_k updated to 9 on upload", proj["top_k"] == 9, f"got {proj['top_k']}")

# the file row should carry the chunk overrides
db = SessionLocal()
frow = db.get(File, file_id)
check("file stored chunk_size=400", frow.chunk_size == 400, f"got {frow.chunk_size}")
check("file stored chunk_overlap=40", frow.chunk_overlap == 40, f"got {frow.chunk_overlap}")
db.close()

# wait for indexing to finish
indexed = False
for _ in range(120):
    files = httpx.get(f"{API}/api/projects/{pid}/files", headers=auth, timeout=30).json()
    st = files[0]["status"] if files else "?"
    if st in ("indexed", "failed"):
        indexed = st == "indexed"
        check("file indexed", indexed, f"status={st} err={files[0].get('error')}")
        break
    time.sleep(2)
else:
    check("file indexed", False, "timed out")

# cleanup
httpx.delete(f"{API}/api/projects/{pid}", headers=auth, timeout=30)

print()
print("ADD-CONFIG VERIFICATION:", "ALL PASS" if ok else "FAILURES — see above")
sys.exit(0 if ok else 1)
