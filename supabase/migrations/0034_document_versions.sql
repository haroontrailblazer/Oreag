-- Document versions: keep the history, index only what is in force.
--
-- Replacing a document today means deleting it and uploading the successor.
-- That delete cascades the chunks away AND removes both storage objects, so
-- the previous text is unrecoverable - the corpus can answer "what does the
-- rule say" and can never show what it used to say. These five columns make a
-- files row an EDITION of a document, so a superseded version keeps its row,
-- its source blob, its converted markdown and all of its metadata while
-- holding zero chunks.
--
-- WHY FIVE COLUMNS ON files AND NOT A documents TABLE
--
-- A "document" owns no data of its own. Its display name is the filename of
-- its current version; its label and dates live on the versions; every
-- consumer already keys on files.id - the ingest queue, the chunk cascade, the
-- Files tab, the storage paths. A table would add an empty row, an RLS policy,
-- a foreign key and a join to every file query in exchange for a name we
-- already have. files inherits its RLS from 0002.
--
-- document_id is a plain GROUPING KEY, not a reference, and has no foreign key
-- on purpose: a lineage must outlive the deletion of any member including the
-- first, and either ON DELETE rule is wrong - SET NULL shatters the group into
-- singletons, CASCADE destroys the history this feature exists to keep.
-- Members whose original row was deleted still share the same (now dangling)
-- uuid, which is exactly the behaviour wanted. NULL document_id means "this
-- file is its own document", so nothing is backfilled and no existing row is
-- touched. The lineage key is coalesce(document_id, id), in SQL and in Python.
--
-- in_force_to IS THE INDEXABILITY SWITCH
--
-- A version with in_force_to set is superseded: it keeps its files row, its
-- source blob, its converted markdown blob, its conversion_version and all its
-- legal metadata, and it holds ZERO chunks. Nothing else decides this - in
-- particular legal_status does NOT, so there is exactly one authority and a
-- descriptive status edit can never silently drop a document out of the index.
--
-- THE INTERVAL IS HALF-OPEN: a version governs [in_force_from, in_force_to).
-- in_force_to is set only when a successor exists, and always to that
-- successor's in_force_from, so the two rows cannot disagree and chaining
-- needs no date arithmetic - which matters, because this backend has no date
-- library at all. The API never accepts in_force_to as an input.
--
-- WHY version_tracking IS PER PROJECT
--
-- The extractor asks "is this a new edition of something already here?", and
-- that question is just as true of report_v2.pdf as of an amending Act. A
-- fleet-wide switch would park uploads in projects that have nothing to do
-- with versioned documents. Default false: every existing project keeps
-- today's behaviour exactly, and no upload anywhere changes until an owner
-- asks for it. The global settings.version_extraction_enabled stays as a
-- fleet-wide kill switch - the two are not redundant.
--
-- ROLLBACK REMEDY. This migration is never rolled back. If the BACKEND is
-- rolled back while superseded versions exist, the old requeue paths do not
-- know about them and the next model switch re-indexes retired law. The repair
-- is a runnable script, not a sketch in this comment:
--   scripts/sql/repair_superseded_editions.sql
-- It also handles two things the sketch here did not: retired editions left
-- sitting in the queue, and the cache signature, which must roll or both
-- answer layers keep serving what was just removed.
--
-- SAFETY: additive and nullable. Every existing row reads NULL on all five,
-- which is precisely today's behaviour - one file, its own document, in force.
-- No index: files is capped at 1000 rows per project and every version query
-- is project-scoped, already covered by files_project_idx.
--
-- NOTE: deliberately NO percent sign anywhere in this file, comments included.
-- scripts/apply_migration.py hands the whole file to psycopg, which scans it
-- for placeholders; one stray percent makes the migration unrunnable by the
-- repo's own tooling.

alter table public.files
  add column if not exists document_id   uuid,
  add column if not exists version_label text,
  add column if not exists in_force_from date,
  add column if not exists in_force_to   date,
  add column if not exists legal_status  text;

alter table public.projects
  add column if not exists version_tracking boolean not null default false;

-- Guarded CHECKs, copying 0032_answer_policy.sql. Both are trivially satisfied
-- today: every existing row is NULL on every new column, so neither can fail
-- the validating scan. Enforced in the database and not only in FastAPI for
-- the reason 0032 gives - a bad write from psql is still a bad write.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'files_legal_status_known'
  ) then
    alter table public.files
      add constraint files_legal_status_known
      check (
        legal_status is null
        or legal_status in ('in_force', 'amended', 'repealed', 'draft', 'unknown')
      );
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'files_in_force_range'
  ) then
    alter table public.files
      add constraint files_in_force_range
      check (
        in_force_to is null
        or in_force_from is null
        or in_force_to >= in_force_from
      );
  end if;
end $$;

-- The invariant, written down and self-healing on every deploy. Matches zero
-- rows on first apply. It exists for the rollback window above: retrieval sums
-- files.chunk_count to size the ANN gate, and a superseded row still claiming
-- its old count inflates the project's apparent size on both gates.
update public.files set chunk_count = 0
 where in_force_to is not null and chunk_count <> 0;

comment on column public.files.document_id is
  'Grouping key for the editions of one document. NULL means this file is its '
  'own document; the lineage key is coalesce(document_id, id). Deliberately '
  'not a foreign key - a lineage must outlive the deletion of any member.';
comment on column public.files.version_label is
  'How this edition names itself, e.g. "Act 18 of 2013" or "Second Amendment '
  '2019". Display only; it never reaches retrieval or the answer prompt.';
comment on column public.files.in_force_from is
  'Start of the half-open interval this edition governs. Required when '
  'superseding a predecessor, because the same value is written to that '
  'predecessor as its in_force_to.';
comment on column public.files.in_force_to is
  'End of the half-open interval, EXCLUSIVE. NOT NULL means superseded: the '
  'row keeps every blob and all metadata, holds zero chunks, and is never '
  'queued for indexing. The only authority on indexability.';
comment on column public.files.legal_status is
  'Descriptive only: in_force, amended, repealed, draft, unknown. Does NOT '
  'gate indexing - see in_force_to.';
comment on column public.projects.version_tracking is
  'When true, an upload that looks like a new edition of a document already in '
  'this project is held in files.status = review until a person confirms what '
  'it replaces. False leaves ingestion byte-identical to its pre-0034 '
  'behaviour, including making no extraction LLM call.';
