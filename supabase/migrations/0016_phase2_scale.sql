-- Phase 2 scale groundwork (all additive / idempotent).
--
-- 1. projects.content_version - monotonic counter bumped on any chunk/memory
--    write. Replaces the per-request "chunk_count:memory_count" cache
--    signature (two COUNT(*) per query, stale on same-count edits): the
--    version is a single already-loaded column, correct on in-place edits.
alter table projects add column if not exists content_version bigint not null default 0;

-- 2. Durable ingestion queue: the files table IS the queue. Workers claim
--    pending rows with FOR UPDATE SKIP LOCKED, take a lease, and bump
--    attempts; a crashed worker's lease expires and the file is re-queued
--    instead of the old boot-time bulk-fail.
alter table files add column if not exists attempts integer not null default 0;
alter table files add column if not exists lease_expires_at timestamptz;
create index if not exists files_queue_idx on files (status, created_at)
  where status in ('pending', 'processing');

-- 3. Operator kill switch: an account listed here has ALL its projects'
--    public API traffic rejected (403), regardless of per-project suspension.
--    Rows are inserted manually by the operator; there is no UI.
create table if not exists suspended_accounts (
  owner_id uuid primary key,
  reason text,
  created_at timestamptz not null default now()
);
alter table suspended_accounts enable row level security;

-- 4. Usage metering: one row per public /v1 request. Previously only /query
--    wrote any usage record - /retrieve, /explore and /memory-graph were
--    invisible (unbillable, unattributable). token counts are nullable until
--    providers report them.
create table if not exists usage_events (
  id bigint generated always as identity primary key,
  owner_id uuid not null,
  project_id uuid not null,
  api_key_id uuid,
  endpoint text not null,
  latency_ms integer,
  prompt_tokens integer,
  completion_tokens integer,
  created_at timestamptz not null default now()
);
create index if not exists usage_events_project_idx on usage_events (project_id, created_at);
create index if not exists usage_events_owner_idx on usage_events (owner_id, created_at);
alter table usage_events enable row level security;
