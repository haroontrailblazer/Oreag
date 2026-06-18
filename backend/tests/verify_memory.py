"""Manual end-to-end check of the memory + retrieve endpoints.

Exercises the pgvector paths unit tests can't (search ordering, recent pinning,
docs retrieve). Requires a project with an embedding key configured.

Usage (PowerShell):
  $env:OREAG_API_KEY="oreag_sk_..."; $env:OREAG_PROJECT_ID="<uuid>"
  cd backend; .venv\\Scripts\\python.exe -m tests.verify_memory
"""
import os

import httpx

BASE = os.environ.get("OREAG_API_BASE", "http://localhost:8000")
KEY = os.environ["OREAG_API_KEY"]
PID = os.environ["OREAG_PROJECT_ID"]

ok = True


def check(label: str, cond: bool) -> None:
    global ok
    print(("PASS " if cond else "FAIL ") + label)
    ok = ok and cond


client = httpx.Client(
    base_url=BASE, headers={"Authorization": f"Bearer {KEY}"}, timeout=60
)

m1 = client.post(
    f"/v1/projects/{PID}/memory",
    json={"content": "The database is Supabase project nzz", "pinned": True},
).json()
m2 = client.post(
    f"/v1/projects/{PID}/memory",
    json={"content": "Auth uses Supabase JWKS verification"},
).json()
check("create returns id", "id" in m1)

recent = client.get(f"/v1/projects/{PID}/memory/recent", params={"limit": 5}).json()
check("recent returns pinned first", bool(recent) and recent[0]["pinned"] is True)

search = client.post(
    f"/v1/projects/{PID}/memory/search", json={"query": "where is the database"}
).json()
check("search surfaces the DB memory", bool(search) and "Supabase" in search[0]["content"])

retr = client.post(f"/v1/projects/{PID}/retrieve", json={"query": "anything"}).json()
check("retrieve returns a list", isinstance(retr, list))

for m in (m1, m2):
    if "id" in m:
        client.delete(f"/v1/projects/{PID}/memory/{m['id']}")

print("OK" if ok else "FAILURES")
