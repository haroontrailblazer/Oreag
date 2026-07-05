-- Lexical half of hybrid search: a Postgres full-text index over chunk text.
--
-- Retrieval now runs TWO searches per query - semantic (pgvector cosine, for
-- meaning/paraphrase) and lexical (this index, for exact terms like error
-- codes, names, and IDs that embeddings fumble) - and fuses the rankings with
-- Reciprocal Rank Fusion in the backend.
--
-- content_tsv is a GENERATED column: Postgres computes and maintains it
-- automatically on every insert/update, so the ingestion pipeline needs no
-- changes and existing rows are backfilled by this ALTER. The 'simple' config
-- is language-neutral (no English stemming): exact-token matching is exactly
-- the lexical half's job - the semantic half already handles paraphrase.

alter table public.chunks
  add column if not exists content_tsv tsvector
  generated always as (to_tsvector('simple', content)) stored;

create index if not exists chunks_content_tsv_idx
  on public.chunks using gin (content_tsv);
