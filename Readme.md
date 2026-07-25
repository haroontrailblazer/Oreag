<div align="center">

# Oreag - RAG & Memory as a Service
https://playground.likec4.dev/share/foITvnUjbk/

**Turn your documents into a production-ready, queryable RAG API - with a built-in memory graph - from a web dashboard.**

![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-3FCF8E?logo=supabase&logoColor=white)
![pgvector](https://img.shields.io/badge/Postgres%20%2B%20pgvector-4169E1?logo=postgresql&logoColor=white)

</div>

---

## Overview

Oreag lets a user upload documents (PDF, DOCX, PPTX, HTML, CSV, …), tune chunking
and embedding settings, and instantly get a **dedicated, API-key-protected RAG
endpoint** to query that knowledge base from any application - plus an **agent
memory graph** derived from the same content. It is **multi-tenant** and
**bring-your-own-key (BYOK)**: each user supplies their own credentials for any
of 16 keyed providers (OpenAI, Gemini, Anthropic, Azure OpenAI, Mistral, Cohere,
and more) or runs a keyless local model (Ollama, LM Studio,
sentence-transformers), stored encrypted at rest.

## Features

- **Any document to an API** - upload, auto-convert to Markdown, chunk, embed, and serve.
- **Per-project RAG endpoint** - `POST /v1/projects/{id}/query` returns grounded answers with cited sources.
- **Agentic retrieval loop** - auto depth detection (short vs long), query decomposition for big/exam questions, multi-round retrieve-and-merge with a sufficiency check, and human-in-the-loop clarification instead of a dead "no reference".
- **Hybrid retrieval** - semantic pgvector search and lexical Postgres full-text search run together and are fused with Reciprocal Rank Fusion (RRF), so exact terms (error codes, IDs, names) embeddings fumble are still caught. Degrades to semantic-only automatically if the lexical column is missing.
- **Two-layer answer cache** - used by every query surface (playground, `/v1` API, MCP). L1 is an exact-match CAG cache in Redis (in-memory fallback, single-flight de-duplication, 5 min TTL); L2 is a semantic cache in Postgres/pgvector - a new question whose cosine similarity to an answered one is >= 0.75 is served from cache at the cost of one embedding call (1 h TTL). Both layers are scoped by project, models, top-K, and content signature, so new content or model changes invalidate automatically. Responses report `cache_layer` and `cache_similarity`.
- **Conversation memory** - server-side, keyed by an optional `conversation_id`, so follow-ups like "summarize that" are condensed into standalone questions before retrieval.
- **Agent memory graph** - a queryable graph of sections and entities derived from indexed content.
- **Agent memory (MCP)** - coding agents (Claude Code, Codex, Claude) save & recall per-project memory and pull document context through the Oreag MCP server.
- **Visualize tab** - a 3D interactive knowledge graph inside each project: the project, its files, chunks, and memories as nodes with structural and similarity edges - orbit/zoom, hover tooltips, and a click-through details panel with a "View file" action.
- **BYOK, multi-provider** - 16 keyed providers (OpenAI, Google Gemini, Anthropic, Azure OpenAI, Mistral, Cohere, Together AI, Fireworks AI, xAI Grok, Groq, DeepSeek, OpenRouter, Perplexity, Voyage AI, Jina AI, Sarvam) plus keyless local Ollama, LM Studio, and sentence-transformers. Keys encrypted with Fernet; per-account **and** per-project overrides.
- **Secure by design** - Supabase Auth (JWT/JWKS), Row-Level Security, SHA-256-hashed API keys, Fernet-encrypted provider keys.
- **Tunable** - chunk size/overlap (global or per-file), embedding model, LLM, top-K - with one-click re-index.
- **Matryoshka (MRL) dimensions** - MRL-capable embedding models (OpenAI text-embedding-3, gemini-embedding-001, Cohere embed-v4.0, Jina v3) offer multiple sizes; shrinking the same model truncates stored vectors (chunks **and** memories) in place instantly with zero re-embedding, while growing or switching models re-embeds everything.

---

## System Architecture

> Thick arrows are the primary request paths; dotted arrows are authentication. Each tier is colour-coded.

```mermaid
flowchart TB
    subgraph client["CLIENT TIER"]
        Browser["Web Browser<br/>Dashboard UI"]
        ExtApp["External App<br/>your code"]
    end

    subgraph agents["CODING AGENTS"]
        Agent["Claude Code · Codex · Claude"]
        MCP["Oreag MCP server<br/>memory + docs tools"]
    end

    subgraph edge["PRESENTATION TIER - Vercel"]
        Next["Next.js 16 · App Router<br/>React 19 · Tailwind · shadcn/ui · SWR"]
        AuthRt["Route Handlers<br/>/auth/confirm · /auth/callback"]
    end

    subgraph appt["APPLICATION TIER - Render · FastAPI"]
        API["Dashboard API<br/>/api/*"]
        PublicAPI["Public API<br/>/v1/* - query · retrieve · memory"]
        subgraph services["Domain Services"]
            Ingest["Ingestion<br/>background tasks"]
            Retrieve["Retrieval"]
            Generate["Generation"]
            Memory["Memory<br/>save · search · recent"]
            MemGraph["Memory Graph"]
        end
        Resolver["BYOK Key Resolver<br/>Fernet decrypt"]
        Registry["Provider Registry"]
    end

    subgraph datat["DATA TIER - Supabase"]
        Auth["Auth<br/>JWT / JWKS"]
        PG[("Postgres + pgvector<br/>projects · files · chunks · memories<br/>provider_keys · api_keys · query_logs<br/>semantic_query_cache")]
        Store[["Storage<br/>project-files bucket"]]
    end

    subgraph ai["AI PROVIDERS - BYOK / local"]
        Keyed["16 keyed providers<br/>OpenAI · Gemini · Anthropic · Azure OpenAI<br/>Mistral · Cohere · Together · Fireworks · xAI Grok · Groq<br/>DeepSeek · OpenRouter · Perplexity · Voyage · Jina · Sarvam"]
        Local["Keyless local<br/>Ollama · LM Studio · sentence-transformers"]
    end

    Browser ==>|HTTPS| Next
    Browser -.->|"sign in / sign up"| Auth
    AuthRt -.->|verifyOtp| Auth
    Next ==>|"Bearer JWT"| API
    ExtApp ==>|"Bearer oreag_sk_…"| PublicAPI
    Agent ==> MCP
    MCP ==>|"Bearer oreag_sk_…"| PublicAPI

    API -.->|validate JWT · JWKS| Auth
    API --> Ingest & Retrieve & Generate & Memory & MemGraph
    PublicAPI --> Retrieve & Generate & Memory & MemGraph

    Ingest & Retrieve & Generate & Memory --> Resolver
    Resolver -->|decrypt keys| PG
    Resolver --> Registry
    Registry --> Keyed & Local

    Ingest -->|raw + markdown| Store
    Ingest -->|chunks + vectors| PG
    Retrieve -->|"hybrid: cosine + full-text · RRF"| PG
    Generate --> PG
    Memory -->|embed-on-save · search| PG
    MemGraph --> PG

    classDef tClient fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
    classDef tAgent fill:#fce7f3,stroke:#db2777,color:#831843
    classDef tEdge fill:#f4f4f5,stroke:#18181b,color:#18181b
    classDef tApp fill:#d1fae5,stroke:#059669,color:#064e3b
    classDef tData fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef tAI fill:#ede9fe,stroke:#7c3aed,color:#4c1d95

    class Browser,ExtApp tClient
    class Agent,MCP tAgent
    class Next,AuthRt tEdge
    class API,PublicAPI,Ingest,Retrieve,Generate,Memory,MemGraph,Resolver,Registry tApp
    class Auth,PG,Store tData
    class Keyed,Local tAI
```

---

## Core Flows

### 1. Document Ingestion (write path)

```mermaid
flowchart LR
    A(["Upload<br/>PDF · DOCX · …"]) --> B["Supabase Storage<br/>raw file"]
    A --> C["File row created<br/>status: pending"]
    C --> D{{"Background task<br/>ingest_file()"}}
    D --> E["Convert to Markdown<br/>PyMuPDF / MarkItDown"]
    E --> F["Chunk<br/>RecursiveCharacterTextSplitter"]
    F --> G["Embed in provider-sized batches<br/>OpenAI/Gemini 100 · Ollama 32 · ST 64<br/>resolved BYOK key"]
    G --> H[("pgvector chunks<br/>content + embedding")]
    H --> I(["status: indexed<br/>project status recomputed"])
    G -.->|exception| J(["status: failed<br/>error shown in Files tab"])

    classDef start fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef proc fill:#f1f5f9,stroke:#475569,color:#0f172a
    classDef task fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef store fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef ok fill:#d1fae5,stroke:#059669,color:#064e3b
    classDef bad fill:#fee2e2,stroke:#dc2626,color:#7f1d1d

    class A start
    class B,H store
    class C,E,F,G proc
    class D task
    class I ok
    class J bad
```

### 2. Query / RAG (read path)

```mermaid
sequenceDiagram
    autonumber
    actor C as Caller
    participant API as FastAPI · /v1
    participant CV as Conversation memory
    participant QC as Answer cache (L1 + L2)
    participant AG as Agentic loop
    participant R as Retrieval
    participant DB as pgvector
    participant L as LLM

    C->>+API: POST /v1/projects/{id}/query (+ optional conversation_id)
    Note over API,DB: validate API key (SHA-256) and check indexed content
    opt invalid key or no chunks
        API-->>C: 401 / 409
    end

    opt conversation_id present
        API->>CV: load prior turns
        CV-->>API: history
        API->>L: condense_question() → standalone question
    end

    API->>QC: L1 exact lookup, then L2 semantic (cosine >= 0.75)<br/>scoped by project · models · top_k · content sig
    alt cache hit (L1 or L2)
        QC-->>API: cached answer (no retrieval, no LLM)
    else double miss (single-flight)
        API->>AG: detect_depth(question) → short | long
        opt long
            AG->>L: plan_subqueries() (literal question kept)
        end
        loop up to agentic_max_rounds
            AG->>R: retrieve every sub-query
            R->>DB: hybrid search - pgvector + full-text, fused with RRF
            DB-->>R: top-k chunks
            R-->>AG: sources
            AG->>AG: merge + de-duplicate · is_sufficient()
        end
        alt sufficient
            AG->>L: depth-aware answer (long = structured · short = strict)
            L-->>AG: grounded answer
        else still insufficient
            AG-->>API: needs_clarification + clarification_questions
        end
        AG-->>API: answer or clarification
        API->>QC: store answer in L1 + L2 (question embedding)
    end

    opt conversation_id present
        API->>CV: save turn (question + answer)
    end
    API->>DB: write query_logs
    API-->>-C: 200 - answer + sources + depth + cache_layer + latency
```

### 3. BYOK Key Resolution

```mermaid
flowchart TD
    S(["Need a provider key<br/>for embedding or LLM"]) --> Q1{"Provider needs a key?<br/>Ollama / ST are local"}
    Q1 -->|"No · local"| Local(["Use local provider<br/>no key required"])
    Q1 -->|Yes| Q2{"Per-project<br/>override set?"}
    Q2 -->|Yes| D1["Decrypt project key<br/>Fernet · projects table"]
    Q2 -->|No| Q3{"Account-level key<br/>for this provider?"}
    Q3 -->|Yes| D2["Decrypt account key<br/>Fernet · provider_keys"]
    Q3 -->|No| Err(["HTTP 503<br/>add a key in Settings → API keys"])
    D1 --> Use(["Call provider with key"])
    D2 --> Use
    Local --> Use

    classDef start fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef decision fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef action fill:#ede9fe,stroke:#7c3aed,color:#4c1d95
    classDef ok fill:#d1fae5,stroke:#059669,color:#064e3b
    classDef bad fill:#fee2e2,stroke:#dc2626,color:#7f1d1d

    class S start
    class Q1,Q2,Q3 decision
    class D1,D2 action
    class Use,Local ok
    class Err bad
```

### 4. Authentication & Email Confirmation

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant FE as Next.js · Vercel
    participant SB as Supabase Auth
    participant M as Email

    Note over U,SB: Sign up
    U->>+FE: submit email + password
    FE->>+SB: auth.signUp()
    alt email confirmation required
        SB->>M: send branded confirm email
        SB-->>FE: session = null
        FE-->>U: "Check your inbox"
    else confirmations disabled
        SB-->>FE: active session
        FE-->>U: redirect → /dashboard
    end
    deactivate SB
    deactivate FE

    Note over U,SB: Confirm
    M-->>U: click link → /auth/confirm?token_hash
    U->>+FE: GET /auth/confirm
    FE->>+SB: verifyOtp(token_hash, type)
    alt token valid
        SB-->>FE: session (Set-Cookie)
        FE-->>U: 302 → /dashboard
    else expired or invalid
        SB-->>FE: error
        FE-->>U: 302 → /login?error
    end
    deactivate SB
    deactivate FE
```

### 5. Agent Memory & Docs Recall (MCP)

```mermaid
sequenceDiagram
    autonumber
    actor A as Coding Agent
    participant MCP as Oreag MCP server
    participant API as FastAPI · /v1
    participant M as Memory service
    participant DB as pgvector

    Note over A,DB: Session start - bootstrap
    A->>MCP: list_recent_memory()
    MCP->>API: GET /memory/recent (Bearer oreag_sk_…)
    API->>M: recent_memories (pinned first)
    M->>DB: SELECT ORDER BY pinned, created_at
    DB-->>M: entries
    M-->>MCP: entries
    MCP-->>A: context to orient the session

    Note over A,DB: During work - save & recall
    A->>MCP: save_memory("decision: …")
    MCP->>API: POST /memory
    API->>M: embed-on-save (resolved key)
    M->>DB: INSERT memory + embedding
    A->>MCP: search_memory("how does auth work?")
    MCP->>API: POST /memory/search
    API->>M: embed query → cosine search
    M->>DB: ORDER BY embedding <=> qvec
    DB-->>M: relevant entries
    M-->>A: recalled memories
    A->>MCP: search_docs("payment flow")
    MCP->>API: POST /retrieve
    API-->>A: relevant document chunks
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | Next.js 16 (App Router), React 19, TypeScript, Tailwind v4, shadcn/ui, SWR |
| **Backend** | FastAPI, SQLAlchemy 2, Pydantic, Uvicorn |
| **Database** | Supabase Postgres + `pgvector` |
| **Auth** | Supabase Auth (JWT / JWKS) |
| **Storage** | Supabase Storage (private bucket) |
| **Cache / conversation memory** | L1: Redis (optional, via `REDIS_URL`) with in-memory fallback · L2: semantic cache in Postgres + `pgvector` |
| **AI providers** | 16 keyed: OpenAI · Google Gemini · Anthropic · Azure OpenAI · Mistral · Cohere · Together AI · Fireworks AI · xAI Grok · Groq · DeepSeek · OpenRouter · Perplexity · Voyage AI · Jina AI · Sarvam · keyless local: Ollama · LM Studio · sentence-transformers |
| **Ingestion** | PyMuPDF, MarkItDown, LangChain text splitters |
| **Crypto** | `cryptography` (Fernet) for BYOK keys |
| **Agent integration** | MCP server (Python, FastMCP) - `mcp-server/` |
| **Hosting** | Vercel (frontend) · Render (backend) · Supabase (data) |

## Repository Structure

```
Oreag/
├── frontend/                 # Next.js dashboard (Vercel)
│   └── src/
│       ├── app/              # routes: (auth), (dashboard), auth/confirm, auth/callback
│       ├── components/       # UI, project tabs, settings (provider keys)
│       └── lib/              # api client, supabase client/server, types
├── backend/                  # FastAPI service (Render)
│   └── app/
│       ├── routers/          # projects, files, keys, provider_keys, account, memory, meta, playground, rag_v1, memory_graph
│       ├── providers/        # registry, resolver, openai/gemini/anthropic/sarvam/ollama/st + openai_compat (Azure, Mistral, Cohere, Together, xAI, Groq, …)
│       ├── services/         # ingestion, retrieval, generation, query, agentic, query_cache, semantic_cache, explore, memory, memory_graph, conversion, storage
│       ├── crypto.py         # Fernet encrypt/decrypt for BYOK keys
│       └── models.py, schemas.py, config.py, db.py, main.py
├── mcp-server/               # Oreag MCP server (FastMCP) - agent memory + docs tools
├── supabase/
│   ├── migrations/           # 0001…0012 (tables, RLS, pgvector, provider_keys, memories, semantic cache, hybrid search)
│   └── templates/            # branded auth email templates
├── render.yaml               # backend blueprint
├── FLOW.md                   # architecture + flow diagrams
└── DEPLOY.md                 # production deploy guide
```

---
