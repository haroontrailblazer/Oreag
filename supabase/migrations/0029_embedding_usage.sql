-- Record embedding spend, which was invisible and is probably the largest.
--
-- WHAT WAS MISSING
--
-- `usage_events` had ONE model and ONE pair of token counts per row, which
-- fits a chat call and nothing else. But a `/query` uses two models - an LLM
-- to answer and an embedder to retrieve - and ingestion uses ONLY an embedder:
-- every chunk of every uploaded file, every memory, every semantic-cache
-- probe. Those rows existed (`files_upload`, `memory_create`) with NULL tokens
-- and NULL cost, so the Usage page showed a document-heavy account spending
-- nothing at all.
--
-- WHY SEPARATE COLUMNS RATHER THAN ADDING TO prompt_tokens
--
-- Embedding tokens are 10-100x cheaper than chat tokens. Summing them into
-- `prompt_tokens` would produce a single number that prices correctly for
-- neither, and "tokens by model" - the breakdown the page is built around -
-- would attribute an embedder's volume to whichever LLM shared the row.
-- Kept apart, each is priced through the table that applies to it and the two
-- can still be added when a single total is what is wanted.
--
-- NULL discipline is unchanged: a provider that does not report embedding
-- usage (local models, and some hosted ones) leaves these NULL, which reads as
-- "not measured" and never as zero.
alter table usage_events
  add column if not exists embedding_tokens integer,
  add column if not exists embedding_model text,
  add column if not exists embedding_cost_usd numeric(12, 6);

comment on column usage_events.embedding_tokens is
  'Input tokens consumed by the EMBEDDER during this request (retrieval, '
  'ingestion, memory, cache probes). NULL = the provider did not report it.';
comment on column usage_events.embedding_model is
  'Which embedding model consumed them - distinct from `model`, which is the LLM.';
comment on column usage_events.embedding_cost_usd is
  'USD for the embedding tokens, priced at write time. NULL when unpriced.';
