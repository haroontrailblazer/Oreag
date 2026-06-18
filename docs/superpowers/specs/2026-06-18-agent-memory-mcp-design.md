# Agent Memory Sync via MCP — Design

**Date:** 2026-06-18
**Status:** Approved (design); ready for implementation plan

## Context & Goal

Oreag is RAG & Memory as a Service. Today a project holds uploaded **documents**
→ `chunks` (pgvector), queryable via the public `/v1` API (`oreag_sk_` keys).
There is no writable, agent-facing **memory** store, and coding agents (Claude
Code, Codex, Claude) have no way to persist or recall project context across
sessions.

**Goal:** let a coding-agent session connect to an Oreag project and (a) **save**
discrete memory entries (decisions, facts, notes), (b) **recall** them in later
sessions, and (c) use the project's **uploaded RAG documents** as additional
agent context — all through one MCP server scoped to a single project by its
API key.

## Decisions (from brainstorming)

- **Distribution:** an **MCP server** is the universal core (works with Claude,
  Claude Code, Codex). A thin Claude Code **plugin** (slash commands + auto
  session hooks) is a later follow-up, not in this spec.
- **Memory unit:** individual **entries** (text + optional tags/pinned), not a
  single MEMORY.md doc or session summaries.
- **Auth/scope:** **per-project `oreag_sk_` key** (reuses the existing key
  system). One repo = one project = one MCP config. No new auth.
- **Retrieval:** semantic **search** + a small **recent/pinned bootstrap**.
- **Storage:** a **dedicated `memories` table** with embed-on-save (Approach A),
  not the document ingestion pipeline.
- **Docs as memory:** also expose the project's documents to agents via a
  retrieval-only endpoint + the existing RAG query.

## Architecture

```
Coding agent (Claude Code / Codex / Claude)
        │  MCP tools
        ▼
Oreag MCP server  ──HTTPS + oreag_sk_ key──►  Oreag /v1 API (FastAPI)
                                                   ├── memories table (pgvector)  ← agent notes
                                                   └── chunks (existing)          ← uploaded docs
Dashboard "Memory" tab (JWT) ──────────────────────► memories (view/search/pin/delete)
```

- The **MCP server** does not read local files itself. The agent (which has file
  access) decides what to persist and calls `save_memory`.
- Memory is **independent of documents** — a project with no uploaded files can
  still accumulate memory.

## Data model — migration `0007_memories.sql`

```sql
create table public.memories (
  id          bigint generated always as identity primary key,
  project_id  uuid not null references public.projects(id) on delete cascade,
  content     text not null,
  tags        text[] not null default '{}',
  pinned      boolean not null default false,
  source      text not null default 'mcp',   -- 'mcp' | 'claude-code' | 'manual'
  embedding   vector,                          -- per-project dim (like chunks); null if not embedded
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index memories_project_idx on public.memories(project_id);

alter table public.memories enable row level security;
create policy "owner full access" on public.memories
  for all using (exists (select 1 from public.projects p
                         where p.id = project_id and p.owner_id = auth.uid()));
```

- `embedding` is the dimensionless `vector` type (matches `chunks`): every
  project's vectors share one dimension, filtered by `project_id`.
- Add a `Memory` model to `backend/app/models.py`.

## Backend endpoints

Reuse: `require_api_key` (public), `get_owned_project` (owner),
`providers.resolver.resolve_embedding_key`, `providers.registry.get_embedder`,
`services.retrieval.retrieve`.

### Public (MCP, `oreag_sk_` key)
- `POST /v1/projects/{id}/memory` — body `{content, tags?, pinned?, source?}`.
  Resolve embedding key → embed `content` → insert. Returns
  `{id, content, tags, pinned, source, created_at}`.
- `POST /v1/projects/{id}/memory/search` — body `{query, top_k?}` (default 5,
  max 20). Embed query → cosine search over the project's memories with a
  non-null embedding → return `[{id, content, tags, similarity, created_at}]`.
- `GET /v1/projects/{id}/memory/recent?limit=` — default 10, max 50. Returns
  **pinned first, then most recent** entries (no embedding needed).
- `DELETE /v1/projects/{id}/memory/{memory_id}` — 204.
- `POST /v1/projects/{id}/retrieve` — body `{query, top_k?}`. Retrieval-only over
  **documents**: reuse `retrieval.retrieve` → return
  `[{filename, page_number, chunk_index, content, similarity}]`. Needs only the
  embedding key (no LLM). Returns `[]` if the project has no indexed chunks.
- `POST /v1/projects/{id}/query` — **already exists** (full RAG answer + sources).

### Owner (dashboard, JWT)
- `GET /api/projects/{id}/memory?limit=&offset=` — list for the Memory tab.
- `PATCH /api/projects/{id}/memory/{memory_id}` — `{pinned}` toggle (optional MVP).
- `DELETE /api/projects/{id}/memory/{memory_id}`.

### Pydantic schemas (`schemas.py`)
`MemoryCreate {content: str (1..8000), tags: list[str] = [], pinned=False, source="mcp"}`,
`MemoryOut {id, content, tags, pinned, source, created_at}`,
`MemorySearchRequest {query, top_k?}`, `MemorySearchResult (MemoryOut + similarity)`,
`RetrieveRequest {query, top_k?}` (reuse `SourceChunk` for results).

## MCP server (`mcp-server/`, Python + FastMCP)

A standalone package `oreag-mcp`, runnable via `uvx oreag-mcp` (or `uv run`
locally). Config via env: `OREAG_API_KEY` (project `oreag_sk_` key), `OREAG_API_BASE`
(default `https://oreag.onrender.com`). Added with `claude mcp add` or `.mcp.json`.

Tools (each a thin HTTPS call to the endpoints above):
| Tool | Endpoint |
|---|---|
| `save_memory(content, tags?, pinned?)` | `POST /v1/.../memory` |
| `search_memory(query, limit?)` | `POST /v1/.../memory/search` |
| `list_recent_memory(limit?)` | `GET /v1/.../memory/recent` |
| `delete_memory(id)` | `DELETE /v1/.../memory/{id}` |
| `search_docs(query, top_k?)` | `POST /v1/.../retrieve` |
| `ask_docs(question)` | `POST /v1/.../query` |

Typical session: bootstrap with `list_recent_memory` → `search_docs` / `search_memory`
during work → `save_memory` for new decisions.

## Error handling

- Missing/invalid key → **401** (existing `require_api_key`).
- `content` > 8000 chars → **422**.
- **No embedding key (BYOK) on save:** store the entry anyway with
  `embedding = null` (never lose a memory) and include a `warning` field noting it
  won't appear in semantic search until re-embedded. `recent`/`list` still return it.
- **No embedding key on `search` / `retrieve`:** can't embed the query → **503**
  with a clear message (these operations require embedding).
- Embedding provider call fails on save → same as no-key: store with null embedding,
  log the exception.
- Unknown `memory_id` on delete → **404**.

## Testing (TDD — failing test first)

Backend (`backend/tests/test_units.py` + a DB-backed verify script as needed):
- `memory/*` and `retrieve` return **401** without a valid API key.
- Save persists the row and calls the resolver+embedder (mock embedder); stored
  embedding present.
- Save with no embedding key stores `embedding = null` and returns the warning.
- Search orders results by similarity desc and excludes null-embedding rows.
- `recent` returns pinned first, then newest.
- `retrieve` returns `[]` when the project has no chunks; returns ranked chunks otherwise.
- Schemas never expose internal columns unexpectedly; `content` length bound enforced.
- Deleting a project cascades its memories (FK).

MCP server: unit-test each tool's request/response mapping against a mocked Oreag API.

## Scope

**MVP (this spec):**
1. `0007_memories.sql` + `Memory` model.
2. Public endpoints: `memory` (create), `memory/search`, `memory/recent`,
   `memory/{id}` (delete), and `retrieve`.
3. MCP server with the six tools.
4. Basic dashboard **Memory tab** (list, search, pin, delete).

**Follow-ups (separate specs):**
- Claude Code **plugin** (slash commands; auto `list_recent_memory` on session
  start, `save_memory` on session end).
- **Memory-graph integration** (memories as nodes in the existing graph view).
- **Save-time dedup/merge** of near-duplicate memories (cosine threshold).

## Reused building blocks

`require_api_key`, `get_owned_project`, `_get_project` (rag_v1),
`resolver.resolve_embedding_key`, `registry.get_embedder`, `retrieval.retrieve`,
`models.Project`, the `vector` column pattern from `chunks`, and the migration +
RLS conventions from `0001`/`0002`.
