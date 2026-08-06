-- Long memories were unretrievable. Split them, like files already are.
--
-- THE PROBLEM
--
-- A memory is one row with ONE embedding, whatever its length - services/memory.py
-- embeds body.content whole, and RecursiveCharacterTextSplitter is only ever
-- applied to file markdown. The content cap is 8000 characters, so up to 8000
-- characters of several distinct ideas collapse into a single vector.
--
-- An embedding is a fixed-size summary. Give it one idea and it points at that
-- idea; give it eight and it points at their average, which is close to none of
-- them. Measured on this project: short single-idea memories retrieve at 0.70+,
-- while a 697-character memory STOPPED MATCHING a query aimed squarely at one
-- of its own clauses, and 6-7k-character sections scored 0.61-0.68.
--
-- THE SHAPE, AND WHY IT IS ADDITIVE
--
-- memories keeps its own row, its own content and its own embedding - it stays
-- the unit of record for pinning, tags, source, display and deletion. This
-- table holds the SPLIT PIECES of long ones, each with its own vector, and
-- search takes the best score across both.
--
-- Nothing is created for a memory short enough to be one piece, which is the
-- overwhelming majority: those keep exactly today's single-vector behaviour and
-- pay nothing. Keeping the parent embedding is what makes this additive rather
-- than a migration of existing data - every current memory keeps working
-- untouched, and explore/memory-graph, which read memories.embedding directly,
-- need no changes at all.
--
-- embedding_full mirrors migration 0024 on chunks and memories: a Matryoshka
-- shrink archives the wide original here too, so growing back stays free for
-- memory chunks as well. Without it, a shrink would leave these rows at a width
-- no restore could recover, and pgvector RAISES when comparing mismatched
-- widths - the search would break outright rather than degrade.
--
-- SAFETY: additive. A new empty table plus indexes; no existing row is read or
-- written by this migration. An unapplied 0025 means long memories keep the
-- single diluted vector they have today - the previous behaviour, not a break.

create table if not exists public.memory_chunks (
  id           bigserial primary key,
  memory_id    bigint not null references public.memories(id) on delete cascade,
  -- Denormalised from the parent so search filters by project without joining
  -- memories on the hot path; the cascade above keeps it honest.
  project_id   uuid   not null references public.projects(id) on delete cascade,
  chunk_index  integer not null,
  content      text   not null,
  embedding    vector,
  embedding_full vector,
  created_at   timestamptz not null default now()
);

create index if not exists memory_chunks_project_idx on public.memory_chunks (project_id);
create index if not exists memory_chunks_memory_idx  on public.memory_chunks (memory_id);

-- RLS (defense-in-depth; the backend uses the service role, which bypasses it).
-- Mirrors 0002_rls.sql and 0007_memories.sql exactly.
--
-- Not optional just because this table is "derived": every row holds a VERBATIM
-- COPY of a slice of memories.content. An unprotected memory_chunks would be a
-- readable mirror of the memory text that public.memories is careful to gate -
-- the derived table would silently become the way around the policy on the
-- table it derives from.
--
-- Keyed on the denormalised project_id, so it is the chunks policy verbatim
-- rather than a join through memories - one less hop, and identical to the
-- shape already reviewed on four other tables.
alter table public.memory_chunks enable row level security;
create policy "owner full access" on public.memory_chunks
  for all using (exists (select 1 from public.projects p
                         where p.id = project_id and p.owner_id = auth.uid()));

comment on table public.memory_chunks is
  'Split pieces of a LONG memory, one embedding each. Absent for memories short enough to be a single piece - those are served by memories.embedding alone. Search scores both and keeps the best per memory.';
