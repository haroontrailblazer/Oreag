-- Server-side two-factor enforcement: let the API answer "does this user have
-- a second factor?" without granting it read access to the auth schema.
--
-- WHY THIS EXISTS AT ALL
--
-- Supabase puts an `aal` (authenticator assurance level) claim in every access
-- token: `aal1` for a conventional sign-in, `aal2` once a second factor has
-- been cleared. Checking that claim is only half an enforcement rule, because
-- `aal1` is also the correct level for a user who has no second factor. The
-- other half is knowing whether this user was SUPPOSED to reach aal2 - which
-- lives in auth.mfa_factors, a table the application role cannot read.
--
-- A SECURITY DEFINER function is the standard way across that boundary: it
-- runs as its owner, returns a single boolean, and exposes nothing else about
-- the factors (no ids, no secrets, no friendly names, not even a count). Same
-- shape and same reasoning as auth_methods_for_email in 0017.
--
-- WITHOUT THIS, the two-factor prompt is decoration. The frontend asks
-- getAuthenticatorAssuranceLevel() and shows a code field, but nothing stops a
-- caller from taking the aal1 access token straight out of local storage and
-- calling the API with curl. The gate has to be server-side or it is not a gate.
--
-- SAFETY: additive and idempotent. Creates one function and grants EXECUTE to
-- the roles the backend actually connects as. Dropping it is a no-op for
-- correctness - backend/app/services/mfa.py treats a missing function as
-- "cannot determine, do not block", so an unapplied 0019 leaves the API
-- behaving exactly as it did before.

create or replace function public.user_has_verified_mfa(p_user uuid)
returns boolean
language sql
security definer
-- Pin the search path. Without it, a caller who can create objects in a
-- schema earlier on their own search_path could shadow `auth.mfa_factors`
-- and make this function answer false for everyone - silently disabling
-- two-factor enforcement account-wide.
set search_path = auth, pg_catalog
stable
as $$
  select exists (
    select 1
      from auth.mfa_factors f
     where f.user_id = p_user
       and f.status = 'verified'
  );
$$;

comment on function public.user_has_verified_mfa(uuid) is
  'True when the user has at least one VERIFIED MFA factor (passkey, TOTP or phone). '
  'Read by the API to decide whether an aal1 access token is acceptable. '
  'Unverified factors are deliberately excluded: a half-finished enrolment must '
  'never lock anybody out.';

-- The anon role is deliberately NOT granted. This answers a question about an
-- arbitrary user id, so letting an unauthenticated caller ask it would leak
-- which accounts have two-factor enabled - useful reconnaissance for choosing
-- a phishing target.
revoke all on function public.user_has_verified_mfa(uuid) from public;
grant execute on function public.user_has_verified_mfa(uuid) to authenticated;
grant execute on function public.user_has_verified_mfa(uuid) to service_role;
