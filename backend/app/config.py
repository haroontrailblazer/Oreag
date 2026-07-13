from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    storage_bucket: str = "project-files"

    jwt_mode: str = "jwks"  # "jwks" (new Supabase projects) or "hs256" (legacy)
    supabase_jwt_secret: str = ""
    supabase_jwt_aud: str = "authenticated"

    # BYOK: users supply their own provider keys; no shared server key is used.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    app_encryption_key: str = ""

    openai_api_key: str = ""  # deprecated - kept only so old .env files don't error
    ollama_base_url: str = "http://localhost:11434"
    # LM Studio's local OpenAI-compatible server (Developer tab -> Start server)
    lmstudio_base_url: str = "http://localhost:1234/v1"

    cors_origins: str = "http://localhost:3000,http://192.168.56.1:3000"

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
