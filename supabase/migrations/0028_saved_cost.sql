-- Price a cache hit's saving exactly, instead of estimating it.
--
-- WHAT WAS WRONG
--
-- 0027 stored `saved_prompt_tokens` / `saved_completion_tokens`: a real
-- measurement, replayed from what the cached answer originally cost. But there
-- was nowhere to store what those tokens were WORTH, so the Usage page derived
-- a dollar figure by blending the window's measured $/token across every model
-- the account used. That number was an estimate wearing the same styling as
-- the measured ones - and it drifted with the mix of models in the window, so
-- the "saved" figure for a fixed set of cache hits changed as unrelated
-- traffic arrived.
--
-- THE FIX
--
-- The cached answer now also carries WHICH model produced it
-- (`AgenticResult.gen_model`), so a hit prices its own saving through exactly
-- the same table a live call uses. Stored at write time for the same reason
-- `cost_usd` is: a later price change must not silently rewrite history.
--
-- NULL, never 0, when the model has no listed price or the original run went
-- unmeasured. An unpriceable saving reads as "not measured" rather than as a
-- saving of nothing.
alter table usage_events
  add column if not exists saved_cost_usd numeric(12, 6);

comment on column usage_events.saved_cost_usd is
  'USD the cache hit did NOT spend, priced from the tokens and model of the '
  'original run. NULL = unpriced or unmeasured, never an estimate.';
