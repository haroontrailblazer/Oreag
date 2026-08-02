-- Recovery codes: the way back in when the authenticator app is gone.
--
-- THE PROBLEM
--
-- Supabase ships no backup codes. With server-side aal2 enforcement in place
-- (migration 0019), losing the phone that holds the TOTP secret means every
-- API call returns 403 for ever. There is no self-service route out, and the
-- only alternative is an operator manually deleting the factor - which does not
-- scale past a handful of users and is a social-engineering target.
--
-- WHY A CODE CANNOT SIMPLY "LOG YOU IN"
--
-- The assurance level is Supabase's to grant: only a real factor verification
-- produces an aal2 session, and nothing in this application can mint one. So a
-- recovery code does not raise the level - it REMOVES the factor. Afterwards
-- the account genuinely has no second factor, aal1 is the correct level for it,
-- and `user_has_verified_mfa` returns false, so the gate in
-- backend/app/auth/jwt.py opens on its own. The user is then asked to enrol
-- again. This is what GitHub does with its recovery codes, and it is the only
-- shape that works without owning the token issuer.
--
-- SAFETY: additive. One table and one function; nothing existing is touched.
-- An unapplied 0021 simply means the recovery UI reports that no codes are
-- configured - it cannot break sign-in.

create table if not exists public.mfa_recovery_codes (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  -- sha256 of the plaintext. Storing codes recoverably would make this table a
  -- second-factor bypass sitting in the same database as everything else.
  code_hash   text not null,
  used_at     timestamptz,
  created_at  timestamptz not null default now()
);

-- One lookup shape: "unused codes for this user".
create index if not exists mfa_recovery_codes_user_idx
  on public.mfa_recovery_codes (user_id) where used_at is null;

-- A user must never read their own hashes: possession of the hash plus the
-- algorithm is enough to work offline against a weak code. Only the backend,
-- which connects with elevated credentials, touches this table.
alter table public.mfa_recovery_codes enable row level security;
revoke all on public.mfa_recovery_codes from anon, authenticated;

comment on table public.mfa_recovery_codes is
  'One-way hashes of single-use MFA recovery codes. Consuming one removes the '
  'user''s second factors (see public.remove_mfa_factors) - it does not grant aal2, '
  'which only Supabase can issue.';


-- Deleting from auth.mfa_factors needs privileges the application role does not
-- have, and Supabase refuses an unenroll from the aal1 session a locked-out
-- user necessarily has. SECURITY DEFINER crosses that boundary with the
-- narrowest possible surface: one user id in, a count out, nothing else
-- readable or writable.
create or replace function public.remove_mfa_factors(p_user uuid)
returns integer
language plpgsql
security definer
-- Pinned so nobody can shadow auth.mfa_factors with their own table and turn
-- this into a no-op that silently leaves the account locked.
set search_path = auth, pg_catalog
as $$
declare
  removed integer;
begin
  delete from auth.mfa_factors where user_id = p_user;
  get diagnostics removed = row_count;
  return removed;
end;
$$;

comment on function public.remove_mfa_factors(uuid) is
  'Deletes every MFA factor for a user. Called only after a valid recovery code '
  'has been consumed. Not granted to anon or authenticated: it would otherwise '
  'let any signed-in caller strip their own second factor and defeat the point.';

revoke all on function public.remove_mfa_factors(uuid) from public, anon, authenticated;
grant execute on function public.remove_mfa_factors(uuid) to service_role;
