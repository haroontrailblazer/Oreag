# Oreag — RAG as a Service

Build a RAG (Retrieval-Augmented Generation) over your own PDFs from a web UI:
upload documents, choose chunking and embedding settings, and get a dedicated
API endpoint + API key to query your knowledge base from any app. Add files or
re-index ("update memory") at any time from the dashboard.

## Architecture

- **frontend/** — Next.js (App Router, TypeScript, Tailwind, shadcn/ui). Auth via Supabase.
- **backend/** — FastAPI. Ingestion (PyMuPDF → chunking → embeddings → pgvector), retrieval, generation, API-key management.
- **supabase/** — SQL migrations: Postgres metadata tables, pgvector `chunks`, RLS policies, private storage bucket.
- **legacy/** — the original prototype, kept for reference.

Providers: **OpenAI** (embeddings + chat), **Ollama** (local, optional), **sentence-transformers** (local embeddings, optional).

## Setup (Windows)

### 1. Supabase

Create a project at [supabase.com](https://supabase.com), then run every file in
`supabase/migrations/` in order (SQL Editor): `0001_init.sql`, `0002_rls.sql`,
`0003_markitdown_memory_graph.sql`.

### 2. Backend

```powershell
cd backend
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then fill in the values
uvicorn app.main:app --reload
```

API runs at http://localhost:8000 (interactive docs at /docs).

Optional local embeddings (downloads PyTorch, ~2.5 GB):

```powershell
pip install -r requirements-local.txt
```

Optional local LLM: install [Ollama](https://ollama.com) and pull a model,
e.g. `ollama pull llama3.1` and `ollama pull nomic-embed-text`.

### 3. Frontend

```powershell
cd frontend
npm install
copy .env.example .env.local   # then fill in the values
npm run dev
```

App runs at http://localhost:3000.

### Accessing from another device on your network (LAN)

`next dev` already listens on all interfaces, so the frontend is reachable at
`http://<your-lan-ip>:3000`. The frontend automatically calls the backend at the
same host, so just start the backend on all interfaces too:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

No env changes are needed — the app follows whatever host you open it on, and the
backend's CORS already allows localhost and any private-LAN origin.

## Using your generated RAG API

Every project gets API keys (Project → API tab). Query it from anywhere:

```bash
curl -X POST http://localhost:8000/v1/projects/<project-id>/query \
  -H "Authorization: Bearer oreag_sk_..." \
  -H "Content-Type: application/json" \
  -d '{"question": "What does the handbook say about onboarding?"}'
```

Response: `{ "answer": "...", "sources": [{ "filename", "page_number", "content", "similarity" }], "model", "latency_ms" }`
