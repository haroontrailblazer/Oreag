-- Report what the Matryoshka archive saves, as a measurement rather than a claim.
--
-- WHAT HAPPENS TODAY
--
-- Shrinking a project's embedding dimension cuts each vector to a prefix in
-- SQL, keeping the widest vector ever held in `embedding_full` (0024). Growing
-- back then RESTORES the exact bytes instead of calling the provider again -
-- the whole point of the archive, and on a large corpus the single biggest
-- avoided cost in the product.
--
-- It was completely invisible. A grow-back showed up nowhere: no usage row, no
-- number, nothing to distinguish "restored ten thousand chunks for free" from
-- "did nothing".
--
-- WHY A COLUMN ON files, AND NOT A CALCULATION
--
-- The saving is "what re-embedding these chunks WOULD have cost". There is no
-- way to know that at restore time without doing the very work being avoided.
-- So the answer has to come from the past: `files.embedding_tokens` records
-- what the file actually cost to embed when it was ingested, and a restore
-- replays that figure.
--
-- Exactly the discipline `saved_prompt_tokens` already follows for the answer
-- cache: a saving is a REPLAYED MEASUREMENT, never an estimate. Files ingested
-- before this column existed have NULL, so their restore reports an unmeasured
-- saving rather than a fabricated one.
alter table files
  add column if not exists embedding_tokens integer;

alter table usage_events
  add column if not exists saved_embedding_tokens integer,
  add column if not exists saved_embedding_cost_usd numeric(12, 6);

comment on column files.embedding_tokens is
  'Tokens this file cost to embed at ingest. Replayed as the saving when a '
  'Matryoshka grow-back restores its vectors instead of re-embedding. '
  'NULL for files ingested before metering existed.';
comment on column usage_events.saved_embedding_tokens is
  'Embedding tokens NOT spent because vectors were restored from the archive.';
comment on column usage_events.saved_embedding_cost_usd is
  'USD value of the above, priced from the project embedding model. NULL when unpriced.';
