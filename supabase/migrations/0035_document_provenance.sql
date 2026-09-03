-- Document provenance: record WHAT was stored, WHO decided, and WHEN.
--
-- 0034 made a files row an EDITION of a document. It answers "which edition is
-- searchable now" and nothing else. An audit of that feature against real
-- corpora found three gaps that no amount of care in the application layer can
-- close, because the facts were never written down:
--
--   1. NO TRANSACTION TIME. files has created_at and indexed_at and no
--      updated_at. A supersession wrote in_force_to - a LEGAL date the user
--      typed - and nothing about when the decision was taken or by whom. So
--      "this edition governed until 22 Jan 2021" was recordable and "on 3 Sep
--      2026 this user recorded that" was not. That is the transaction-time
--      axis of bitemporality, and every question about proving what was in
--      force, approved or published on a date reduces to having it.
--
--   2. NO CONTENT IDENTITY. Nothing hashed document bytes, so "has this
--      changed since we recorded it" and "do I already hold this file" were
--      both unanswerable, and an identical re-upload silently paid to embed
--      the same text twice.
--
--   3. NO INSTRUMENT ROLE. The extractor was told an amendment counts as a
--      match, so an amending Act, an erratum, a translation or a supplementary
--      appendix could all supersede the thing they are about. Measured against
--      105 realistic documents that was the largest single source of wrong and
--      destructive proposals: a Lancet Department of Error retiring the trial
--      it corrects, a French WHO guideline retiring the English text that
--      declares itself authoritative.
--
-- WHY document_events IS A TABLE AND NOT MORE COLUMNS
--
-- A column records the CURRENT state; an audit needs the SEQUENCE. Three
-- columns on files could say "superseded on D by user U" once and would be
-- overwritten by the next decision. The events table keeps every decision, in
-- order, forever - which is also what finally gives a lineage a defined
-- ordering: 0034 derived order from in_force_from, a nullable, user-supplied
-- legal date, so a lineage of undated pre-feature editions had no order at all.
--
-- file_id AND document_id ARE DELIBERATELY NOT FOREIGN KEYS. An audit record
-- must outlive the thing it describes - the most important event about a file
-- is often its deletion, and a FK would either cascade that record away or
-- block the delete. The same reasoning 0034 used for document_id, applied to a
-- stronger requirement.
--
-- APPEND-ONLY IS ENFORCED IN THE DATABASE, not assumed of the application. The
-- trigger below refuses UPDATE. DELETE is deliberately still permitted: a
-- project or account deletion must remain possible, and lawful erasure beats
-- an audit trail that cannot be erased. That is tamper-EVIDENCE against
-- application bugs, not against a database administrator - defending against
-- that needs a hash chain, which is left for later because it would serialise
-- every insert behind a per-project lock.
--
-- SAFETY: additive and nullable throughout. One new table, three new nullable
-- columns, two indexes. Every existing row and every existing query is
-- unaffected, and nothing here is read by retrieval.
--
-- NOTE: deliberately NO percent sign anywhere in this file, comments included -
-- scripts/apply_migration.py hands the whole file to psycopg, which scans it
-- for placeholders.

alter table public.files
  add column if not exists content_sha256   text,
  add column if not exists extracted_title  text,
  add column if not exists instrument_role  text;

-- Which roles may RETIRE another edition. An amending instrument is diff text
-- ("for the words X substitute Y"); a correction is a notice about an article;
-- a translation is the same edition in another language; a supplement is a
-- part. None of them replaces what it refers to, and letting them try was the
-- feature's most destructive failure mode. 'unknown' is permitted to supersede
-- so that a corpus with no role information behaves exactly as it did before.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'files_instrument_role_known'
  ) then
    alter table public.files
      add constraint files_instrument_role_known
      check (
        instrument_role is null
        or instrument_role in (
          'principal', 'consolidated', 'amending',
          'correction', 'translation', 'supplement', 'unknown'
        )
      );
  end if;
end $$;

create table if not exists public.document_events (
  id          bigint generated always as identity primary key,
  project_id  uuid not null references public.projects(id) on delete cascade,
  -- NOT foreign keys, on purpose - see the header. An event about a deleted
  -- file is the event most worth keeping.
  file_id     uuid,
  document_id uuid,
  event       text not null,
  -- auth.users id of whoever caused it, or NULL for work done by a worker
  -- (ingest, requeue) where there is no interactive actor.
  actor_id    uuid,
  occurred_at timestamptz not null default now(),
  -- Free-form context for the event: the filename at the time, the label and
  -- dates written, the predecessor's id, the model that proposed a match.
  detail      jsonb not null default '{}'::jsonb
);

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'document_events_known'
  ) then
    alter table public.document_events
      add constraint document_events_known
      check (
        event in (
          'uploaded', 'indexed', 'ingest_failed',
          'version_proposed', 'parked_for_review',
          'version_confirmed', 'version_rejected',
          'superseded', 'reinstated', 'detached',
          'deleted', 'requeued'
        )
      );
  end if;
end $$;

-- The audit read path: a project's history, newest first.
create index if not exists document_events_project_time_idx
  on public.document_events (project_id, occurred_at desc);
-- One document's history across every edition, including deleted ones.
create index if not exists document_events_document_idx
  on public.document_events (document_id, occurred_at)
  where document_id is not null;
create index if not exists document_events_file_idx
  on public.document_events (file_id)
  where file_id is not null;

-- 0034 added no index for the lineage lookups it introduced. files is capped
-- at 1000 rows per project so the scan was cheap, but the version dialog and
-- the extraction candidate query both filter on exactly this shape.
create index if not exists files_document_idx
  on public.files (project_id, document_id)
  where document_id is not null;

alter table public.document_events enable row level security;

-- SELECT only, and deliberately not the `for all` the sibling tables use: an
-- audit trail that its own subject can rewrite is not an audit trail. The
-- backend connects as the service role and bypasses RLS, so inserts still
-- work; this policy governs direct PostgREST/anon access only.
do $$
begin
  if not exists (
    select 1 from pg_policies
     where schemaname = 'public'
       and tablename = 'document_events'
       and policyname = 'owner reads own events'
  ) then
    create policy "owner reads own events" on public.document_events
      for select using (
        exists (
          select 1 from public.projects p
           where p.id = document_events.project_id
             and p.owner_id = auth.uid()
        )
      );
  end if;
end $$;

-- Append-only, enforced by the database rather than assumed of the callers.
create or replace function public.document_events_no_update()
returns trigger
language plpgsql
as $$
begin
  raise exception 'document_events is append-only';
end;
$$;

do $$
begin
  if not exists (
    select 1 from pg_trigger where tgname = 'document_events_append_only'
  ) then
    create trigger document_events_append_only
      before update on public.document_events
      for each row execute function public.document_events_no_update();
  end if;
end $$;

comment on column public.files.content_sha256 is
  'SHA-256 of the uploaded bytes, taken at upload before anything is derived. '
  'Answers "have I already got this file" and "is the stored object still the '
  'one that was recorded". NULL for rows ingested before 0035.';
comment on column public.files.extracted_title is
  'The document''s first markdown heading, captured at ingest. The version '
  'shortlist scores filename plus this, so a file named scan_0001.pdf whose '
  'identity is in its body can still be recognised as a predecessor.';
comment on column public.files.instrument_role is
  'What KIND of document this is: principal, consolidated, amending, '
  'correction, translation, supplement, unknown. Roles that refer to another '
  'document rather than replacing it are refused as supersessions.';
comment on table public.document_events is
  'Append-only record of every decision taken about a document edition: who, '
  'when, and what. file_id and document_id are not foreign keys because an '
  'event must outlive its subject. UPDATE is blocked by trigger; DELETE stays '
  'possible so that account erasure remains possible.';
