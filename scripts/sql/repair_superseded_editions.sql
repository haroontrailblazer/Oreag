-- Repair: superseded editions that are back in the index.
--
-- WHEN TO RUN THIS
--
-- Migration 0034 made `files.in_force_to IS NOT NULL` mean "superseded: keeps
-- its blobs, holds ZERO chunks, never queued". That invariant is enforced by
-- the BACKEND - three requeue guards and two ingest guards - not by the
-- database. So it holds only while version-aware code is deployed.
--
-- Roll the backend back to a pre-0034 build while superseded editions exist
-- and the old requeue paths no longer know about them. The next model switch,
-- re-index or retry then re-embeds retired law straight back into the live
-- index, silently, and answers start quoting text the corpus had retired.
--
-- 0034's header described this remedy in a comment. A comment is not runnable
-- at 3am, so it lives here instead - and unlike that sketch, this file gets
-- the ORDER right: the chunks must go BEFORE chunk_count is zeroed, or the
-- second statement makes the first unable to find what it was meant to delete
-- by any count-based check, and reports success over a corpus that still has
-- retired content in it.
--
-- SAFE TO RUN AT ANY TIME. On a healthy database every statement matches zero
-- rows. It is idempotent, it touches no storage object, and it removes only
-- derived data: a superseded edition's chunks are rebuildable from the
-- markdown blob that 0034 deliberately keeps, so nothing here is unrecoverable.
--
--     python scripts/apply_migration.py --file scripts/sql/repair_superseded_editions.sql
--   or paste into the SQL editor.
--
-- NOTE: no percent sign anywhere, so the repo's own tooling can run it.

begin;

-- 1. What is wrong, before changing anything. Keep this output.
select
  f.id,
  f.filename,
  f.in_force_to,
  f.status,
  f.chunk_count as recorded_chunk_count,
  count(c.id)   as actual_chunks
from public.files f
left join public.chunks c on c.file_id = f.id
where f.in_force_to is not null
group by f.id, f.filename, f.in_force_to, f.status, f.chunk_count
having count(c.id) > 0 or f.chunk_count <> 0 or f.status in ('pending', 'processing');

-- 2. Remove the chunks a retired edition must not have. FIRST, so that the
--    count in step 3 is corrected only for rows whose content is actually gone.
delete from public.chunks c
 using public.files f
 where c.file_id = f.id
   and f.in_force_to is not null;

-- 3. Correct the count retrieval sums to size the ANN gate. A superseded row
--    still claiming its old count inflates both the absolute threshold and the
--    project-share threshold, routing a small project onto HNSW on phantom rows.
update public.files
   set chunk_count = 0
 where in_force_to is not null
   and chunk_count <> 0;

-- 4. Take retired editions out of the queue. claim_next matches status
--    'pending' unconditionally, so one left queued is re-claimed on every lease
--    lapse, burns its retry budget, and finally fails - dragging the whole
--    project to status 'error' for a file nobody can retry by design.
update public.files
   set status = 'indexed',
       lease_expires_at = null
 where in_force_to is not null
   and status in ('pending', 'processing');

-- 5. Roll the cache signature for every project this touched, or both answer
--    layers keep serving answers built on the content just removed - L1 for an
--    hour, L2 for a day.
update public.projects p
   set content_version = p.content_version + 1
 where exists (
   select 1 from public.files f
    where f.project_id = p.id
      and f.in_force_to is not null
 );

-- 6. Prove it. Expect zero rows.
select f.id, f.filename, f.status, f.chunk_count, count(c.id) as actual_chunks
from public.files f
left join public.chunks c on c.file_id = f.id
where f.in_force_to is not null
group by f.id, f.filename, f.status, f.chunk_count
having count(c.id) > 0 or f.chunk_count <> 0 or f.status in ('pending', 'processing');

commit;
