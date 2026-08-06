-- HNSW indexes for memory_chunks, so long-memory search scales like document
-- search already does.
--
-- WHY THIS EXISTS NOW
--
-- Migration 0025 split long memories into pieces with their own vectors, and
-- services/memory.py scores parents and pieces in one UNION. That query was
-- justified as "exact is fine, max_memories_per_project caps it at 2000 rows" -
-- a bound that died the moment the pieces were added. A memory can be 8000
-- characters, which splits into 20 pieces, so the real ceiling is
-- 2000 * 20 = 40,000 rows per project: twenty times the old cap, and DOUBLE the
-- 20,000 (vector_ann_min_chunks) at which document chunks were judged to need
-- an index.
--
-- SHAPE - identical to 0018, deliberately
--
-- memory_chunks.embedding is a DIMENSIONLESS `vector`, one table across every
-- project's dimension, so a plain HNSW index is impossible. One PARTIAL index
-- per dimension instead, keyed on the same expression the query orders by.
-- 3072 is absent for the same reason as 0018: pgvector's HNSW limit is 2000
-- dimensions, and the halfvec workaround would change the distance arithmetic
-- and therefore the similarity value callers depend on.
--
-- Only the PIECES get an index. The parent `memories` table is capped at 2000
-- rows per project and stays an exact scan - it is genuinely small, and the
-- unlimited parent branch is also what makes the piece branch's LIMIT safe:
-- every memory is already a candidate through its parent, so a piece outside
-- the limit costs that memory its piece-level BOOST, never its findability.
--
-- SAFETY: creates nothing but indexes, reads and writes no rows. Size-gated
-- exactly like 0018 - a plain CREATE INDEX takes a SHARE lock for the whole
-- build, so this runs inline only while the table is small enough for that to
-- be instant, and otherwise prints the CONCURRENTLY runbook at the foot of this
-- file. Unapplied, memory search simply keeps using today's exact SQL:
-- retrieval.memory_ann_dimension() finds no index and closes the gate.

do $$
declare
  -- Same reasoning as 0018: at 1536 dimensions 5000 rows is ~30 MB of vectors,
  -- which fits maintenance_work_mem and gets pgvector's fast in-memory build.
  -- memory_chunks is far smaller than chunks in every project seen so far, so
  -- this is expected to take the inline branch on a real database.
  inline_row_limit constant bigint := 5000;
  dims             constant int[]  := array[256, 384, 512, 768, 1024, 1536];
  ext_version      text;
  major            int := 0;
  minor            int := 0;
  target_oid       oid;
  est_rows         real;
  d                int;
  created          int := 0;
  cancelled        boolean := false;
begin
  select extversion into ext_version
    from pg_extension where extname = 'vector';

  if ext_version is null then
    raise notice '0026: the pgvector extension is not installed; no HNSW index created.';
    return;
  end if;

  -- A capture group can only return digits, so a build tagged `0.8rc1` cannot
  -- blow up the ::int cast and abort the migration.
  if ext_version ~ '^[0-9]+\.[0-9]+' then
    major := substring(ext_version, '^([0-9]+)')::int;
    minor := substring(ext_version, '^[0-9]+\.([0-9]+)')::int;
  end if;

  -- Informational. hnsw.iterative_scan arrived in 0.8.0; below that the backend
  -- keeps memory search on the exact path, but the indexes are still worth
  -- creating - a later pgvector upgrade turns them on with no schema change.
  if major = 0 and minor < 8 then
    raise notice
      '0026: pgvector % is older than 0.8.0, so hnsw.iterative_scan is unavailable and the backend will keep using exact memory search. Indexes are still created.',
      ext_version;
  end if;

  if not exists (select 1 from pg_am where amname = 'hnsw') then
    raise notice
      '0026: this pgvector build (%) has no hnsw access method; no HNSW index created.',
      ext_version;
    return;
  end if;

  -- A partial index predicate and an indexed expression must both be
  -- IMMUTABLE. True on every shipped pgvector, but verified rather than
  -- assumed - a false result would otherwise surface as a hard failure pasted
  -- into a production SQL editor.
  if not exists (
    select 1 from pg_proc p
     where p.proname = 'vector_dims' and p.provolatile = 'i'
  ) then
    raise notice
      '0026: vector_dims() is not IMMUTABLE on this server, so a partial index predicate is not possible; no HNSW index created.';
    return;
  end if;

  if not exists (
    select 1 from pg_proc p
     where p.proname = 'vector' and p.pronargs = 3 and p.provolatile = 'i'
  ) then
    raise notice
      '0026: the vector(vector, integer, boolean) typmod cast is not IMMUTABLE on this server, so an expression index is not possible; no HNSW index created.';
    return;
  end if;

  target_oid := to_regclass('public.memory_chunks');
  if target_oid is null then
    raise notice
      '0026: public.memory_chunks does not exist (migration 0025 not applied); no HNSW index created.';
    return;
  end if;

  -- reltuples is -1 on a table Postgres has never sampled, which is exactly the
  -- state of one created by 0025 minutes ago - i.e. the case the inline branch
  -- exists for. Reading it first would defer on every fresh database and create
  -- nothing. ANALYZE is sampled, bounded, cheap, writes reltuples in place, and
  -- is allowed inside a transaction and a DO block. Guarded because it needs
  -- table ownership: on a restricted role this must degrade to the deferred
  -- branch, never abort the migration. query_canceled is named explicitly -
  -- PL/pgSQL's OTHERS does not cover it.
  begin
    execute 'analyze public.memory_chunks';
  exception
    when query_canceled then
      raise notice
        '0026: the ANALYZE of public.memory_chunks was cancelled; falling back to the stored estimate.';
    when others then
      raise notice
        '0026: could not analyze public.memory_chunks (%); falling back to the stored estimate.',
        sqlerrm;
  end;

  select c.reltuples into est_rows from pg_class c where c.oid = target_oid;
  -- After that ANALYZE, -1 can only mean the analyze did not run, so the size is
  -- genuinely unknown: take the deferred branch. -1 must never be read as
  -- "small" - a freshly restored large table reads -1 too, and inlining there is
  -- the lock disaster this gate exists to prevent.
  if est_rows is null or est_rows < 0 or est_rows >= inline_row_limit then
    raise notice
      '0026: public.memory_chunks holds ~% rows (-1 = size unknown, the ANALYZE above could not run), which is more than this migration indexes inline without blocking memory writes. No HNSW index created - build them with CREATE INDEX CONCURRENTLY over a DIRECT session-mode (port 5432) connection, one statement per execute. See the runbook at the end of this file.',
      coalesce(est_rows, -1);
    return;
  end if;

  foreach d in array dims loop
    -- One guarded block per dimension so a single bad dimension cannot abort
    -- the migration. query_canceled needs its own handler (OTHERS excludes it),
    -- and it stops the loop rather than driving the remaining builds into the
    -- same timeout.
    begin
      execute format(
        'create index if not exists memory_chunks_embedding_hnsw_%s_idx '
        'on public.memory_chunks using hnsw ((embedding::vector(%s)) vector_cosine_ops) '
        'with (m = 16, ef_construction = 64) '
        'where vector_dims(embedding) = %s',
        d, d, d
      );
      created := created + 1;
    exception
      when query_canceled then
        raise notice
          '0026: the build of memory_chunks_embedding_hnsw_%_idx was cancelled (statement timeout, or an operator cancel), so no further dimension is attempted. Build the remaining indexes with CREATE INDEX CONCURRENTLY - see the runbook at the end of this file.',
          d;
        cancelled := true;
      when others then
        raise notice
          '0026: could not create memory_chunks_embedding_hnsw_%_idx: %', d, sqlerrm;
    end;
    -- EXIT in the loop body, not in the handler: one less thing that has to be
    -- right in a script that cannot be test-run.
    exit when cancelled;
  end loop;

  raise notice '0026: created % of % memory_chunks HNSW indexes.', created, array_length(dims, 1);
end $$;

comment on table public.memory_chunks is
  'Split pieces of a LONG memory, one embedding each. Absent for memories short enough to be a single piece - those are served by memories.embedding alone. Search scores both and keeps the best per memory. Per-dimension partial HNSW indexes (0026) are used once a project clears vector_ann_min_chunks pieces.';

-- ── RUNBOOK: building these on a large memory_chunks ─────────────────────────
--
-- If the block above printed the "holds ~N rows" notice, build the indexes
-- yourself. CONCURRENTLY cannot run inside a transaction block, so it cannot
-- live in this file - and the Supabase SQL editor and the repo's migration
-- runner both impose one.
--
--   1. Connect over a DIRECT session-mode connection (port 5432, NOT the 6543
--      transaction pooler - CONCURRENTLY needs a session that outlives a
--      transaction).
--   2. Run ONE statement per execute, and only for the dimensions actually in
--      use:  select distinct vector_dims(embedding) from public.memory_chunks;
--
--   create index concurrently if not exists memory_chunks_embedding_hnsw_1536_idx
--     on public.memory_chunks using hnsw ((embedding::vector(1536)) vector_cosine_ops)
--     with (m = 16, ef_construction = 64)
--     where vector_dims(embedding) = 1536;
--
--   3. Verify every index came out VALID. A CONCURRENTLY build that fails
--      leaves an INVALID index that is never used for reads but IS maintained
--      on writes - all of the cost, none of the benefit. The backend's probe
--      already ignores those (indisvalid), so a failed build silently costs
--      write throughput and delivers nothing:
--
--      select c.relname, i.indisvalid
--        from pg_class c join pg_index i on i.indexrelid = c.oid
--       where i.indrelid = to_regclass('public.memory_chunks')
--         and strpos(c.relname, 'memory_chunks_embedding_hnsw_') = 1;
--
--      Drop and rebuild any row with indisvalid = false.
