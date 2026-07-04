-- BYOK provider credentials. Users supply their own OpenAI / Gemini / Anthropic
-- keys instead of a shared server key. Keys are encrypted by the app layer
-- (Fernet) before they ever reach the database - `encrypted_key` is ciphertext,
-- never plaintext. `last4` is for masked display only.

-- Account-level keys: one per (owner, provider), reused across all the user's
-- projects unless a project overrides it (columns below).
create table public.provider_keys (
  id            uuid primary key default gen_random_uuid(),
  owner_id      uuid not null references auth.users(id) on delete cascade,
  provider      text not null,            -- 'openai' | 'gemini' | 'anthropic'
  label         text not null default 'default',
  encrypted_key text not null,
  last4         text not null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (owner_id, provider)
);
create index provider_keys_owner_idx on public.provider_keys(owner_id);

-- Per-project overrides. Two slots because a project can mix providers
-- (e.g. Gemini embeddings + Anthropic LLM), each needing its own key. When null,
-- resolution falls back to the owner's account-level key for that provider.
alter table public.projects
  add column if not exists embedding_key_encrypted text,
  add column if not exists embedding_key_last4 text,
  add column if not exists llm_key_encrypted text,
  add column if not exists llm_key_last4 text;

-- RLS (defense-in-depth; the backend uses the service role and enforces
-- ownership in code). Mirrors 0002_rls.sql.
alter table public.provider_keys enable row level security;
create policy "owner full access" on public.provider_keys
  for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());
