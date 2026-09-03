-- Document relations: one edge type was never enough.
--
-- 0034-0036 gave a document exactly ONE relation to another - "supersedes" -
-- and it always did the same two things: retire the predecessor, index the
-- newcomer. Measured against 105 real documents, that single edge was right
-- for four classes and wrong for nine.
--
--   a bare amending Act ("for the words X substitute Y") replaced the statute
--   it amends, so answers quoted diff fragments that read like law;
--   an erratum retired the article it corrects;
--   a retraction notice left the retracted paper answering, unmarked;
--   a translation retired the authoritative language edition;
--   an API v2 reference retired a v1 that is still supported;
--   an FY23 filing retired FY22, which is a SERIES, not a revision;
--   an Amendment No. 1 retired the MSA whose operative terms it depends on.
--
-- 0035's instrument_role says what a document IS. relation_kind says what it
-- DOES to the document it points at. They are different axes and both are
-- needed: an annual report and a consolidated reprint are both `principal`
-- documents, and one succeeds its predecessor while the other replaces it.
--
-- WHY THIS NEEDS NO RETRIEVAL CHANGE
--
-- "Should this document answer questions?" is already expressed in exactly one
-- way: whether it has rows in `chunks`. Superseded editions hold none, which is
-- why retrieval.py has never needed a predicate. A relation kind therefore
-- reduces to two booleans the confirm transaction already knows how to apply -
-- does the predecessor keep its chunks, and does this document get any - and
-- the byte-pinned search SQL stays untouched for the fourth migration running.
--
--   supersedes   predecessor retires        this answers
--   restates     predecessor retires        this answers   (recorded distinctly:
--                                                           a restatement carries
--                                                           obligations a revision
--                                                           does not)
--   amends       predecessor STAYS          this does NOT  (diff text)
--   corrects     predecessor STAYS          this does NOT  (a notice about)
--   retracts     predecessor STOPS + marked this does NOT  (withdrawn work must
--                                                           not answer, and must
--                                                           not vanish silently)
--   translates   predecessor STAYS          this answers
--   supplements  predecessor STAYS          this answers
--   succeeds     predecessor STAYS          this answers   (next in a series, or
--                                                           a newer version whose
--                                                           predecessor is still
--                                                           supported)
--
-- `retracted` joins legal_status for the mark itself. A retracted paper that
-- simply disappeared would be the worst outcome of all - the corpus would look
-- as though it had never held it.
--
-- SAFETY: additive and nullable. One column, one widened CHECK, one index.
-- NULL relation_kind on an existing row means `supersedes`, which is what every
-- relation recorded before this migration was, so nothing is backfilled and no
-- existing behaviour changes.
--
-- NOTE: deliberately NO percent sign anywhere in this file.

alter table public.files
  add column if not exists relation_kind text;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'files_relation_kind_known'
  ) then
    alter table public.files
      add constraint files_relation_kind_known
      check (
        relation_kind is null
        or relation_kind in (
          'supersedes', 'restates', 'amends', 'corrects',
          'retracts', 'translates', 'supplements', 'succeeds'
        )
      );
  end if;
end $$;

-- A relation_kind without a target is meaningless, and a target whose kind is
-- unknown falls back to `supersedes` - the pre-0037 behaviour. Both are legal;
-- this only forbids the shape that says nothing at all.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'files_relation_needs_target'
  ) then
    alter table public.files
      add constraint files_relation_needs_target
      check (relation_kind is null or supersedes_file_id is not null);
  end if;
end $$;

-- legal_status gains 'retracted'. Dropping and re-adding rather than widening
-- in place because a CHECK cannot be altered: guarded so a re-run is a no-op,
-- and every existing value is still admitted, so the validating scan cannot
-- fail on live data.
do $$
begin
  if exists (
    select 1 from pg_constraint where conname = 'files_legal_status_known'
  ) then
    alter table public.files drop constraint files_legal_status_known;
  end if;
  alter table public.files
    add constraint files_legal_status_known
    check (
      legal_status is null
      or legal_status in (
        'in_force', 'amended', 'repealed', 'draft', 'unknown', 'retracted'
      )
    );
end $$;

-- "What relates to this document, and how" - the read behind a document's
-- relations panel, and the only query that walks the edge in reverse.
create index if not exists files_relation_idx
  on public.files (supersedes_file_id, relation_kind)
  where supersedes_file_id is not null;

comment on column public.files.relation_kind is
  'What this document does to the one supersedes_file_id points at: '
  'supersedes, restates, amends, corrects, retracts, translates, supplements, '
  'succeeds. Decides two things and nothing else - whether the predecessor '
  'keeps its chunks, and whether this document gets any - so retrieval needs '
  'no predicate. NULL means supersedes, the only relation that existed before '
  'this migration.';
