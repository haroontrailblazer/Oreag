from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    # Session-pooler (5432) URL for DDL, where session state (SET
    # maintenance_work_mem, advisory locks) actually survives.
    # tests/apply_migrations.py uses it when set and falls back to database_url
    # otherwise. It does NOT unlock CREATE INDEX CONCURRENTLY: that also needs
    # one statement per round trip outside any transaction block, i.e. psql -
    # see the runbook in supabase/migrations/0018_hnsw_vector_indexes.sql.
    migration_database_url: str = ""

    # SQLAlchemy connection pool. Sized to sit at or below Supavisor's
    # per-tenant transaction-mode Pool Size, so waits happen here - where
    # pool_timeout fast-fails them into main.py's 503 handler - instead of
    # invisibly inside the pooler.
    db_pool_size: int = 10
    db_max_overflow: int = 10        # total client capacity 20, not 40
    db_pool_timeout: int = 5         # must stay in step with the sizes above
    db_pool_recycle: int = 1500      # drop sockets before Render NAT / Supavisor idle-kill them
    db_connect_timeout: int = 10     # libpq connect_timeout; without it a pooler outage hangs a thread
    # Escape hatch for many Render instances or a separate ingest service. Off
    # by default: with a transaction pooler idle client connections are cheap,
    # and NullPool adds a TLS+SCRAM handshake to every request and worker poll.
    db_use_null_pool: bool = False
    # Kill switch for releasing the connection during provider I/O. Verified
    # against live Supabase: with this on, a pooled connection goes checkedout
    # 1 -> 0 across the provider call and the ORM objects stay usable after.
    # False restores hold-for-the-whole-request behaviour with an env change
    # and no redeploy.
    db_release_during_provider_io: bool = True

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    storage_bucket: str = "project-files"

    jwt_mode: str = "jwks"  # "jwks" (new Supabase projects) or "hs256" (legacy)
    supabase_jwt_secret: str = ""
    supabase_jwt_aud: str = "authenticated"

    # Two-factor enforcement. On, an access token below aal2 is refused (403)
    # for any user who has a VERIFIED factor - which is what stops someone
    # lifting an aal1 token out of the browser and skipping the prompt with
    # curl. Users with no factor are unaffected, so this is safe to leave on
    # from day one; it only starts biting an account the moment that account
    # opts in. MFA_ENFORCE_AAL2=false disables it with a restart and no
    # redeploy, for the case where a bad enrolment locks people out.
    mfa_enforce_aal2: bool = True
    # How long "does this user have a factor?" is memoised per process. Short,
    # because it bounds how long a freshly enrolled factor takes to start being
    # enforced and how long a removed one keeps being demanded.
    mfa_cache_ttl_seconds: int = 60

    # BYOK: users supply their own provider keys; no shared server key is used.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    app_encryption_key: str = ""

    openai_api_key: str = ""  # deprecated - kept only so old .env files don't error
    ollama_base_url: str = "http://localhost:11434"
    # LM Studio's local OpenAI-compatible server (Developer tab -> Start server)
    lmstudio_base_url: str = "http://localhost:1234/v1"

    cors_origins: str = "http://localhost:3000,http://192.168.56.1:3000"
    # Auto-generated Vercel preview hostnames. Both ends must match, which
    # keeps unrelated origins out - but it is a SHAPE filter, not proof of
    # ownership: *.vercel.app is a shared namespace, so anyone can register
    # oreag-<anything> under their own team and satisfy it. That is tolerable
    # only because main.py sets allow_credentials=False; see the note there
    # before turning credentials on. An empty project means no preview regex is
    # emitted at all, so the default is fail-closed and only CORS_ORIGINS
    # applies.
    vercel_project: str = ""    # slug every preview hostname starts with
    vercel_scope: str = ""      # team/account slug every preview hostname ends with
    # Gates the localhost / RFC1918 branch of the origin regex. True so local
    # and LAN dev keep working with no .env change (api.ts follows
    # window.location.hostname, so LAN origins aren't in CORS_ORIGINS).
    # Set CORS_ALLOW_LOCAL_NETWORK=false in the production environment, where
    # no browser should ever be calling the API from a private address.
    cors_allow_local_network: bool = True
    # Access-Control-Expose-Headers (comma-separated). Retry-After is part of
    # the documented 429 contract but is unreadable by cross-origin JS today.
    cors_expose_headers: str = "Retry-After"
    # Access-Control-Allow-Credentials. False is what makes a mistakenly
    # allowed origin harmless, because the preview regex over the shared
    # *.vercel.app namespace is a SHAPE filter and cannot prove ownership.
    # Turning this on while VERCEL_PROJECT/VERCEL_SCOPE are set is refused at
    # startup by main.py rather than merely discouraged - see the guard there.
    cors_allow_credentials: bool = False

    max_upload_bytes: int = 50 * 1024 * 1024

    # Guards for the public (API-key) ingest route /v1/projects/{id}/files.
    # Owner/dashboard uploads are NOT limited by these.
    max_files_per_upload: int = 20         # files accepted in one request
    max_files_per_project: int = 1000      # total files a project may hold
    upload_rate_per_minute: int = 60       # files ingested per project per minute

    # Public /v1 rate limits (per minute, fixed window; Redis-shared when
    # configured). Two scopes stack: each key has a budget AND the project's
    # keys share a project budget, so one busy integration can't starve the
    # rest. "heavy" covers the most expensive endpoints (/explore,
    # /memory-graph); everything else uses the standard budget.
    rate_limit_enabled: bool = True
    query_rate_per_minute_per_key: int = 120
    query_rate_per_minute_per_project: int = 300
    heavy_rate_per_minute_per_key: int = 10
    heavy_rate_per_minute_per_project: int = 20
    # /explore hop budget for API-key callers (each hop multiplies exact
    # vector scans; the dashboard is not clamped).
    explore_max_hops_api: int = 1
    # Memories had NO quota (files cap at 1000/project) - any key could grow
    # the table and embedding spend without bound.
    max_memories_per_project: int = 2000

    # Durable ingestion queue (the files table is the queue; see
    # services/ingest_queue.py). Worker threads run in the web process today;
    # a dedicated worker service can run the same loop unchanged.
    ingest_worker_count: int = 2
    ingest_poll_seconds: float = 3.0
    ingest_lease_seconds: int = 1800       # a dead worker's file re-queues after this
    ingest_max_attempts: int = 3           # then failed permanently (chunks dropped)

    # Retention: query_logs and usage_events are append-only (one row per
    # request); prune past this horizon so the dashboard's aggregates stay
    # bounded. Expired semantic-cache rows are swept on the same schedule.
    log_retention_days: int = 90
    maintenance_interval_seconds: int = 6 * 3600

    # Audio ingestion: BYOK transcription through the uploader's own provider
    # keys - every STT-capable provider they hold a key for is tried in order
    # (own answer-model provider first): OpenAI Whisper, Gemini, Groq, Mistral
    # Voxtral, Sarvam Saarika. MarkItDown's free Google Web Speech endpoint
    # (short clips only) runs only when the whole chain yields nothing. This
    # setting picks the OpenAI model used in that chain.
    audio_transcription_model: str = "whisper-1"

    # "Brain": blend relevant agent memories into RAG answers, and link memories
    # into the memory graph alongside document chunks (same embedding space).
    rag_memory_blend_k: int = 4            # max memories blended into one answer
    rag_memory_min_similarity: float = 0.35

    # Hybrid retrieval: fuse semantic (pgvector) and lexical (Postgres
    # full-text) rankings with RRF, so exact terms (error codes, names, IDs)
    # hit alongside meaning matches. Degrades to semantic-only automatically
    # if the full-text column is missing (migration 0012 not applied).
    hybrid_search_enabled: bool = True

    # Approximate vector search (HNSW). The master kill switch: false forces
    # every vector search back onto today's exact SQL without dropping an index
    # or shipping code. Safe to default True because three further gates
    # (pgvector >= 0.8, index present and valid, project large enough) mean
    # dev, tests and every small tenant never reach the ANN path.
    vector_ann_enabled: bool = True
    # Project size below which the exact scan wins outright: ~20k x 1536 float4
    # is a few ms of distance arithmetic plus a bounded bitmap heap read, which
    # ANN can't beat and can only lose recall against. Read from a
    # per-(project, content_version) memoized sum(files.chunk_count).
    vector_ann_min_chunks: int = 20000
    # The recall gate. A global HNSW index must post-filter by project_id, so
    # recall depends on the project's SHARE of indexed rows, not its size. At
    # 2% share with max_scan_tuples 40000 a k=20 query expects ~800 in-project
    # candidates inside the scan budget - a ~40x margin. Below this, exact.
    vector_ann_min_project_share: float = 0.02
    # hnsw.iterative_scan - relaxed rather than strict because the rewritten
    # SQL already re-sorts the <=20 returned rows in an outer ORDER BY, so we
    # get strict ordering at relaxed cost. 'off' tests raw post-filter behaviour.
    vector_ann_iterative_scan: str = "relaxed_order"
    # hnsw.ef_search on the ANN path only (pgvector default 40). Must exceed
    # the LIMIT with headroom for the project_id post-filter; top_k caps at 20.
    vector_ann_ef_search: int = 100
    # hnsw.max_scan_tuples (pgvector 0.8 default 20000). Bounds the worst-case
    # iterative scan so a mis-gated query degrades to a bounded cost rather
    # than a full index walk; doubled because our post-filter is a tenant filter.
    vector_ann_max_scan_tuples: int = 40000
    # How long the pgvector-version / index-existence / reltuples probe is
    # cached per process: one round trip per 5 minutes, a newly built index
    # takes effect without a restart, and a dropped or invalidated index can
    # only be wrongly assumed present for this long.
    vector_ann_capability_ttl_seconds: int = 300

    # Agentic retrieval (explore_brain): graph-aware traversal of the brain.
    explore_seeds_per_type: int = 6        # top chunks + top memories to seed from
    explore_fanout: int = 4                # neighbours expanded per node per hop
    explore_max_nodes: int = 50            # subgraph size cap

    # Agentic query loop (run_query): decompose broad/exam-style questions, gather
    # a wide context over several rounds, and only ask the human to clarify when
    # grounding is genuinely too thin - instead of refusing with "no reference".
    agentic_max_subqueries: int = 5        # sub-queries a broad question is split into
    agentic_max_clarifying: int = 3        # clarifying questions when escalating
    agentic_min_similarity: float = 0.2    # a source must clear this to count as grounding
    agentic_min_strong: int = 1            # this many grounding sources = enough to answer
    agentic_max_rounds: int = 2            # retrieval rounds before escalating to a human

    # CAG (Cache-Augmented Generation): cache answers so a repeated question isn't
    # re-retrieved and re-generated, and simultaneous identical asks compute once.
    # Keyed on project+model+top_k+content+question, so new files/memories
    # invalidate it. Entries also expire after the TTL.
    query_cache_enabled: bool = True
    query_cache_ttl_seconds: int = 3600    # L1 exact-match cache - 1 hour
    query_cache_max_entries: int = 512     # in-memory LRU cap across all projects

    # Semantic cache (L2, pgvector): also serve SIMILAR questions from cache,
    # not just exact repeats - "what is deep learning" answers "explain deep
    # learning to me" without re-running retrieval + the LLM. A cached answer
    # is reused when cosine similarity clears the threshold; below it, the
    # query runs for real. Scoped per project + models + content signature.
    semantic_cache_enabled: bool = True
    semantic_cache_min_similarity: float = 0.75
    semantic_cache_ttl_seconds: int = 86400  # L2 semantic cache - 24 hours

    # Optional Redis: when set, the CAG cache AND conversation memory use Redis
    # (shared across workers, survives restarts); otherwise they fall back to an
    # in-memory store, so local dev needs no Redis running.
    redis_url: str = ""

    # Conversation memory (server-side, keyed by conversation_id): lets a follow-up
    # like "summarize that" be rewritten against the previous turns before retrieval.
    conversation_ttl_seconds: int = 86400  # 24h - how long a thread is remembered
    conversation_max_turns: int = 20       # turns retained per conversation
    conversation_history_turns: int = 6    # recent turns fed to the condense step


settings = Settings()
