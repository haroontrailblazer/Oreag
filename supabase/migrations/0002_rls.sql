-- RLS is defense-in-depth: the backend connects with the service role (which
-- bypasses RLS) and enforces ownership in code. These policies protect against
-- direct PostgREST/anon access.

alter table public.projects   enable row level security;
alter table public.files      enable row level security;
alter table public.chunks     enable row level security;
alter table public.api_keys   enable row level security;
alter table public.query_logs enable row level security;

create policy "owner full access" on public.projects
  for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());

create policy "owner full access" on public.files
  for all using (exists (select 1 from public.projects p
                         where p.id = project_id and p.owner_id = auth.uid()));

create policy "owner full access" on public.chunks
  for all using (exists (select 1 from public.projects p
                         where p.id = project_id and p.owner_id = auth.uid()));

create policy "owner full access" on public.api_keys
  for all using (exists (select 1 from public.projects p
                         where p.id = project_id and p.owner_id = auth.uid()));

create policy "owner full access" on public.query_logs
  for all using (exists (select 1 from public.projects p
                         where p.id = project_id and p.owner_id = auth.uid()));

-- Private bucket for uploaded PDFs (paths: {owner_id}/{project_id}/{file_id}.pdf)
insert into storage.buckets (id, name, public)
values ('project-files', 'project-files', false)
on conflict (id) do nothing;
