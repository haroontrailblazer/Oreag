-- Identifier-first login helper (moved off the sleeping FastAPI backend into
-- the always-on Next.js app). A SECURITY DEFINER function reads the auth schema
-- and reports which sign-in methods an email has, so the login UI can route a
-- Google-only user straight to "Continue with Google" instead of a dead-end
-- "invalid credentials". EXECUTE is granted ONLY to service_role - it is called
-- from a Next.js route handler with the service key, never from the browser.
create or replace function public.auth_methods_for_email(p_email text)
returns jsonb
language plpgsql
security definer
set search_path = auth, public
as $$
declare
  u_id uuid;
  u_has_password boolean;
  provs text[];
begin
  select id, (encrypted_password is not null and encrypted_password <> '')
    into u_id, u_has_password
  from auth.users
  where lower(email) = lower(p_email)
  limit 1;

  if u_id is null then
    return jsonb_build_object(
      'exists', false, 'has_password', false, 'providers', '[]'::jsonb
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

  return jsonb_build_object(
    'exists', true,
    'has_password', coalesce(u_has_password, false),
    'providers', to_jsonb(provs)
  );
end;
$$;

revoke all on function public.auth_methods_for_email(text) from public, anon, authenticated;
grant execute on function public.auth_methods_for_email(text) to service_role;
