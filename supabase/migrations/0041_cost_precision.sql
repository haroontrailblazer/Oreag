-- Cost columns kept six decimal places, which priced real spend at zero.
--
-- NUMERIC(12,6) has a quantum of $0.000001. Per-token prices are three to five
-- orders of magnitude smaller than that: text-embedding-3-small is $0.02 per
-- million tokens, so a 20-token embedding - a memory write, a semantic-cache
-- probe, a short query - costs $0.0000004 and was stored as exactly 0.000000.
--
-- That is not a rounding nit. `registry.py` is explicit that NULL means "we
-- could not price this" and 0 means "this was measured and it was free", and
-- the whole Usage page is built on that distinction. Quantising a real charge
-- down to a MEASURED zero is precisely the lie the rule exists to prevent, and
-- it is silent: nothing errors, the row just says the call was free.
--
-- Ten decimal places holds one token of the cheapest rate in either price
-- table (text-embedding-3-small, $0.02/Mtok = $0.00000002 per token) with two
-- decimal places still to spare.
-- The precision goes to 18 so the integer part still reaches $99,999,999 -
-- widening the scale alone would have shrunk the range.
--
-- THIS REWRITES THE TABLE. An earlier draft of this comment said the opposite
-- and it was wrong, which is worse than saying nothing: Postgres relabels a
-- numeric without touching the heap ONLY when the scale is unchanged and the
-- precision grows (numeric_transform), so numeric(12,6) -> numeric(18,6) would
-- have been free. Changing the SCALE 6 -> 10 is a real coercion, so the whole
-- heap is rewritten under ACCESS EXCLUSIVE and roughly twice the table's size
-- in free space is needed while it runs.
--
-- usage_events is the busiest table in the system - every /v1 request, ingest,
-- judge and playground call writes one - so that lock blocks every read and
-- write to it for the duration. Run it when traffic is quiet, exactly as 0039
-- says of its own rewrite.
--
-- lock_timeout for the reason 0024 gives: on a busy table the ACCESS EXCLUSIVE
-- request queues behind any long-running scan, and every subsequent query then
-- queues behind IT. Failing after 5s is recoverable; a stampede is not.
--
-- Existing values are preserved exactly (0.000037 becomes 0.0000370000). Rows
-- already written keep whatever they were quantised to - this stops the loss,
-- it cannot recover it. Re-running is cheap: the second run finds the column
-- already at the target typmod and does no work.
set local lock_timeout = '5s';

alter table usage_events
  alter column cost_usd type numeric(18, 10),
  alter column saved_cost_usd type numeric(18, 10),
  alter column embedding_cost_usd type numeric(18, 10),
  alter column saved_embedding_cost_usd type numeric(18, 10);

comment on column usage_events.cost_usd is
  'USD for the LLM calls of this request, at the public list price recorded in '
  'providers/registry.py when the row was written. NULL when the model has no '
  'listed price or either token count was unmeasured - never 0 for those, '
  'because 0 is a real measurement. Ten decimal places: the cheapest rate in '
  'either price table is $0.00000002 per token.';
