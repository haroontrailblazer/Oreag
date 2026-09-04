-- Let a project's answer language be a DEFAULT rather than an override.
--
-- Since 0032 `answer_language` has meant exactly one thing: "write the entire
-- answer in this language, regardless of the language of the question or of
-- the source material". That is the right behaviour for a fixed audience - a
-- public help centre, a regulator-facing assistant - and it is the wrong
-- behaviour for a project whose users do not all read the same language,
-- because a question asked in Hindi comes back in English.
--
-- The two needs are genuinely different and cannot both be served by one
-- setting, so this adds the missing half:
--
--   answer_language_strict = true   answer in that language, always  (today)
--   answer_language_strict = false  answer in the question's language,
--                                   falling back to that language when it
--                                   cannot be determined
--
-- DEFAULT TRUE, and that matters: every project that has already chosen a
-- language chose it under the old meaning, and a migration must not quietly
-- change what their answers look like. The new behaviour is opt-in.
--
-- Nothing is indexed from this and nothing is re-embedded. It is read at the
-- single generation chokepoint, and it joins the answer-cache signature in
-- services/query.py, because it changes the ANSWER without changing the
-- CONTENT - exactly like the four answer-policy columns 0032 added.
--
-- No percent sign anywhere in this file: psycopg scans the whole statement
-- text for placeholders and scripts/apply_migration.py would refuse it.

alter table public.projects
  add column if not exists answer_language_strict boolean not null default true;

comment on column public.projects.answer_language_strict is
  'How answer_language is applied. TRUE: every answer is written in it, whatever language the question used. FALSE: answers follow the question''s own language and fall back to answer_language only when that cannot be determined. Ignored when answer_language is NULL, which already means "always match the question".';
