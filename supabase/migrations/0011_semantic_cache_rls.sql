-- RLS for semantic_query_cache (missed in 0010; flagged by the Supabase
-- advisor). Without it, the public PostgREST surface + the anon key would let
-- anyone read every cached question/answer across ALL accounts - or insert
-- forged rows that get served as answers (cache poisoning).
--
-- Same defense-in-depth pattern as 0002: the backend's direct Postgres
-- connection owns the table and is unaffected; this guards direct
-- PostgREST/anon access, scoping rows to the owning account.

alter table public.semantic_query_cache enable row level security;

create policy "owner full access" on public.semantic_query_cache
  for all using (exists (select 1 from public.projects p
                         where p.id = project_id and p.owner_id = auth.uid()));
