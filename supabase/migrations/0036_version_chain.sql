-- The version chain: make "what did this replace" a fact, not an inference.
--
-- 0034 grouped editions with a flat key, `coalesce(document_id, id)`, and gave
-- a lineage NO ORDER. Order was derived from in_force_from - a nullable,
-- user-supplied LEGAL date - so a lineage of editions uploaded before the
-- feature existed, or of editions whose effective date the extractor could not
-- read, had no defined order at all. "Which edition replaced which" was
-- recoverable only by reading the event payloads 0035 added, and not at all
-- for anything predating them.
--
-- supersedes_file_id is the missing edge. With it a lineage is a chain that
-- can be walked from the current edition backwards, independently of any date
-- anyone typed. It is written by the one endpoint that performs a supersession
-- and by nothing else.
--
-- NOT A FOREIGN KEY, for the third time in this schema and the same reason as
-- files.document_id (0034) and document_events.file_id (0035): a chain must
-- survive the deletion of a link. ON DELETE SET NULL would silently sever the
-- history at whichever edition someone removed; CASCADE would delete the rest
-- of the chain along with it. A dangling uuid that still records "this edition
-- replaced THAT one, which no longer exists" is strictly more truthful than
-- either.
--
-- markdown_sha256 records the DERIVED artefact, where content_sha256 (0035)
-- records the upload. They answer different questions and both are needed: a
-- conversion-pipeline change re-derives the searchable text of an edition
-- IN PLACE - the markdown blob is written with upsert=true - so an edition can
-- answer differently tomorrow with no change to its bytes, its row, or its
-- version metadata. Without this column that rewrite leaves no trace at all.
--
-- SAFETY: additive and nullable. Two columns, one partial index. Nothing is
-- backfilled: an existing lineage keeps deriving its order from dates, and
-- gains a real chain from its next supersession onward. Nothing here is read
-- by retrieval.
--
-- NOTE: deliberately NO percent sign anywhere in this file, comments included.

alter table public.files
  add column if not exists supersedes_file_id uuid,
  add column if not exists markdown_sha256    text;

-- Walk a chain backwards from the current edition. Partial because only
-- superseding editions carry the pointer, which in a mixed corpus is a small
-- minority of rows.
create index if not exists files_supersedes_idx
  on public.files (supersedes_file_id)
  where supersedes_file_id is not null;

-- An edition cannot replace itself. Cheap, and it catches the shape of bug
-- that would make a chain walk loop forever.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'files_supersedes_not_self'
  ) then
    alter table public.files
      add constraint files_supersedes_not_self
      check (supersedes_file_id is null or supersedes_file_id <> id);
  end if;
end $$;

comment on column public.files.supersedes_file_id is
  'The edition this one replaced, written at the moment of supersession. Gives '
  'a lineage a real order independent of the nullable, user-supplied '
  'in_force_from. Deliberately not a foreign key: a chain must survive the '
  'deletion of a link, and a dangling id that records what was replaced is '
  'more truthful than SET NULL severing the history.';
comment on column public.files.markdown_sha256 is
  'SHA-256 of the converted markdown, stamped beside conversion_version. '
  'content_sha256 identifies the UPLOAD; this identifies the text actually '
  'chunked and embedded. A conversion-pipeline change rewrites that text in '
  'place, so without this an edition can answer differently with no change to '
  'its bytes or its row.';
