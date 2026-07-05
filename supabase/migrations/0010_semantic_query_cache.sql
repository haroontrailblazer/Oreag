-- Semantic query cache (L2, pgvector). The Redis CAG cache only hits when the
-- question text matches exactly; this layer catches *similar* questions - the
-- cached question's embedding is compared by cosine similarity, and anything
-- at or above the configured threshold (default 0.75) is served from cache
-- instead of paying for retrieval + the LLM again.
--
-- Rows are scoped to everything that could change the answer (project, both
-- model configs, top_k, and the indexed-content signature) and expire by TTL.
-- embedding is dimension-less on purpose, like chunks/memories: each project
-- chooses its own embedding model and lookups always filter by project first.

create table if not exists semantic_query_cache (
  id                 bigserial primary key,
  project_id         uuid not null references projects(id) on delete cascade,
  question           text not null,
  embedding          vector not null,
  content_signature  text not null,
  embedding_provider text not null,
  embedding_model    text not null,
  llm_provider       text not null,
  llm_model          text not null,
  top_k              int  not null,
  result             jsonb not null,
  created_at         timestamptz not null default now(),
  expires_at         timestamptz not null
);

create index if not exists semantic_query_cache_lookup_idx
  on semantic_query_cache (project_id, expires_at);
