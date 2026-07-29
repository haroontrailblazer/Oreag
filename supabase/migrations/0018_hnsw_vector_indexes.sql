-- Approximate vector search groundwork: per-dimension HNSW indexes on chunks,
-- plus two scoping btrees on the semantic query cache.
--
-- 1. chunks - six PARTIAL HNSW expression indexes, one per embedding dimension.
--
--    `chunks.embedding` is a DIMENSIONLESS `vector` on purpose (each project
--    picks its own embedding model), so one table holds mixed dimensions and a
--    plain HNSW index is impossible. The partial predicate
--    `vector_dims(embedding) = d` makes each index cover exactly one
--    dimension, and Postgres evaluates an index PREDICATE before it computes
--    the indexed EXPRESSION - so a 768-dim row is never handed to
--    `::vector(1536)` and inserting other dimensions cannot error.
--
--    The predicates are mutually exclusive: every row lands in exactly ONE
--    graph, so six indexes cost the same on write as one, and a dimension
--    nobody uses is an empty catalog entry that builds in milliseconds. That
--    is why all six known dimensions are covered rather than just 1536/768 -
--    a project switching to Cohere 1024 or a small MRL size should not
--    silently fall off the fast path until someone ships another migration.
--
--    3072 is deliberately EXCLUDED: pgvector's HNSW limit is 2000 dimensions
--    for `vector`, and the only workaround (`halfvec`) would change the
--    distance arithmetic to half precision and therefore change the
--    `similarity` value that agentic_min_similarity, rag_memory_min_similarity
--    and the UI's match % all depend on. 3072-dimension projects keep the
--    exact scan.
--
--    m = 16 / ef_construction = 64 are pgvector's own defaults, pinned
--    explicitly so a future default change cannot silently move recall.
--
-- 2. semantic_query_cache - btrees only, NO HNSW. Its lookup already filters
--    on seven equality columns plus expires_at, which leaves a handful of
--    candidate rows for the vector ORDER BY, and it is the highest-churn table
--    in the schema (one INSERT per cache miss, a bulk DELETE on every store
--    and on the maintenance sweep). scope_idx makes the existing plan strictly
--    better; expiry_idx turns the TTL sweep into an index scan.
--
-- 3. memories - NO index of any kind is added. max_memories_per_project caps
--    it at 2000 rows per project, so the exact scan is bounded and has perfect
--    recall, while a global HNSW index would have to post-filter by project_id
--    across every tenant at a guaranteed-tiny project share - the exact case
--    where post-filtering collapses. Revisit only if that cap moves by an
--    order of magnitude.
--
-- SAFETY: everything below is additive and idempotent, and NOTHING raises. On
-- an old pgvector, a missing `hnsw` access method, or non-IMMUTABLE
-- preconditions this migration emits NOTICEs and creates no HNSW index. The
-- backend never depends on these indexes for correctness: services/retrieval.py
-- probes for them and only rewrites a query when the matching index is present
-- and valid, so an unapplied (or partially applied) 0018 simply means every
-- vector search keeps using today's exact SQL.

-- ── chunks: per-dimension partial HNSW indexes ──────────────────────────────
--
-- Guarded and size-gated. A plain CREATE INDEX takes a SHARE lock on chunks,
-- which blocks every ingest-queue INSERT for the whole build, and an HNSW
-- build over a large table is minutes to hours. So the indexes are created
-- INLINE only when chunks is genuinely small - small enough that six builds
-- finish inside a SQL-editor statement timeout; on a bigger table (or one
-- whose size cannot be established) this creates nothing and tells the
-- operator to build them with CREATE INDEX CONCURRENTLY instead - see the
-- runbook at the bottom of this file. CONCURRENTLY cannot run here: this
-- script executes inside a transaction block (both the Supabase SQL editor and
-- the repo's migration runner impose one) and CONCURRENTLY is rejected there.
do $$
declare
  -- Deliberately small. At 1536 dimensions 5000 rows is ~30 MB of vectors,
  -- which fits a default maintenance_work_mem and so gets pgvector's fast
  -- in-memory build; six of those finish in seconds. The limit this started
  -- at (50000) was ~300 MB, which forces pgvector's slow two-pass on-disk
  -- build and holds a SHARE lock on chunks for minutes - exactly the blocked
  -- ingestion the deferred branch below exists to avoid.
  inline_row_limit constant bigint := 5000;
  dims             constant int[]  := array[256, 384, 512, 768, 1024, 1536];
  ext_version      text;
  major            int := 0;
  minor            int := 0;
  chunks_oid       oid;
  est_rows         real;
  d                int;
  created          int := 0;
  cancelled        boolean := false;
begin
  select extversion into ext_version
    from pg_extension where extname = 'vector';

  if ext_version is null then
    raise notice '0018: the pgvector extension is not installed; no HNSW index created.';
    return;
  end if;

  if ext_version ~ '^[0-9]+\.[0-9]+' then
    major := split_part(ext_version, '.', 1)::int;
    minor := split_part(ext_version, '.', 2)::int;
  end if;

  -- Informational only. hnsw.iterative_scan (which stops a project_id
  -- post-filter from silently returning too few rows) arrived in pgvector
  -- 0.8.0; below that the backend keeps every query on the exact path, but the
  -- indexes are still worth creating - a later pgvector upgrade turns them on
  -- with no schema change.
  if major = 0 and minor < 8 then
    raise notice
      '0018: pgvector % is older than 0.8.0, so hnsw.iterative_scan is unavailable and the backend will keep using exact vector search. Indexes are still created.',
      ext_version;
  end if;

  if not exists (select 1 from pg_am where amname = 'hnsw') then
    raise notice
      '0018: this pgvector build (%) has no hnsw access method; no HNSW index created.',
      ext_version;
    return;
  end if;

  -- A partial index predicate must be IMMUTABLE, and so must an indexed
  -- expression. Both hold in every shipped pgvector, but verify rather than
  -- assume: a false result here would otherwise surface as a hard failure
  -- pasted into a production SQL editor.
  if not exists (
    select 1 from pg_proc p
     where p.proname = 'vector_dims' and p.provolatile = 'i'
  ) then
    raise notice
      '0018: vector_dims() is not IMMUTABLE on this server, so a partial index predicate is not possible; no HNSW index created.';
    return;
  end if;

  if not exists (
    select 1 from pg_proc p
     where p.proname = 'vector' and p.pronargs = 3 and p.provolatile = 'i'
  ) then
    raise notice
      '0018: the vector(vector, integer, boolean) typmod cast is not IMMUTABLE on this server, so an expression index is not possible; no HNSW index created.';
    return;
  end if;

  chunks_oid := to_regclass('public.chunks');
  if chunks_oid is null then
    raise notice '0018: public.chunks does not exist; no HNSW index created.';
    return;
  end if;

  -- The size gate is only as good as the estimate it reads, and
  -- pg_class.reltuples is -1 ("never analyzed") on any table Postgres has not
  -- sampled yet - which is EXACTLY the state of a table created minutes ago by
  -- 0001, i.e. the case the inline branch exists for. Reading reltuples first
  -- would therefore defer on every fresh database and create nothing at all.
  -- ANALYZE fixes that: it is sampled (default 30000 rows), bounded and cheap
  -- even on a huge table, it writes reltuples in place so the SELECT below
  -- sees the new value, and - unlike VACUUM - it is allowed inside a
  -- transaction block and inside a DO block. Guarded (query_canceled by name,
  -- since OTHERS does not cover it) because ANALYZE needs table ownership: on
  -- a restricted role this must degrade to the deferred branch, never abort
  -- the migration.
  begin
    execute 'analyze public.chunks';
  exception
    when query_canceled then
      raise notice
        '0018: the ANALYZE of public.chunks was cancelled; falling back to the stored estimate.';
    when others then
      raise notice
        '0018: could not analyze public.chunks (%); falling back to the stored estimate.',
        sqlerrm;
  end;

  select c.reltuples into est_rows from pg_class c where c.oid = chunks_oid;
  -- After that ANALYZE, -1 can only mean the analyze itself did not run, so the
  -- size is genuinely unknown: take the safe (deferred) branch. -1 must never
  -- be read as "small" - a freshly restored multi-million-row table reads -1
  -- too, and inlining there is the lock disaster this gate exists to prevent.
  if est_rows is null or est_rows < 0 or est_rows >= inline_row_limit then
    raise notice
      '0018: public.chunks holds ~% rows (-1 = size unknown, the ANALYZE above could not run), which is more than this migration indexes inline without blocking ingestion. No HNSW index created - build them with CREATE INDEX CONCURRENTLY over a DIRECT session-mode (port 5432) connection, one statement per execute. See the runbook at the end of supabase/migrations/0018_hnsw_vector_indexes.sql.',
      coalesce(est_rows, -1);
    return;
  end if;

  foreach d in array dims loop
    -- One guarded block per dimension: a single bad dimension must not abort
    -- the whole migration. `when others` alone does NOT achieve that: PL/pgSQL
    -- excludes QUERY_CANCELED from OTHERS, so a statement_timeout or an
    -- operator cancel mid-build - the single most likely failure here - would
    -- propagate straight out of this DO block and roll the whole migration
    -- back. It gets its own handler, and stops the loop rather than driving
    -- the five remaining builds into the same timeout.
    begin
      execute format(
        'create index if not exists chunks_embedding_hnsw_%s_idx '
        'on public.chunks using hnsw ((embedding::vector(%s)) vector_cosine_ops) '
        'with (m = 16, ef_construction = 64) '
        'where vector_dims(embedding) = %s',
        d, d, d
      );
      created := created + 1;
    exception
      when query_canceled then
        raise notice
          '0018: the build of chunks_embedding_hnsw_%_idx was cancelled (statement timeout, or an operator cancel), so no further dimension is attempted. Build the remaining indexes with CREATE INDEX CONCURRENTLY - see the runbook at the end of supabase/migrations/0018_hnsw_vector_indexes.sql.',
          d;
        cancelled := true;
      when others then
        raise notice '0018: could not create chunks_embedding_hnsw_%_idx: %', d, sqlerrm;
    end;
    -- EXIT sits in the loop body, not in the handler above: one less thing
    -- that has to be right in a script that cannot be test-run.
    exit when cancelled;
  end loop;

  -- No ANALYZE here: the one above already refreshed the statistics that
  -- retrieval.py's probe reads, and creating an index changes no rows.
  raise notice '0018: created or confirmed % of % HNSW indexes on public.chunks (~% rows).',
    created, array_length(dims, 1), est_rows;
end
$$;

-- ── semantic query cache: scope + expiry btrees ─────────────────────────────
--
-- LAST, deliberately: these are independent of the HNSW work, and a client
-- that autocommits statement by statement (psql -f without --single-transaction)
-- keeps them even if an index build above is cancelled. In a client that wraps
-- the whole script in one transaction the ordering is moot - which is why the
-- DO block above also refuses to raise.
create index if not exists semantic_query_cache_scope_idx
  on public.semantic_query_cache (project_id, content_signature, top_k, expires_at desc);

create index if not exists semantic_query_cache_expiry_idx
  on public.semantic_query_cache (expires_at);

-- ── runbook: building the same indexes CONCURRENTLY on a large table ────────
--
-- Run these in psql (or any client that does NOT wrap the script in a
-- transaction) over the DIRECT session-mode connection on port 5432 - NOT the
-- transaction pooler and NOT the Supabase SQL editor, both of which put the
-- script in a transaction block and will reject CONCURRENTLY. Issue ONE
-- statement per round trip.
--
--   -- 1. maintenance_work_mem is the single biggest build-time lever: if the
--   --    graph does not fit, pgvector falls back to a much slower two-pass
--   --    on-disk build.
--   set maintenance_work_mem = '2GB';
--   set max_parallel_maintenance_workers = 4;
--
--   -- 2. A failed CREATE INDEX CONCURRENTLY leaves an indisvalid = false
--   --    index that is NEVER used for reads but IS maintained on every write,
--   --    and `if not exists` skips it forever. Drop those first. The backend
--   --    already filters on indisvalid, so it treats them as absent.
--   select c.relname
--     from pg_class c
--     join pg_namespace n on n.oid = c.relnamespace
--     join pg_index i on i.indexrelid = c.oid
--    where n.nspname = 'public'
--      and strpos(c.relname, 'chunks_embedding_hnsw_') = 1
--      and not i.indisvalid;
--   -- for each name returned:
--   drop index concurrently if exists public.<name>;
--
--   -- 3. Build, one statement at a time (repeat for 256, 384, 512, 768, 1024).
--   create index concurrently if not exists chunks_embedding_hnsw_1536_idx
--     on public.chunks using hnsw ((embedding::vector(1536)) vector_cosine_ops)
--     with (m = 16, ef_construction = 64)
--     where vector_dims(embedding) = 1536;
--
--   -- 4. Watch progress from another session:
--   select phase, blocks_done, blocks_total, tuples_done, tuples_total
--     from pg_stat_progress_create_index;
--
--   -- 5. Finally:
--   analyze public.chunks;
--
-- Rollback is symmetric and needs no schema revert: DROP INDEX CONCURRENTLY
-- the offending chunks_embedding_hnsw_<d>_idx (also one statement per round
-- trip, also not in a transaction block). Within
-- vector_ann_capability_ttl_seconds the backend's probe notices and closes the
-- ANN gate for that dimension only. The two semantic_query_cache btrees are
-- independent of this feature and should be kept.
