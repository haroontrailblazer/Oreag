-- Per-file chunking overrides. When null, ingestion falls back to the project's
-- chunk_size / chunk_overlap. Embedding model stays project-wide (uniform vector
-- dimension), so it is NOT stored per file.
alter table public.files
  add column if not exists chunk_size int,
  add column if not exists chunk_overlap int;
