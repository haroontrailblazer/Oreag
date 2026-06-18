-- Agent memory entries. Coding agents (via the MCP server) save and recall
-- per-project context across sessions. Independent of uploaded documents.
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

-- RLS (defense-in-depth; backend uses the service role). Mirrors 0002_rls.sql.
alter table public.memories enable row level security;
create policy "owner full access" on public.memories
  for all using (exists (select 1 from public.projects p
                         where p.id = project_id and p.owner_id = auth.uid()));
