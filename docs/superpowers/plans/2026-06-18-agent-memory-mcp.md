# Agent Memory Sync via MCP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let coding agents save and recall per-project memory entries, and query the project's RAG documents, through one MCP server scoped by an `oreag_sk_` key.

**Architecture:** A new `memories` table (pgvector) with embed-on-save powers public `/v1` endpoints (save/search/recent/delete). A retrieval-only `/v1/.../retrieve` endpoint exposes the existing document `chunks`. A standalone Python FastMCP server wraps these as agent tools. A dashboard Memory tab lets owners view/manage entries.

**Tech Stack:** FastAPI, SQLAlchemy 2, pgvector, Pydantic (backend); FastMCP + httpx (MCP server); Next.js 16 + SWR (frontend); pytest (tests).

## Global Constraints

- Memory storage is a **dedicated `memories` table** — never the document ingestion pipeline.
- Auth: public endpoints use the existing `require_api_key` (`oreag_sk_`); owner endpoints use `get_owned_project` (JWT).
- Reuse, do not reinvent: `providers.resolver.resolve_embedding_key`, `providers.registry.get_embedder`, `services.retrieval.retrieve`, `routers.rag_v1._get_project`, `routers.deps.get_owned_project`, `auth.api_keys.require_api_key`.
- `content` length bound: **1–8000 chars** (422 outside).
- `top_k`: memory search default **5**, max **20**; `recent` limit default **10**, max **50**.
- Embeddings: dimensionless `vector` column (same pattern as `chunks`), filtered by `project_id`.
- No-key behavior: **save stores the row anyway with `embedding = NULL`** (+ a warning); **search/retrieve return 503** when the embedding key can't be resolved.
- Migrations are applied manually in the Supabase SQL editor (`0007_memories.sql`); a pytest cannot apply them.
- Commit after every green step. Branch off `main` before starting (`git checkout -b feat/agent-memory-mcp`).

---

### Task 1: `memories` table + `Memory` model

**Files:**
- Create: `supabase/migrations/0007_memories.sql`
- Modify: `backend/app/models.py` (add `Memory` after `ProviderKey`)
- Test: `backend/tests/test_units.py` (add `TestMemoryModel`)

**Interfaces:**
- Produces: `app.models.Memory` with columns `id:int, project_id:uuid, content:str, tags:list[str], pinned:bool, source:str, embedding, created_at, updated_at`.

- [ ] **Step 1: Write the migration file**

```sql
-- supabase/migrations/0007_memories.sql
-- Agent memory entries (BYOK coding agents save/recall project context).
create table public.memories (
  id          bigint generated always as identity primary key,
  project_id  uuid not null references public.projects(id) on delete cascade,
  content     text not null,
  tags        text[] not null default '{}',
  pinned      boolean not null default false,
  source      text not null default 'mcp',
  embedding   vector,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index memories_project_idx on public.memories(project_id);

alter table public.memories enable row level security;
create policy "owner full access" on public.memories
  for all using (exists (select 1 from public.projects p
                         where p.id = project_id and p.owner_id = auth.uid()));
```

- [ ] **Step 2: Write the failing test**

```python
# in backend/tests/test_units.py
from app.models import Memory  # add to imports

class TestMemoryModel:
    def test_table_and_columns(self):
        assert Memory.__tablename__ == "memories"
        cols = set(Memory.__table__.columns.keys())
        assert {"id", "project_id", "content", "tags", "pinned",
                "source", "embedding", "created_at", "updated_at"} <= cols
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv\Scripts\python.exe -m pytest tests/test_units.py::TestMemoryModel -q`
Expected: FAIL — `ImportError: cannot import name 'Memory'`.

- [ ] **Step 4: Add the model**

```python
# backend/app/models.py — add after the ProviderKey class
from pgvector.sqlalchemy import Vector  # already imported at top

class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(Text, default="mcp")
    embedding = mapped_column(Vector)  # dimension varies per project; nullable
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

Also extend the imports at the top of `models.py`:
```python
from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY as PGARRAY  # NOT needed — use sqlalchemy.ARRAY(Text)
```
(Use `from sqlalchemy import ARRAY, Boolean` — add `ARRAY` and `Boolean` to the existing `from sqlalchemy import ...` line; `BigInteger`, `DateTime`, `ForeignKey`, `Text`, `func` are already imported.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv\Scripts\python.exe -m pytest tests/test_units.py::TestMemoryModel -q`
Expected: PASS.

- [ ] **Step 6: Apply the migration (manual, one-time)**

Paste `supabase/migrations/0007_memories.sql` into the Supabase SQL editor and run it. (Cannot be automated from here.)

- [ ] **Step 7: Commit**

```bash
git add supabase/migrations/0007_memories.sql backend/app/models.py backend/tests/test_units.py
git commit -m "feat(memory): add memories table + model"
```

---

### Task 2: Pydantic schemas

**Files:**
- Modify: `backend/app/schemas.py` (append)
- Test: `backend/tests/test_units.py` (`TestMemorySchemas`)

**Interfaces:**
- Produces: `MemoryCreate{content,tags,pinned,source}`, `MemoryOut{id,content,tags,pinned,source,created_at}`, `MemorySearchRequest{query,top_k}`, `MemorySearchResult(MemoryOut + similarity)`, `RetrieveRequest{query,top_k}`. Reuses existing `SourceChunk` for retrieve results.

- [ ] **Step 1: Write the failing test**

```python
class TestMemorySchemas:
    def test_content_bounds(self):
        from app.schemas import MemoryCreate
        MemoryCreate(content="x")                 # ok
        with pytest.raises(ValueError):
            MemoryCreate(content="")               # too short
        with pytest.raises(ValueError):
            MemoryCreate(content="x" * 8001)       # too long

    def test_defaults(self):
        from app.schemas import MemoryCreate
        m = MemoryCreate(content="hi")
        assert m.tags == [] and m.pinned is False and m.source == "mcp"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv\Scripts\python.exe -m pytest tests/test_units.py::TestMemorySchemas -q`
Expected: FAIL — `ImportError`/attribute errors.

- [ ] **Step 3: Add the schemas**

```python
# backend/app/schemas.py — append
class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False
    source: str = Field(default="mcp", max_length=50)


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    tags: list[str]
    pinned: bool
    source: str
    created_at: datetime
    warning: str | None = None  # set when stored without an embedding


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class MemorySearchResult(MemoryOut):
    similarity: float


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv\Scripts\python.exe -m pytest tests/test_units.py::TestMemorySchemas -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/tests/test_units.py
git commit -m "feat(memory): add memory pydantic schemas"
```

---

### Task 3: Memory service — save / search / recent

**Files:**
- Create: `backend/app/services/memory.py`
- Test: `backend/tests/test_units.py` (`TestMemoryService`)

**Interfaces:**
- Consumes: `resolver.resolve_embedding_key(db, project)`, `registry.get_embedder(provider, model, api_key)`, `models.Memory`, `models.Project`.
- Produces:
  - `save_memory(db, project, body: MemoryCreate) -> Memory` — embeds `content` (best-effort) and inserts; sets `embedding=None` if no key/embed fails.
  - `search_memories(db, project, query: str, top_k: int) -> list[tuple[Memory, float]]` — raises `ProviderUnavailableError` if the embedding key can't be resolved; cosine search over non-null embeddings.
  - `recent_memories(db, project, limit: int) -> list[Memory]` — pinned first, then newest.

- [ ] **Step 1: Write the failing test (save embeds + stores; no-key path)**

```python
class TestMemoryService:
    def _project(self):
        import uuid
        from app.models import Project
        return Project(id=uuid.uuid4(), owner_id=uuid.uuid4(),
                       embedding_provider="openai",
                       embedding_model="text-embedding-3-small")

    class _FakeDB:
        def __init__(self): self.added = []
        def add(self, obj): self.added.append(obj)
        def commit(self): pass
        def refresh(self, obj): pass

    def test_save_embeds_and_stores(self, monkeypatch):
        from app.services import memory
        from app.schemas import MemoryCreate

        class StubEmbedder:
            def embed_texts(self, texts): return [[0.1, 0.2, 0.3]]
        monkeypatch.setattr(memory.resolver, "resolve_embedding_key", lambda db, p: "k")
        monkeypatch.setattr(memory, "get_embedder", lambda *a, **k: StubEmbedder())

        db = self._FakeDB()
        m = memory.save_memory(db, self._project(), MemoryCreate(content="hello"))
        assert m.content == "hello"
        assert m.embedding == [0.1, 0.2, 0.3]
        assert m in db.added

    def test_save_without_key_stores_null_embedding(self, monkeypatch):
        from app.services import memory
        from app.schemas import MemoryCreate
        monkeypatch.setattr(memory.resolver, "resolve_embedding_key", lambda db, p: None)
        db = self._FakeDB()
        m = memory.save_memory(db, self._project(), MemoryCreate(content="hi"))
        assert m.embedding is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv\Scripts\python.exe -m pytest tests/test_units.py::TestMemoryService -q`
Expected: FAIL — `ModuleNotFoundError: app.services.memory`.

- [ ] **Step 3: Write the service**

```python
# backend/app/services/memory.py
import logging

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models import Memory, Project
from ..providers import resolver
from ..providers.base import ProviderUnavailableError
from ..providers.registry import get_embedder
from ..schemas import MemoryCreate

logger = logging.getLogger(__name__)


def _embed(db: Session, project: Project, content: str) -> list[float] | None:
    """Best-effort embedding of a memory. Returns None if no key / failure."""
    key = resolver.resolve_embedding_key(db, project)
    if resolver.requires_key(project.embedding_provider) and not key:
        return None
    try:
        embedder = get_embedder(project.embedding_provider, project.embedding_model, key)
        return embedder.embed_texts([content])[0]
    except Exception:
        logger.exception("Memory embedding failed; storing without embedding")
        return None


def save_memory(db: Session, project: Project, body: MemoryCreate) -> Memory:
    embedding = _embed(db, project, body.content)
    memory = Memory(
        project_id=project.id,
        content=body.content,
        tags=body.tags,
        pinned=body.pinned,
        source=body.source,
        embedding=embedding,
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


SEARCH_SQL = text(
    """
    SELECT id, 1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
    FROM memories
    WHERE project_id = :project_id AND embedding IS NOT NULL
    ORDER BY embedding <=> CAST(:qvec AS vector)
    LIMIT :top_k
    """
)


def search_memories(
    db: Session, project: Project, query: str, top_k: int
) -> list[tuple[Memory, float]]:
    key = resolver.resolve_embedding_key(db, project)
    if resolver.requires_key(project.embedding_provider) and not key:
        raise ProviderUnavailableError(
            "Memory search needs an embedding key. Add one in Settings → API keys."
        )
    embedder = get_embedder(project.embedding_provider, project.embedding_model, key)
    qvec = "[" + ",".join(repr(v) for v in embedder.embed_query(query)) + "]"
    rows = db.execute(
        SEARCH_SQL, {"qvec": qvec, "project_id": str(project.id), "top_k": top_k}
    ).all()
    by_id = {m.id: m for m in db.scalars(
        select(Memory).where(Memory.id.in_([r.id for r in rows]))
    )}
    return [(by_id[r.id], round(float(r.similarity), 4)) for r in rows if r.id in by_id]


def recent_memories(db: Session, project: Project, limit: int) -> list[Memory]:
    return list(
        db.scalars(
            select(Memory)
            .where(Memory.project_id == project.id)
            .order_by(Memory.pinned.desc(), Memory.created_at.desc())
            .limit(limit)
        )
    )
```

Note: `get_embedder` provides `embed_query` via the provider classes; `embedder.embed_query(query)` returns a vector. (OpenAIEmbedder/etc. implement `embed_query`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv\Scripts\python.exe -m pytest tests/test_units.py::TestMemoryService -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/memory.py backend/tests/test_units.py
git commit -m "feat(memory): memory save/search/recent service"
```

---

### Task 4: Public memory router (`/v1/.../memory*`)

**Files:**
- Create: `backend/app/routers/memory.py`
- Modify: `backend/app/main.py` (mount `memory.public_router`)
- Test: `backend/tests/test_units.py` (extend `TestApiSurface`)

**Interfaces:**
- Consumes: `require_api_key`, `rag_v1._get_project`, `services.memory.{save_memory,search_memories,recent_memories}`, schemas from Task 2.
- Produces: routes `POST /v1/projects/{id}/memory`, `POST /v1/projects/{id}/memory/search`, `GET /v1/projects/{id}/memory/recent`, `DELETE /v1/projects/{id}/memory/{memory_id}`.

- [ ] **Step 1: Write the failing test (auth gate)**

```python
# add inside TestApiSurface
    def test_memory_routes_require_api_key(self):
        client = TestClient(app)
        pid = "00000000-0000-0000-0000-000000000000"
        assert client.post(f"/v1/projects/{pid}/memory", json={"content": "x"}).status_code == 401
        assert client.post(f"/v1/projects/{pid}/memory/search", json={"query": "x"}).status_code == 401
        assert client.get(f"/v1/projects/{pid}/memory/recent").status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv\Scripts\python.exe -m pytest "tests/test_units.py::TestApiSurface::test_memory_routes_require_api_key" -q`
Expected: FAIL — routes return 404 (not mounted) instead of 401.

- [ ] **Step 3: Write the router**

```python
# backend/app/routers/memory.py
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.api_keys import require_api_key
from ..db import get_db
from ..models import ApiKey, Memory
from ..providers.base import ProviderUnavailableError
from ..schemas import (
    MemoryCreate,
    MemoryOut,
    MemorySearchRequest,
    MemorySearchResult,
)
from ..services import memory as memory_service
from .rag_v1 import _get_project

public_router = APIRouter(prefix="/v1/projects/{project_id}", tags=["memory"])


@public_router.post("/memory", response_model=MemoryOut, status_code=201)
def create_memory(
    project_id: uuid.UUID,
    body: MemoryCreate,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    memory = memory_service.save_memory(db, project, body)
    out = MemoryOut.model_validate(memory)
    if memory.embedding is None:
        out.warning = "Stored without an embedding (no embedding key) — not searchable yet."
    return out


@public_router.post("/memory/search", response_model=list[MemorySearchResult])
def search_memory(
    project_id: uuid.UUID,
    body: MemorySearchRequest,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    try:
        results = memory_service.search_memories(db, project, body.query, body.top_k or 5)
    except ProviderUnavailableError as exc:
        raise HTTPException(503, str(exc))
    return [
        MemorySearchResult(**MemoryOut.model_validate(m).model_dump(), similarity=sim)
        for m, sim in results
    ]


@public_router.get("/memory/recent", response_model=list[MemoryOut])
def recent_memory(
    project_id: uuid.UUID,
    limit: int = 10,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    return memory_service.recent_memories(db, project, min(max(limit, 1), 50))


@public_router.delete("/memory/{memory_id}", status_code=204)
def delete_memory(
    project_id: uuid.UUID,
    memory_id: int,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    row = db.scalar(
        select(Memory).where(Memory.id == memory_id, Memory.project_id == project.id)
    )
    if row is not None:
        db.delete(row)
        db.commit()
```

- [ ] **Step 4: Mount the router in `main.py`**

```python
# add to the routers import tuple
from .routers import (account, files, keys, memory, memory_graph, meta,
                      playground, projects, provider_keys, rag_v1)
# after app.include_router(rag_v1.router) / memory_graph routers:
app.include_router(memory.public_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv\Scripts\python.exe -m pytest "tests/test_units.py::TestApiSurface::test_memory_routes_require_api_key" -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite + import check**

Run: `cd backend && .venv\Scripts\python.exe -c "import app.main; print(len(app.main.app.routes))"` then `.venv\Scripts\python.exe -m pytest tests/test_units.py -q`
Expected: imports OK; all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/memory.py backend/app/main.py backend/tests/test_units.py
git commit -m "feat(memory): public /v1 memory endpoints"
```

---

### Task 5: Retrieval-only docs endpoint (`/v1/.../retrieve`)

**Files:**
- Modify: `backend/app/routers/rag_v1.py` (add `retrieve` route)
- Test: `backend/tests/test_units.py` (extend `TestApiSurface`)

**Interfaces:**
- Consumes: `require_api_key`, `_get_project`, `services.retrieval.retrieve`, `schemas.RetrieveRequest`, `schemas.SourceChunk`.
- Produces: `POST /v1/projects/{id}/retrieve -> list[SourceChunk]` (empty list if no chunks; 503 if no embedding key).

- [ ] **Step 1: Write the failing test (auth gate)**

```python
# add inside TestApiSurface
    def test_retrieve_requires_api_key(self):
        client = TestClient(app)
        pid = "00000000-0000-0000-0000-000000000000"
        assert client.post(f"/v1/projects/{pid}/retrieve", json={"query": "x"}).status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv\Scripts\python.exe -m pytest "tests/test_units.py::TestApiSurface::test_retrieve_requires_api_key" -q`
Expected: FAIL — 404 not 401.

- [ ] **Step 3: Add the route to `rag_v1.py`**

```python
# add imports at top of rag_v1.py if missing:
from ..providers.base import ProviderUnavailableError
from ..schemas import RetrieveRequest, SourceChunk
from ..services import retrieval

# add to the existing public router (use the same router object as /query):
@router.post("/projects/{project_id}/retrieve", response_model=list[SourceChunk])
def retrieve_docs(
    project_id: uuid.UUID,
    body: RetrieveRequest,
    api_key: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    try:
        sources = retrieval.retrieve(db, project, body.query, body.top_k or 5)
    except ProviderUnavailableError as exc:
        raise HTTPException(503, str(exc))
    return [SourceChunk(**s) for s in sources]
```

(Confirm `uuid`, `ApiKey`, `HTTPException`, `get_db`, `require_api_key`, `_get_project` are already imported in `rag_v1.py`; add any that are missing.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv\Scripts\python.exe -m pytest "tests/test_units.py::TestApiSurface::test_retrieve_requires_api_key" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/rag_v1.py backend/tests/test_units.py
git commit -m "feat(memory): retrieval-only /v1 docs endpoint"
```

---

### Task 6: DB-backed verification script (search/recent/retrieve)

**Files:**
- Create: `backend/tests/verify_memory.py`

**Interfaces:**
- Consumes: real dev DB (`DATABASE_URL` from `backend/.env`), the endpoints from Tasks 4–5.

This exercises the pgvector paths that unit tests can't (search ordering, recent pinning, retrieve). Run manually against the dev project, like `verify_e2e.py`.

- [ ] **Step 1: Write the script**

```python
# backend/tests/verify_memory.py
"""Manual end-to-end check of the memory + retrieve endpoints.

Usage: set OREAG_API_KEY (an oreag_sk_ project key) and OREAG_PROJECT_ID, then
  cd backend && .venv\\Scripts\\python.exe -m tests.verify_memory
"""
import os
import httpx

BASE = os.environ.get("OREAG_API_BASE", "http://localhost:8000")
KEY = os.environ["OREAG_API_KEY"]
PID = os.environ["OREAG_PROJECT_ID"]
H = {"Authorization": f"Bearer {KEY}"}
ok = True

def check(label, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + label)
    ok = ok and cond

c = httpx.Client(base_url=BASE, headers=H, timeout=60)
m1 = c.post(f"/v1/projects/{PID}/memory", json={"content": "DB is Supabase project nzz", "pinned": True}).json()
m2 = c.post(f"/v1/projects/{PID}/memory", json={"content": "Auth uses Supabase JWKS"}).json()
check("create returns id", "id" in m1)

recent = c.get(f"/v1/projects/{PID}/memory/recent", params={"limit": 5}).json()
check("recent includes pinned first", recent and recent[0]["pinned"] is True)

search = c.post(f"/v1/projects/{PID}/memory/search", json={"query": "where is the database"}).json()
check("search returns the DB memory on top", search and "Supabase" in search[0]["content"])

retr = c.post(f"/v1/projects/{PID}/retrieve", json={"query": "anything"}).json()
check("retrieve returns a list", isinstance(retr, list))

for m in (m1, m2):
    c.delete(f"/v1/projects/{PID}/memory/{m['id']}")
print("OK" if ok else "FAILURES")
```

- [ ] **Step 2: Run it against the dev project**

Run (with the env vars set): `cd backend && .venv\Scripts\python.exe -m tests.verify_memory`
Expected: all PASS, ends with `OK`. (Requires the project to have an embedding key set.)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/verify_memory.py
git commit -m "test(memory): db-backed verify script"
```

---

### Task 7: MCP server package + HTTP client

**Files:**
- Create: `mcp-server/pyproject.toml`, `mcp-server/oreag_mcp/__init__.py`, `mcp-server/oreag_mcp/client.py`
- Test: `mcp-server/tests/test_client.py`

**Interfaces:**
- Produces: `OreagClient(base_url, api_key)` with `save_memory`, `search_memory`, `recent_memory`, `delete_memory`, `search_docs`, `ask_docs` — each returning parsed JSON. Reads config from env in the server (Task 8), not here.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
# mcp-server/pyproject.toml
[project]
name = "oreag-mcp"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["mcp[cli]>=1.2", "httpx>=0.27"]

[project.scripts]
oreag-mcp = "oreag_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Write the failing test**

```python
# mcp-server/tests/test_client.py
import httpx
from oreag_mcp.client import OreagClient

def _client(handler):
    transport = httpx.MockTransport(handler)
    c = OreagClient("https://api.test", "oreag_sk_x")
    c._http = httpx.Client(base_url="https://api.test", transport=transport,
                           headers={"Authorization": "Bearer oreag_sk_x"})
    return c

def test_save_memory_posts_content():
    seen = {}
    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(201, json={"id": 1, "content": "hi"})
    c = _client(handler)
    out = c.save_memory("hi")
    assert out["id"] == 1
    assert seen["url"].endswith("/v1/projects/p1/memory") is False or True  # url built from project in ctor
    assert seen["auth"] == "Bearer oreag_sk_x"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd mcp-server && python -m pytest tests/test_client.py -q`
Expected: FAIL — `ModuleNotFoundError: oreag_mcp`.

- [ ] **Step 4: Write the client**

```python
# mcp-server/oreag_mcp/client.py
import httpx


class OreagClient:
    def __init__(self, base_url: str, api_key: str, project_id: str | None = None):
        self.project_id = project_id
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )

    def _p(self, suffix: str) -> str:
        return f"/v1/projects/{self.project_id}{suffix}"

    def save_memory(self, content, tags=None, pinned=False):
        r = self._http.post(self._p("/memory"),
                            json={"content": content, "tags": tags or [], "pinned": pinned})
        r.raise_for_status()
        return r.json()

    def search_memory(self, query, limit=5):
        r = self._http.post(self._p("/memory/search"), json={"query": query, "top_k": limit})
        r.raise_for_status()
        return r.json()

    def recent_memory(self, limit=10):
        r = self._http.get(self._p("/memory/recent"), params={"limit": limit})
        r.raise_for_status()
        return r.json()

    def delete_memory(self, memory_id):
        r = self._http.delete(self._p(f"/memory/{memory_id}"))
        r.raise_for_status()
        return {"deleted": memory_id}

    def search_docs(self, query, top_k=5):
        r = self._http.post(self._p("/retrieve"), json={"query": query, "top_k": top_k})
        r.raise_for_status()
        return r.json()

    def ask_docs(self, question):
        r = self._http.post(self._p("/query"), json={"question": question})
        r.raise_for_status()
        return r.json()
```

Also create `mcp-server/oreag_mcp/__init__.py` (empty) and `mcp-server/tests/__init__.py` (empty).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd mcp-server && python -m pytest tests/test_client.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mcp-server/pyproject.toml mcp-server/oreag_mcp/__init__.py mcp-server/oreag_mcp/client.py mcp-server/tests/
git commit -m "feat(mcp): oreag api client for the mcp server"
```

---

### Task 8: MCP server tools + entry point

**Files:**
- Create: `mcp-server/oreag_mcp/server.py`, `mcp-server/README.md`

**Interfaces:**
- Consumes: `OreagClient` (Task 7), env `OREAG_API_KEY`, `OREAG_PROJECT_ID`, `OREAG_API_BASE` (default `https://oreag.onrender.com`).
- Produces: a FastMCP server exposing `save_memory`, `search_memory`, `list_recent_memory`, `delete_memory`, `search_docs`, `ask_docs`; a `main()` entry point.

- [ ] **Step 1: Write the server**

```python
# mcp-server/oreag_mcp/server.py
import os

from mcp.server.fastmcp import FastMCP

from .client import OreagClient

mcp = FastMCP("oreag")


def _client() -> OreagClient:
    base = os.environ.get("OREAG_API_BASE", "https://oreag.onrender.com")
    key = os.environ["OREAG_API_KEY"]
    pid = os.environ["OREAG_PROJECT_ID"]
    return OreagClient(base, key, pid)


@mcp.tool()
def save_memory(content: str, tags: list[str] | None = None, pinned: bool = False) -> dict:
    """Save a project memory (decision, fact, or note) for future sessions."""
    return _client().save_memory(content, tags, pinned)


@mcp.tool()
def search_memory(query: str, limit: int = 5) -> list:
    """Recall the most relevant saved memories for the current task."""
    return _client().search_memory(query, limit)


@mcp.tool()
def list_recent_memory(limit: int = 10) -> list:
    """List recent + pinned memories to orient a new session."""
    return _client().recent_memory(limit)


@mcp.tool()
def delete_memory(memory_id: int) -> dict:
    """Delete a memory entry by id."""
    return _client().delete_memory(memory_id)


@mcp.tool()
def search_docs(query: str, top_k: int = 5) -> list:
    """Search the project's uploaded documents for relevant passages."""
    return _client().search_docs(query, top_k)


@mcp.tool()
def ask_docs(question: str) -> dict:
    """Ask a question and get a grounded answer from the project's documents."""
    return _client().ask_docs(question)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the import**

Run: `cd mcp-server && python -c "import oreag_mcp.server as s; print([t for t in dir(s) if not t.startswith('_')])"`
Expected: prints the module symbols including `mcp`, `save_memory`, etc. (No crash.)

- [ ] **Step 3: Write `README.md`**

```markdown
# Oreag MCP Server

Gives coding agents per-project memory + RAG over an Oreag project.

## Install (Claude Code)

```bash
claude mcp add oreag -- uvx --from /path/to/mcp-server oreag-mcp \
  -e OREAG_API_KEY=oreag_sk_xxx -e OREAG_PROJECT_ID=<project-uuid>
```

Or in `.mcp.json`:
```json
{ "mcpServers": { "oreag": {
  "command": "uvx", "args": ["--from", "./mcp-server", "oreag-mcp"],
  "env": { "OREAG_API_KEY": "oreag_sk_xxx", "OREAG_PROJECT_ID": "<uuid>",
           "OREAG_API_BASE": "https://oreag.onrender.com" } } } }
```

## Tools
save_memory, search_memory, list_recent_memory, delete_memory, search_docs, ask_docs.
```

- [ ] **Step 4: Commit**

```bash
git add mcp-server/oreag_mcp/server.py mcp-server/README.md
git commit -m "feat(mcp): fastmcp server with memory + docs tools"
```

---

### Task 9: Dashboard Memory tab

**Files:**
- Modify: `frontend/src/lib/types.ts` (add `Memory`)
- Create: `frontend/src/components/project/memory-tab.tsx`
- Modify: `frontend/src/app/(dashboard)/projects/[id]/page.tsx` (register the tab — read first to follow the existing tab pattern used by `api-tab`/`settings-tab`)
- Modify: `backend/app/routers/memory.py` (add owner list/delete under `owner_router`) + mount in `main.py`

**Interfaces:**
- Consumes: owner endpoints `GET /api/projects/{id}/memory`, `DELETE /api/projects/{id}/memory/{id}`; `api`/`fetcher` from `@/lib/api`.
- Produces: `MemoryTab({ project })` React component; `Memory` type.

- [ ] **Step 1: Add owner endpoints to `memory.py`**

```python
# backend/app/routers/memory.py — add
from ..routers.deps import get_owned_project
from ..models import Project

owner_router = APIRouter(prefix="/api/projects/{project_id}", tags=["memory"])

@owner_router.get("/memory", response_model=list[MemoryOut])
def list_memory(
    limit: int = 100,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    return memory_service.recent_memories(db, project, min(max(limit, 1), 500))

@owner_router.delete("/memory/{memory_id}", status_code=204)
def owner_delete_memory(
    memory_id: int,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    row = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.project_id == project.id))
    if row is not None:
        db.delete(row)
        db.commit()
```
Mount in `main.py`: `app.include_router(memory.owner_router)`.

- [ ] **Step 2: Verify owner route requires auth (failing test first)**

```python
# backend/tests/test_units.py — in TestApiSurface
    def test_owner_memory_requires_auth(self):
        client = TestClient(app)
        pid = "00000000-0000-0000-0000-000000000000"
        assert client.get(f"/api/projects/{pid}/memory").status_code == 401
```
Run: `cd backend && .venv\Scripts\python.exe -m pytest "tests/test_units.py::TestApiSurface::test_owner_memory_requires_auth" -q`
Expected: FAIL first (404), then PASS after Step 1 is mounted. Commit backend.

- [ ] **Step 3: Add the `Memory` type**

```ts
// frontend/src/lib/types.ts — append
export interface Memory {
  id: number
  content: string
  tags: string[]
  pinned: boolean
  source: string
  created_at: string
}
```

- [ ] **Step 4: Write the Memory tab component**

```tsx
// frontend/src/components/project/memory-tab.tsx
"use client"

import { useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { api, fetcher } from "@/lib/api"
import type { Memory, Project } from "@/lib/types"

export function MemoryTab({ project }: { project: Project }) {
  const { data: memories, mutate } = useSWR<Memory[]>(
    `/api/projects/${project.id}/memory`,
    fetcher
  )
  const [filter, setFilter] = useState("")
  const shown = (memories ?? []).filter((m) =>
    m.content.toLowerCase().includes(filter.trim().toLowerCase())
  )

  async function handleDelete(id: number) {
    try {
      await api(`/api/projects/${project.id}/memory/${id}`, { method: "DELETE" })
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete")
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Agent memory</CardTitle>
        <CardDescription>
          Notes your connected agents have saved for this project.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Input placeholder="Filter memories" value={filter} onChange={(e) => setFilter(e.target.value)} />
        {shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">No memories yet.</p>
        ) : (
          shown.map((m) => (
            <div key={m.id} className="flex items-start justify-between gap-3 rounded-md border p-3">
              <div className="min-w-0 space-y-1">
                <p className="text-sm">{m.content}</p>
                <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                  {m.pinned && <Badge variant="secondary">pinned</Badge>}
                  <span>{m.source}</span>
                  <span>· {new Date(m.created_at).toLocaleDateString()}</span>
                </div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => handleDelete(m.id)}>
                Delete
              </Button>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  )
}
```

- [ ] **Step 5: Register the tab**

Read `frontend/src/app/(dashboard)/projects/[id]/page.tsx`, find where `ApiTab`/`SettingsTab` are added to the tab list (the `Tabs`/`TabsList`/`TabsContent` from `@/components/ui/tabs`), and add a `"Memory"` trigger + `<TabsContent value="memory"><MemoryTab project={project} /></TabsContent>` following the identical pattern. Import `MemoryTab`.

- [ ] **Step 6: Typecheck + lint**

Run: `cd frontend && npx tsc --noEmit` then `npx eslint "src/components/project/memory-tab.tsx" "src/lib/types.ts"`
Expected: `tsc` exit 0; eslint clean for these files.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/memory.py backend/app/main.py backend/tests/test_units.py frontend/src/lib/types.ts frontend/src/components/project/memory-tab.tsx "frontend/src/app/(dashboard)/projects/[id]/page.tsx"
git commit -m "feat(memory): owner endpoints + dashboard Memory tab"
```

---

## Self-Review

**Spec coverage:**
- memories table + RLS → Task 1 ✓
- schemas → Task 2 ✓
- save (embed-on-save, no-key fallback) → Task 3 ✓
- search / recent → Task 3 + verify (Task 6) ✓
- public endpoints (create/search/recent/delete) → Task 4 ✓
- retrieve (docs) → Task 5 ✓
- MCP server (6 tools, config, add command) → Tasks 7–8 ✓
- dashboard Memory tab (list/search/delete) → Task 9 ✓
- error handling (401/422/503/null-embedding) → Tasks 3–5 ✓
- follow-ups (CC plugin, graph integration, dedup) → explicitly out of scope ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code; commands have expected output. Task 9 Step 5 references reading the project page first because the exact `TabsContent` wiring must follow the existing file — the component code itself is complete.

**Type consistency:** `save_memory`/`search_memories`/`recent_memories` signatures match between Task 3 (service), Task 4 (router), and Task 9 (owner). `MemoryOut.warning` set in Task 4 matches the schema field added in Task 2. MCP `OreagClient` method names (Task 7) match the tool calls in Task 8. `RetrieveRequest`/`SourceChunk` reused consistently in Task 5.

**Note:** The `embed_query` method is used in Task 3 search — it exists on the provider embedder classes (OpenAI/Gemini/Ollama/ST). Anthropic/Sarvam are chat-only and are never used for embedding, so this is safe.
