-- Per-project cross-lingual translation threshold.
--
-- WHY THIS IS NOT A GLOBAL CONSTANT ANY MORE. The cross-lingual path embeds a
-- TRANSLATION of the question when the search as asked came back weak, and
-- "weak" was one number - settings.cross_lingual_similarity_floor, 0.40 -
-- shared by every project on the server.
--
-- That number is not portable, because this product is BYOK and a project may
-- be on any of 22 embedding models. Models place their score distributions
-- differently: some compress every cosine into 0.7-0.9, others spread across
-- 0.0-0.6. A floor calibrated against text-embedding-3-small is a materially
-- different question when asked of gemini-embedding-001, and no vendor
-- publishes what would let the right value be derived rather than measured.
--
-- NULL MEANS AUTO, and that is why the column is nullable with no DEFAULT.
-- Backfilling 0.40 would assert that the old global value is correct for every
-- existing project on every model, which is the claim this migration exists to
-- retract. NULL is "we have not been told", which is a different fact from any
-- number and the only honest thing to store. Every existing project therefore
-- keeps exactly today's behaviour, and nothing needs re-indexing or
-- re-embedding - this changes WHEN a translation is made, never what is
-- indexed, so it does not touch content_version.
--
-- 0.0 IS A REAL SETTING - "never translate, this embedder is fine" - which is
-- why readers must test against NULL rather than falsiness. The CHECK admits
-- both ends: services/cross_lingual.py::floor_for compares `is None`, the same
-- trap models.py already documents for min_similarity.

alter table public.projects
  add column if not exists cross_lingual_floor double precision;

alter table public.projects
  drop constraint if exists projects_cross_lingual_floor_range;

alter table public.projects
  add constraint projects_cross_lingual_floor_range
  check (cross_lingual_floor is null
         or (cross_lingual_floor >= 0 and cross_lingual_floor <= 1));

comment on column public.projects.cross_lingual_floor is
  'Similarity below which a search counts as failed and the cross-lingual path '
  'embeds a translation instead. NULL = use the server default; 0 = never '
  'translate. Per-project because a cosine is not comparable across embedding '
  'models.';
