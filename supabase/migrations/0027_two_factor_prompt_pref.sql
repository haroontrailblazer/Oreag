-- Turn the second-factor PROMPT off without destroying the factor.
--
-- THE PROBLEM
--
-- Supabase gives a factor exactly two states, `verified` and `unverified`.
-- There is no "keep it but stop asking", so the only way to stop prompting was
-- `mfa.unenroll()` - which deletes the TOTP secret. Turning two-factor back on
-- then meant scanning a fresh QR code, and anyone who toggled it off to debug
-- something lost their enrolment for good.
--
-- WHY A TABLE AND NOT user_metadata
--
-- `raw_user_meta_data` is writable by the user's own access token, and it rides
-- in the JWT - so a stolen aal1 session could set "two-factor off" on itself and
-- walk straight past the gate. That is a complete 2FA bypass. The preference
-- has to live somewhere only the server writes, which is why this is a table
-- with deny-all RLS rather than a metadata key.
--
-- WHY IT IS SAFE TO HONOUR
--
-- Turning your own second factor off is already something the account owner can
-- do (by removing the factor). This changes what that costs them, not who is
-- allowed to do it. The row is only reachable through an authenticated
-- dashboard route, and the default is ON: a missing row means "prompt me",
-- so an unapplied migration or a failed read can never silently disable 2FA.
--
-- SAFETY: additive. One table and one function. Nothing existing is read or
-- written, and with 0027 unapplied `two_factor_prompt_enabled()` is absent, so
-- backend/app/services/mfa.py falls back to "enabled" and behaviour is exactly
-- what it is today.

create table if not exists public.user_security_prefs (
  user_id            uuid primary key references auth.users(id) on delete cascade,
  -- TRUE means "ask me for my second factor when I sign in". Default true so a
  -- row that exists for some other reason never weakens the account.
  two_factor_prompt  boolean not null default true,
  updated_at         timestamptz not null default now()
);

-- Deny-all RLS: the backend reaches this with the service role, and no browser
-- has any business writing its own 2FA policy. Mirrors 0019/0021.
alter table public.user_security_prefs enable row level security;
create policy "owner full access" on public.user_security_prefs
  for all using (user_id = auth.uid());

-- SECURITY DEFINER so the API can ask without granting table access, in the
-- shape of `user_has_verified_mfa` (0019).
--
-- `set search_path = ''` and fully-qualified names: a table of the same name on
-- the caller's search_path would otherwise shadow this one, and the function
-- runs as its owner.
create or replace function public.two_factor_prompt_enabled(p_user_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  -- coalesce, not `= true`: NO ROW means the user never turned it off, which is
  -- the protected state. Defaulting the other way would disable 2FA for every
  -- account that has not visited the setting.
  select coalesce(
    (select p.two_factor_prompt
       from public.user_security_prefs p
      where p.user_id = p_user_id),
    true
  );
$$;

revoke all on function public.two_factor_prompt_enabled(uuid) from public, anon;
grant execute on function public.two_factor_prompt_enabled(uuid) to authenticated, service_role;

comment on table public.user_security_prefs is
  'Per-user security preferences. two_factor_prompt=false means "keep my enrolled factors but do not challenge me at sign-in" - Supabase has no disabled-factor state, so without this the only way to stop prompting was to delete the factor.';
