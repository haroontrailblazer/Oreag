# Oreag - System & Flow Diagrams

> A structured redesign of the system architecture and the four core flows.
> **Same logic as the source diagrams** - every node, branch, and path is preserved -
> reorganised into a consistent visual grammar with colour-coded tiers, typed
> connectors, and inline endpoint annotations.

All diagrams are [Mermaid](https://mermaid.js.org/) and render directly on GitHub,
GitLab, VS Code, Obsidian, and most Markdown viewers.

---

## Legend

| Connector | Meaning |
|---|---|
| `A ==> B` (thick) | Primary request path |
| `A --> B` (solid) | Data read / write · internal call |
| `A -.-> B` (dotted) | Authentication |

| Tier | Colour |
|---|---|
| Client | 🟦 sky |
| Coding agents · MCP | 🩷 rose |
| Presentation · Vercel | ⬜ zinc |
| Application · Render · FastAPI | 🟩 emerald |
| Data · Supabase | 🟢 green |
| AI providers · BYOK / local | 🟪 violet |

**Shapes** - `([stadium])` start/end · `[process]` · `{decision}` · `{{task}}` · `[(datastore)]` · `[[storage]]`

### Contents

| # | Diagram | Type |
|---|---|---|
| 1 | [System Architecture](#1-system-architecture) | layered flowchart |
| 2 | [Document Ingestion](#2-document-ingestion--write-path) | write path |
| 3 | [Query / RAG](#3-query--rag--read-path) | sequence |
| 4 | [BYOK Key Resolution](#4-byok-key-resolution) | decision tree |
| 5 | [Authentication & Email Confirmation](#5-authentication--email-confirmation) | sequence |
| 6 | [Agent Memory & Docs Recall (MCP)](#6-agent-memory--docs-recall-mcp) | sequence |

---

## 1. System Architecture

Five colour-coded tiers from browser to AI provider. Thick arrows are primary
request paths; solid arrows are data/internal calls; dotted arrows are
authentication.

```mermaid
flowchart TB
    subgraph client["CLIENT TIER"]
        direction LR
        Browser["Web Browser<br/>Dashboard UI"]
        ExtApp["External App<br/>your code"]
    end

    subgraph agents["CODING AGENTS"]
        direction LR
        Agent["Claude Code · Codex · Claude"]
        MCP["Oreag MCP server<br/>memory + docs tools"]
    end

    subgraph edge["PRESENTATION TIER · Vercel"]
        direction LR
        Next["Next.js 16 · App Router<br/>React 19 · Tailwind · shadcn/ui · SWR"]
        AuthRt["Route Handlers<br/>/auth/confirm · /auth/callback"]
    end

    subgraph appt["APPLICATION TIER · Render · FastAPI"]
        API["Dashboard API<br/>/api/*"]
        PublicAPI["Public API<br/>/v1/* - query · retrieve · memory"]
        subgraph services["Domain Services"]
            direction LR
            Ingest["Ingestion<br/>background tasks"]
            Retrieve["Retrieval"]
            Generate["Generation"]
            Agentic["Agentic query loop<br/>depth · sub-queries · clarify"]
            QCache["Query cache (CAG)"]
            Memory["Memory<br/>save · search · recent"]
            MemGraph["Memory Graph"]
        end
        Resolver["BYOK Key Resolver<br/>Fernet decrypt"]
        Registry["Provider Registry"]
    end

    subgraph datat["DATA TIER · Supabase"]
        direction LR
        Auth["Auth<br/>JWT / JWKS"]
        PG[("Postgres + pgvector<br/>projects · files · chunks · memories<br/>provider_keys · api_keys · query_logs")]
        Store[["Storage<br/>project-files bucket"]]
        Redis[("Redis · optional<br/>CAG cache + conversation memory<br/>falls back to in-memory")]
    end

    subgraph ai["AI PROVIDERS · BYOK / local"]
        direction LR
        OpenAI["OpenAI"]
        Gemini["Google Gemini"]
        Anthropic["Anthropic Claude"]
        Sarvam["Sarvam AI"]
        Ollama["Ollama · local"]
    end

    %% --- primary request paths ---
    Browser ==>|HTTPS| Next
    Next ==>|"Bearer JWT"| API
    ExtApp ==>|"Bearer oreag_sk_…"| PublicAPI
    Agent ==> MCP
    MCP ==>|"Bearer oreag_sk_…"| PublicAPI

    %% --- authentication (dotted) ---
    Browser -.->|"sign in / sign up"| Auth
    AuthRt  -.->|verifyOtp| Auth
    API     -.->|"validate JWT · JWKS"| Auth

    %% --- application fan-out ---
    API --> Ingest & Retrieve & Generate & Agentic & Memory & MemGraph
    PublicAPI --> Retrieve & Generate & Agentic & Memory & MemGraph

    %% --- agentic query loop + CAG cache ---
    Agentic --> QCache & Retrieve & Generate
    QCache -->|"cache + conversation"| Redis

    %% --- BYOK resolution & provider calls ---
    Ingest & Retrieve & Generate & Memory --> Resolver
    Resolver -->|"decrypt keys"| PG
    Resolver --> Registry
    Registry --> OpenAI & Gemini & Anthropic & Sarvam & Ollama

    %% --- data reads / writes ---
    Ingest   -->|"raw + markdown"| Store
    Ingest   -->|"chunks + vectors"| PG
    Retrieve -->|"cosine search"| PG
    Generate --> PG
    Memory   -->|"embed-on-save · search"| PG
    MemGraph --> PG

    classDef tClient fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
    classDef tAgent  fill:#fce7f3,stroke:#db2777,color:#831843
    classDef tEdge   fill:#f4f4f5,stroke:#18181b,color:#18181b
    classDef tApp    fill:#d1fae5,stroke:#059669,color:#064e3b
    classDef tData   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef tAI     fill:#ede9fe,stroke:#7c3aed,color:#4c1d95

    class Browser,ExtApp tClient
    class Agent,MCP tAgent
    class Next,AuthRt tEdge
    class API,PublicAPI,Ingest,Retrieve,Generate,Agentic,QCache,Memory,MemGraph,Resolver,Registry tApp
    class Auth,PG,Store,Redis tData
    class OpenAI,Gemini,Anthropic,Sarvam,Ollama tAI
```

---

## 2. Document Ingestion · write path

An uploaded file is stored, a row is created, then a background task
**converts → chunks → embeds → writes vectors**. Any exception during embedding
flips the file to `failed`.

```mermaid
flowchart LR
    A(["Upload<br/>PDF · DOCX · …"]) -->|"raw file"| B["Supabase Storage<br/>raw file"]
    A --> C["File row created<br/>status: pending"]
    C --> D{{"Background task<br/>ingest_file()"}}
    D --> E["Convert to Markdown<br/>PyMuPDF · MarkItDown"]
    E --> F["Chunk<br/>RecursiveCharacterTextSplitter"]
    F --> G["Embed in batches<br/>resolved BYOK key"]
    G --> H[("pgvector chunks<br/>content + embedding")]
    H --> I(["status: indexed<br/>project status recomputed"])
    G -.->|exception| J(["status: failed<br/>error shown in Files tab"])

    classDef start fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef proc  fill:#f1f5f9,stroke:#475569,color:#0f172a
    classDef task  fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef store fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef ok    fill:#d1fae5,stroke:#059669,color:#064e3b
    classDef bad   fill:#fee2e2,stroke:#dc2626,color:#7f1d1d

    class A start
    class B,H store
    class C,E,F,G proc
    class D task
    class I ok
    class J bad
```

---

## 3. Query / RAG · read path

A caller hits either endpoint (dashboard `/api/projects/{id}/query` or public
`/v1/projects/{id}/query` - both run the same `run_query()`). When a
`conversation_id` is present the follow-up is condensed to a standalone question;
the CAG cache is checked first; depth is classified; a long question is decomposed
into sub-queries and each is retrieved + merged; a sufficiency check either grounds
a depth-aware answer or returns a human clarification (with a retry/broaden loop);
then the answer is cached, the conversation turn appended, and `query_logs` written.

```mermaid
sequenceDiagram
    autonumber
    actor C as Caller
    participant API as FastAPI · /query
    participant Q as run_query
    participant AG as Agentic loop
    participant CC as Redis · cache + conversation
    participant R as Retrieval
    participant DB as pgvector
    participant L as LLM

    C->>+API: POST /projects/{id}/query
    Note over API,DB: validate auth (JWT or API key) · check indexed content
    opt invalid auth or no chunks
        API-->>C: 401 / 409
    end
    API->>+Q: run_query(question, top_k, conversation_id?)

    opt conversation_id present
        Q->>CC: load prior turns
        CC-->>Q: history
        Q->>L: condense follow-up → standalone question
        L-->>Q: standalone question
    end

    Q->>CC: CAG cache lookup (project · models · top_k · content sig · question)
    alt cache hit
        CC-->>Q: cached answer (no retrieval · no LLM)
    else cache miss
        Q->>AG: detect_depth(question) → short | long
        opt long question
            AG->>L: plan_subqueries() - decompose (literal question kept)
            L-->>AG: sub-queries
        end
        loop retrieve + merge · max 2 rounds
            AG->>R: retrieve each sub-query (top_k)
            R->>DB: nearest-neighbour search
            DB-->>R: top-k chunks
            R-->>AG: sources
            Note over AG: merge + de-dup (best similarity) · is_sufficient?
            alt grounding too thin
                Note over AG: broaden & retry
            end
        end
        alt sufficient
            AG->>L: generate depth-aware grounded answer
            L-->>AG: answer (concise short · structured long)
        else still insufficient
            Note over AG: human-in-the-loop - clarifying questions
            AG-->>Q: needs_clarification · answer = clarification prompt
        end
        AG-->>Q: answer + sources + depth + sub_queries
        Q->>CC: store in CAG cache (TTL)
    end

    opt conversation_id present
        Q->>CC: append turn (question + answer)
    end
    Q->>DB: write query_logs
    Q-->>-API: result
    API-->>-C: 200 - answer · sources · depth · sub_queries · needs_clarification · conversation_id
```

---

## 4. BYOK Key Resolution

When an embedding or LLM call needs a provider key, the resolver checks in order:
**local provider** (no key) → **per-project override** → **account-level key** →
otherwise **503**.

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

    classDef start    fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef decision fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef action   fill:#ede9fe,stroke:#7c3aed,color:#4c1d95
    classDef ok       fill:#d1fae5,stroke:#059669,color:#064e3b
    classDef bad      fill:#fee2e2,stroke:#dc2626,color:#7f1d1d

    class S start
    class Q1,Q2,Q3 decision
    class D1,D2 action
    class Use,Local ok
    class Err bad
```

---

## 5. Authentication & Email Confirmation

Sign-up branches on whether email confirmation is required; confirmation branches
on whether the OTP token is still valid.

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

---

## 6. Agent Memory & Docs Recall (MCP)

A coding-agent session connects to one project through the MCP server (project
`oreag_sk_` key) and persists / recalls memory and pulls document context across
sessions. Bootstrap at start, then save & recall during work.

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

MCP tools: `save_memory`, `search_memory`, `list_recent_memory`, `delete_memory`,
`search_docs`, `ask_docs`. Connect an agent via `mcp-server/README.md`.

---

<sub>Oreag architecture - structured diagram set · logic preserved from source.</sub>
