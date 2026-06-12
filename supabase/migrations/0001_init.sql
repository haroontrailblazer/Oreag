create extension if not exists vector;

create table public.projects (
  id                   uuid primary key default gen_random_uuid(),
  owner_id             uuid not null references auth.users(id) on delete cascade,
  name                 text not null,
  description          text,
  chunk_size           int  not null default 1000 check (chunk_size between 100 and 8000),
  chunk_overlap        int  not null default 200  check (chunk_overlap >= 0 and chunk_overlap < chunk_size),
  embedding_provider   text not null default 'openai',
  embedding_model      text not null default 'text-embedding-3-small',
  embedding_dimensions int  not null default 1536,
  llm_provider         text not null default 'openai',
  llm_model            text not null default 'gpt-4o-mini',
  top_k                int  not null default 5 check (top_k between 1 and 20),
  status               text not null default 'empty',
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
create index projects_owner_idx on public.projects(owner_id);

create table public.files (
  id           uuid primary key default gen_random_uuid(),
  project_id   uuid not null references public.projects(id) on delete cascade,
  filename     text not null,
  storage_path text not null,
  size_bytes   bigint,
  page_count   int,
  chunk_count  int not null default 0,
  status       text not null default 'pending',
  error        text,
  created_at   timestamptz not null default now(),
  indexed_at   timestamptz
);
create index files_project_idx on public.files(project_id);

-- embedding has no fixed dimension on purpose: each project chooses its own
-- embedding model, and queries always filter by project_id first so vectors of
-- different dimensions are never compared. Retrieval is an exact scan per
-- project; add a per-dimension partial HNSW expression index if a project
-- outgrows ~100k chunks.
create table public.chunks (
  id          bigint generated always as identity primary key,
  project_id  uuid not null references public.projects(id) on delete cascade,
  file_id     uuid not null references public.files(id) on delete cascade,
  chunk_index int  not null,
  page_number int,
  content     text not null,
  embedding   vector not null,
  created_at  timestamptz not null default now()
);
create index chunks_project_idx on public.chunks(project_id);
create index chunks_file_idx    on public.chunks(file_id);

create table public.api_keys (
  id           uuid primary key default gen_random_uuid(),
  project_id   uuid not null references public.projects(id) on delete cascade,
  name         text not null default 'default',
  key_prefix   text not null,
  key_hash     text not null unique,
  last_used_at timestamptz,
  created_at   timestamptz not null default now(),
  revoked_at   timestamptz
);
create index api_keys_hash_idx on public.api_keys(key_hash);

create table public.query_logs (
  id          bigint generated always as identity primary key,
  project_id  uuid not null references public.projects(id) on delete cascade,
  api_key_id  uuid references public.api_keys(id) on delete set null,
  question    text not null,
  top_k       int,
  latency_ms  int,
  created_at  timestamptz not null default now()
);
create index query_logs_project_idx on public.query_logs(project_id);
