-- Rollback for migration 0027 (two-factor prompt preference).
--
-- 0027 was applied to the live database and then the feature it supported was
-- reverted, so `public.user_security_prefs` and
-- `public.two_factor_prompt_enabled()` have no readers left anywhere in the
-- codebase. They were inert, not broken - the second-factor gate went back to
-- deciding purely on whether a verified factor exists, which is the behaviour
-- that predates 0027.
--
-- NOT a numbered migration: 0027 no longer exists in supabase/migrations, so
-- adding an 0028 to undo a file nobody can read would be more confusing than a
-- one-off script. If the feature is ever revived, restore 0027 from git history
-- (`git show 12746ae -- supabase/migrations/`) rather than reversing this.
--
-- WHAT IS LOST: one row per user holding a single boolean preference. At the
-- time of writing that was exactly one row (two_factor_prompt = false). Nothing
-- reads it, so dropping it changes no behaviour.
--
-- Order matters: the function does not depend on the table at plan time, but
-- dropping it first means a concurrent call cannot hit a half-removed pair.

drop function if exists public.two_factor_prompt_enabled(uuid);
drop table if exists public.user_security_prefs;
