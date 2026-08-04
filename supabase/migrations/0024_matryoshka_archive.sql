-- Reversible Matryoshka shrink: growing a dimension back must not re-embed.
--
-- THE PROBLEM
--
-- Shrinking 3072 -> 1536 ran
--   UPDATE chunks SET embedding = l2_normalize(subvector(embedding, 1, 1536))
-- which OVERWRITES the row. The upper half is deleted, not hidden. Growing back
-- to 3072 therefore had nothing to read and fell through to a full re-embed,
-- charging the user again for numbers they had already paid to compute.
--
-- WHY NOT JUST KEEP THE WIDE VECTOR AND CAST DOWN WHEN SEARCHING
--
-- Because that would silently disable HNSW for exactly the projects that shrank
-- in order to get it. Migration 0018 builds PARTIAL indexes
--   ... using hnsw ((embedding::vector(D)) ...) where vector_dims(embedding) = D
-- and services/retrieval.py filters "AND vector_dims(c.embedding) = {dim}".
-- pgvector cannot HNSW-index above 2000 dimensions, so a 3072 project is
-- exact-scan only; shrinking to 1536 is how it becomes indexable. `embedding`
-- must therefore keep the ACTIVE width, and the original has to live elsewhere.
--
-- THE SHAPE
--
-- embedding_full holds the full-fidelity original beside the active vector.
-- Dimensionless `vector`, mirroring the column it shadows: vector_dims() IS the
-- restorable width, so there is no second width column that could disagree with
-- the data it describes, and NULL has exactly one meaning - "embedding is
-- already full fidelity, there is nothing archived". Never searched, never
-- indexed, so it costs nothing but bytes and the 0018 indexes never see it.
--
-- projects.embedding_native_dimensions records the width this project's vectors
-- were originally computed at. It is what makes archiving CONDITIONAL: a
-- project that never shrinks never writes an archive byte. Without it, "active
-- < model native" would archive for a project deliberately born at 512, which
-- would pay 6x storage for a restore it never asked for.
--
-- SAFETY: additive, nullable, no defaults - catalog-only, no table rewrite.
-- Every existing row reads NULL, which means "nothing archived", which is
-- exactly today's behaviour.
--
-- DEPLOY ORDER: apply this BEFORE deploying the code. The application degrades
-- deliberately if you do not (it keeps today's destructive-but-free shrink
-- rather than demoting to a paid re-embed - see _archive_supported in
-- backend/app/routers/files.py), but the reversibility this migration exists
-- for is simply absent until it runs.
--
-- The ALTERs are catalog-only yet still take ACCESS EXCLUSIVE for an instant.
-- On a busy table that lock queues behind any long-running scan, and everything
-- else then queues behind IT. Fail fast and retry instead - same operational
-- caution as 0018.
set local lock_timeout = '5s';

alter table public.chunks   add column if not exists embedding_full vector;
alter table public.memories add column if not exists embedding_full vector;
alter table public.projects
  add column if not exists embedding_native_dimensions integer;

comment on column public.chunks.embedding_full is
  'Full-fidelity original of embedding, banked by a Matryoshka shrink so growing back never re-embeds. NULL = embedding IS full fidelity, or the tail predates this column and is gone for good. Width is self-describing via vector_dims(). Never searched, never indexed.';
comment on column public.memories.embedding_full is
  'Same contract as chunks.embedding_full. MUST be nulled alongside memories.embedding on a model switch - an archive from the old model belongs to an incompatible vector space.';
comment on column public.projects.embedding_native_dimensions is
  'Width this project''s vectors were originally computed at. NULL or equal to embedding_dimensions means never shrunk, so nothing is archived and ingestion embeds at the active width. Greater than embedding_dimensions means the project is shrunk: ingestion embeds at this width and banks it.';
