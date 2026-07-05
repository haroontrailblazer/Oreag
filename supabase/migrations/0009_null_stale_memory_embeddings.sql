-- Clean up memory embeddings left behind by embedding-model switches that
-- happened BEFORE the vector-migration fix (backend now nulls + re-embeds
-- memories on every model change, and truncates them in place on a same-model
-- Matryoshka shrink).
--
-- A memory vector whose dimension no longer matches its project's
-- embedding_dimensions is from an old model's space: comparing it aborts
-- pgvector with "different vector dimensions", which used to 500 every query
-- on the project. Null them out - unembedded memories are skipped by search
-- (embedding IS NOT NULL) and get a fresh vector on the next model change or
-- re-save.
--
-- Same-dimension cross-model staleness cannot be detected from the data alone;
-- those vectors are cleaned up by the next re-index / model change.

update memories m
set embedding = null
from projects p
where p.id = m.project_id
  and m.embedding is not null
  and vector_dims(m.embedding) <> p.embedding_dimensions;
