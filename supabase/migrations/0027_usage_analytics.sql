-- Columns the account Usage page needs, none of which exist today.
--
-- WHAT WAS MISSING AND WHY IT MATTERS
--
-- `usage_events` records WHICH endpoint was called and how long it took, but
-- not WHICH MODEL answered - so "tokens by model" was unanswerable even once
-- the token columns started being filled. Same for cost: without storing it at
-- write time, a later price change silently rewrites history.
--
-- `query_logs` records `cache_layer` ('l1' | 'l2' | NULL) but throws away both
-- the SIMILARITY that decided an L2 hit and the retrieval similarity that
-- drives answer quality. Both are computed, returned to the caller, and then
-- dropped.
--
-- TOKENS SAVED BY THE CACHE - the honest definition
--
-- A cache hit skips the model, so there is no usage to record. The tempting
-- shortcut is to multiply hits by an average, which produces a number nobody
-- can defend. Instead, the tokens a cached answer ORIGINALLY cost are stored
-- with it and replayed on every hit: `saved_prompt_tokens` is a measurement of
-- a real past call, not an estimate of a hypothetical one.
--
-- NULL IS NOT ZERO, and the UI must not render it as such. Every column here is
-- nullable because history cannot be backfilled: NULL means "before this
-- migration" or "the provider did not report it", while 0 is a real
-- measurement. Collapsing the two is how a usage dashboard starts lying.
--
-- SAFETY: additive. Nullable columns and two indexes; no existing row is read
-- or written, and an unapplied 0027 simply leaves the Usage page with nothing
-- to show for those metrics.

alter table public.usage_events
  -- Which model produced the tokens. Text, not an FK: models come and go from
  -- the catalog, and a usage row must stay readable after one is retired.
  add column if not exists model text,
  -- Cost computed AT WRITE TIME from the price in effect then. Deriving it at
  -- read time would let a price change rewrite every past invoice.
  add column if not exists cost_usd numeric(12, 6),
  -- Tokens NOT spent because L1/L2 served this request. Set only on a cache
  -- hit; NULL on a miss, which is different from 0 (a hit that saved nothing).
  add column if not exists saved_prompt_tokens integer,
  add column if not exists saved_completion_tokens integer,
  -- 'l1' | 'l2' | NULL, mirroring query_logs so savings can be attributed to
  -- the layer that produced them without a join.
  add column if not exists cache_layer text;

alter table public.query_logs
  -- Mean similarity of the chunks that were actually used. The single best
  -- signal for "is retrieval working on this project", and today it is computed
  -- and discarded.
  add column if not exists retrieval_similarity real,
  -- How close the L2 semantic-cache match was. Needed to tell whether
  -- semantic_cache_min_similarity (0.75) is too loose - a threshold nobody can
  -- currently evaluate because the evidence is thrown away.
  add column if not exists cache_similarity real;

-- The Usage page always filters by owner and a time window, and the account
-- scope is the SECURITY boundary - one account must never see another's rows.
-- Leading with owner_id keeps that filter index-backed rather than a scan.
create index if not exists usage_events_owner_time_idx
  on public.usage_events (owner_id, created_at desc);

-- Per-project cache and similarity aggregates over a window.
create index if not exists query_logs_project_time_idx
  on public.query_logs (project_id, created_at desc);
