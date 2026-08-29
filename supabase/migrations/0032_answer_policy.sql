-- Per-project answer policy: how sure the loop must be, and how it must speak.
--
-- WHY THESE FOUR, AND WHY ON THE PROJECT
--
-- Grounding and answer framing were global (config.py agentic_min_similarity,
-- agentic_min_strong; the two prompt constants in generation.py), so every
-- project on the deployment shared one posture. That is wrong the moment one
-- project is a regulatory corpus and another is lecture notes: the first must
-- refuse far sooner than the second, and must carry a standing disclaimer the
-- second has no use for.
--
-- NOT NULL WITH DEFAULTS, NOT NULLABLE-INHERIT
--
-- The obvious shape is `null = inherit the global setting`. It was rejected:
-- 0.0 and 0 are MEANINGFUL values here ("never abstain"), so every read site
-- would need `is not None` rather than `or`, and one `or` slipping in silently
-- restores the global default while the UI shows 0. Defaulting in SQL removes
-- the ambiguity - every project carries an explicit, visible policy, and the
-- defaults below reproduce today's behaviour exactly, so no existing project
-- changes when this migration runs.
--
-- The global settings stay as the seed for NEW projects (models.py reads them
-- for the ORM-side default); they no longer steer projects that already exist,
-- which is the point.

alter table public.projects
  add column if not exists min_similarity real not null default 0.2,
  add column if not exists min_strong integer not null default 1,
  add column if not exists answer_language text,
  add column if not exists answer_disclaimer text;

-- Bounds match the API validators, so a bad write is rejected by the database
-- even if it arrives from outside FastAPI (psql, a future service, a migration).
-- Cosine similarity is bounded 0..1; min_strong 0 means "never abstain".
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'projects_min_similarity_range'
  ) then
    alter table public.projects
      add constraint projects_min_similarity_range
      check (min_similarity >= 0 and min_similarity <= 1);
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'projects_min_strong_range'
  ) then
    alter table public.projects
      add constraint projects_min_strong_range
      check (min_strong >= 0 and min_strong <= 20);
  end if;
end $$;

comment on column public.projects.min_similarity is
  'Cosine a retrieved chunk must clear to count as grounding. Raise it for a '
  'corpus where a wrong answer is expensive. 0 = never abstain on score.';
comment on column public.projects.min_strong is
  'How many chunks must clear min_similarity before the loop may answer. '
  '0 = never abstain; the default 1 reproduces the pre-0032 global behaviour.';
comment on column public.projects.answer_language is
  'Force every answer into this language (e.g. "Hindi"). NULL = mirror the '
  'language the question was asked in.';
comment on column public.projects.answer_disclaimer is
  'Sentence appended verbatim to every answer, e.g. an "information, not legal '
  'advice" notice. NULL = none.';
