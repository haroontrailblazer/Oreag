"""Full M2+M3 end-to-end verification against Ollama (local provider).

Run from backend/ with the server NOT required (this drives the pipeline
services directly + the public API via the running server for the key path).

  python -m tests.verify_e2e

Reads credentials from backend/.env. Creates a throwaway user + project,
uploads the legacy reference PDF, runs ingestion synchronously, then queries
both the retrieval pipeline directly and the public /v1 endpoint with a key.
"""
import secrets
import sys
import uuid
from pathlib import Path

import httpx
import psycopg

from app.auth.api_keys import generate_api_key
from app.config import settings
from app.db import SessionLocal
from app.models import ApiKey, Chunk, File, Project
from app.providers import ollama_provider
from app.services.ingestion import ingest_file
from app.services.query import run_query

API = "http://localhost:8000"
EMBEDDING = ("ollama", "nomic-embed-text", 768)
LLM = ("ollama", "llama3.1")
PDF = Path(__file__).resolve().parents[2] / "legacy" / "RAG With LangGraph.pdf"

ok = True


def check(label: str, condition: bool, extra: str = ""):
    global ok
    print(("PASS" if condition else "FAIL"), label, extra)
    ok = ok and condition


def seed_user(db_dsn: str, email: str, password: str) -> str:
    with psycopg.connect(db_dsn, autocommit=True) as conn:
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
    return uid


if not ollama_provider.is_available():
    print("FAIL Ollama is not reachable at", settings.ollama_base_url)
    sys.exit(1)

# confirm both required models are present
tags = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=10).json()
names = {m["name"].split(":")[0] for m in tags.get("models", [])}
check("ollama has nomic-embed-text", "nomic-embed-text" in names, str(sorted(names)))
check("ollama has llama3.1", "llama3.1" in names, str(sorted(names)))
if not ok:
    print("\nPull the missing models, then re-run:")
    print("  ollama pull nomic-embed-text")
    print("  ollama pull llama3.1")
    sys.exit(1)

dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
email = f"oreag-e2e-{secrets.token_hex(4)}@closefuture.io"
owner_id = seed_user(dsn, email, "Oreag-" + secrets.token_hex(8))

db = SessionLocal()
project = Project(
    owner_id=uuid.UUID(owner_id),
    name="E2E verify",
    chunk_size=1000,
    chunk_overlap=200,
    embedding_provider=EMBEDDING[0],
    embedding_model=EMBEDDING[1],
    embedding_dimensions=EMBEDDING[2],
    llm_provider=LLM[0],
    llm_model=LLM[1],
    top_k=4,
)
db.add(project)
db.commit()
project_id = project.id

# upload the PDF to storage + create the file row, exactly like the route does
from app.services import storage  # noqa: E402

file_id = uuid.uuid4()
storage_path = f"{owner_id}/{project_id}/{file_id}.pdf"
pdf_bytes = PDF.read_bytes()
storage.upload_pdf(storage_path, pdf_bytes)
db.add(
    File(
        id=file_id,
        project_id=project_id,
        filename=PDF.name,
        storage_path=storage_path,
        size_bytes=len(pdf_bytes),
    )
)
db.commit()

print("Ingesting (embeddings via Ollama — may take a minute)…")
ingest_file(file_id)

db.expire_all()
file = db.get(File, file_id)
check("file indexed", file.status == "indexed", f"status={file.status} err={file.error}")
check("file has chunks", file.chunk_count > 0, f"chunk_count={file.chunk_count}")
check(
    "markdown sidecar stored (MarkItDown)",
    bool(file.markdown_storage_path),
    f"path={file.markdown_storage_path}",
)
check("no conversion error", file.conversion_error is None, f"err={file.conversion_error}")

chunk_rows = db.query(Chunk).filter(Chunk.project_id == project_id).count()
check("chunks persisted in pgvector", chunk_rows > 0, f"rows={chunk_rows}")

db.refresh(project)
check("project status ready", project.status == "ready", f"status={project.status}")

# direct retrieval + generation
result = run_query(db, project, "What is LangGraph?", None, api_key_id=None)
check("query returns answer", len(result.answer) > 0, f"{result.latency_ms}ms")
check("query returns sources", len(result.sources) > 0, f"{len(result.sources)} sources")
print("   answer:", result.answer[:200].replace("\n", " "))

# public /v1 path with a real API key (requires the server running)
full_key, key_hash, prefix = generate_api_key()
db.add(ApiKey(project_id=project_id, name="e2e", key_prefix=prefix, key_hash=key_hash))
db.commit()

try:
    r = httpx.post(
        f"{API}/v1/projects/{project_id}/query",
        json={"question": "What is LangGraph?"},
        headers={"Authorization": f"Bearer {full_key}"},
        timeout=120,
    )
    check("public /v1 query (valid key)", r.status_code == 200, f"({r.status_code}) {r.text[:150]}")
    r2 = httpx.post(
        f"{API}/v1/projects/{project_id}/query",
        json={"question": "x"},
        headers={"Authorization": "Bearer oreag_sk_wrong"},
        timeout=30,
    )
    check("public /v1 rejects bad key", r2.status_code == 401, f"({r2.status_code})")
except httpx.ConnectError:
    print("SKIP public /v1 checks — backend not running on :8000")

# second file (same content) -> must auto-link to the first via similarity
file_id2 = uuid.uuid4()
storage_path2 = f"{owner_id}/{project_id}/{file_id2}.pdf"
storage.upload_pdf(storage_path2, pdf_bytes)
db.add(
    File(
        id=file_id2,
        project_id=project_id,
        filename="RAG With LangGraph (copy).pdf",
        storage_path=storage_path2,
        size_bytes=len(pdf_bytes),
    )
)
db.commit()
print("Ingesting second file…")
ingest_file(file_id2)

# memory graph (built in-process, no JWT needed)
from app.services.memory_graph import build_memory_graph  # noqa: E402

graph = build_memory_graph(db, project)
related = [e for e in graph.edges if e.type == "related"]
check("memory graph includes chunk nodes", any(n.type == "chunk" for n in graph.nodes))
check(
    "two file nodes present",
    sum(1 for n in graph.nodes if n.type == "file") == 2,
)
check("cross-file related edges exist", len(related) > 0, f"{len(related)} related")
check(
    "file-to-file related edge present",
    any(e.source.startswith("file:") and e.target.startswith("file:") for e in related),
)

# cleanup
db.delete(project)
db.commit()
storage.delete(
    [storage_path, storage_path2, storage_path + ".md", storage_path2 + ".md"]
)
db.close()

print()
print("E2E VERIFICATION:", "ALL PASS" if ok else "FAILURES — see above")
sys.exit(0 if ok else 1)
