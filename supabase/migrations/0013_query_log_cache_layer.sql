-- Record which cache served each query so the dashboard can show a real
-- PROJECT-WIDE cache hit rate (across the playground AND the public API),
-- instead of a per-chat-session count.
--
-- "l1" = exact-match (Redis) hit, "l2" = semantic (pgvector) hit, NULL = the
-- answer was computed fresh. Existing rows stay NULL (counted as misses).

alter table public.query_logs
  add column if not exists cache_layer text;
