-- Teach the identifier-first login lookup about passkeys.
--
-- WHY
--
-- The login page should only offer "Continue with a passkey" to an account that
-- actually has one. Offering it to everybody produces a button that opens the
-- system prompt and then fails with nothing to select - which reads as broken
-- software, not as "you have no passkey".
--
-- WHERE PASSKEYS LIVE - verified against the live database, because the two
-- kinds of WebAuthn credential are NOT in the same place:
--
--   auth.webauthn_credentials   <- passkeys registered as a LOGIN method
--                                  (auth.registerPasskey / auth.passkey.*)
--   auth.mfa_factors            <- second factors: totp, phone, and webauthn
--                                  enrolled through mfa.enroll()
--
-- Checking only mfa_factors - the obvious guess - would report has_passkey
-- false for every real passkey user and the button would never appear.
--
-- SAFETY: replaces one function in place, additive fields only. Both new keys
-- are computed behind to_regclass guards, so on a Supabase version without
-- these tables the function still returns the original three keys and the
-- login page behaves exactly as it did before. The existing callers read
-- `exists`, `has_password` and `providers` by name and are unaffected.
--
-- Same privilege posture as 0017: service_role only. This answers a question
-- about an arbitrary email address, so anon/authenticated must not have it -
-- it would let anyone enumerate which accounts have passkeys, which is useful
-- reconnaissance when choosing a phishing target.

create or replace function public.auth_methods_for_email(p_email text)
returns jsonb
language plpgsql
security definer
set search_path = auth, public
as $$
declare
  u_id           uuid;
  u_has_password boolean;
  provs          text[];
  has_passkey    boolean := false;
  has_mfa        boolean := false;
begin
  select id, (encrypted_password is not null and encrypted_password <> '')
    into u_id, u_has_password
  from auth.users
  where lower(email) = lower(p_email)
  limit 1;

  if u_id is null then
    -- Shape must match the found branch exactly. A missing key is not the same
    -- as false to the TypeScript caller, and an undefined `has_passkey` is
    -- falsy by accident rather than by decision.
    return jsonb_build_object(
      'exists', false,
      'has_password', false,
      'providers', '[]'::jsonb,
      'has_passkey', false,
      'has_mfa', false
    );
  end if;

  -- OAuth providers only; the password credential shows as provider 'email'.
  select coalesce(
    array_agg(distinct provider) filter (
      where provider is not null and provider <> 'email'
    ),
    '{}'
  )
    into provs
  from auth.identities
  where user_id = u_id;

  -- Login passkeys. Guarded: this table does not exist on older Supabase.
  if to_regclass('auth.webauthn_credentials') is not null then
    execute
      'select exists (select 1 from auth.webauthn_credentials where user_id = $1)'
      into has_passkey
      using u_id;
  end if;

  -- Any VERIFIED second factor. Unverified rows are deliberately excluded: an
  -- abandoned enrolment must not change what the login page offers.
  if to_regclass('auth.mfa_factors') is not null then
    execute
      'select exists (select 1 from auth.mfa_factors where user_id = $1 and status = ''verified'')'
      into has_mfa
      using u_id;
  end if;

  return jsonb_build_object(
    'exists', true,
    'has_password', coalesce(u_has_password, false),
    'providers', to_jsonb(provs),
    'has_passkey', coalesce(has_passkey, false),
    'has_mfa', coalesce(has_mfa, false)
  );
end;
$$;

revoke all on function public.auth_methods_for_email(text) from public, anon, authenticated;
grant execute on function public.auth_methods_for_email(text) to service_role;

comment on function public.auth_methods_for_email(text) is
  'Identifier-first login lookup: which sign-in methods this email has. '
  'has_passkey reads auth.webauthn_credentials (login passkeys), NOT '
  'auth.mfa_factors - the two are separate tables. service_role only.';
