-- Cache the model list each provider key can actually reach.
--
-- THE PROBLEM
--
-- The model pickers are driven by a hardcoded catalog in
-- backend/app/providers/registry.py. It cannot know what any particular key is
-- entitled to, and it rots: "text-embedding-004" was offered for months after
-- Google retired it (a direct call 404s), so choosing it built a project that
-- could never index a single file. The same class of failure applies to every
-- provider - project-level model allowlists on OpenAI, workspace scoping on
-- Anthropic, free-vs-paid tiers everywhere.
--
-- WHY THE LIST LIVES HERE AND NOT IN A CACHE
--
-- GET /api/models is on the dashboard load path. Fetching 16 vendors there -
-- even behind a TTL cache - means a cold cache after every deploy, a stampede
-- across Render's workers, and one slow vendor delaying the whole response.
-- Fetching it when the KEY IS SAVED moves that cost onto an action the user is
-- already waiting on, happens once, and survives restarts. /api/models then
-- does no vendor I/O at all.
--
-- SHAPE
--
-- models_json is the parsed result, not the raw vendor payload:
--   {"models": ["gpt-4o", "text-embedding-3-small", ...], "key_scoped": true}
--
-- Just the SET OF IDS, deliberately not split by role. The static catalog
-- already records which of its own entries are embedding models and which are
-- chat models, so the merge is a membership test and nothing here has to
-- classify. That matters because most vendors cannot be classified reliably -
-- OpenAI's /v1/models returns only id/object/created/owned_by, with no
-- capability field at all, so any split would be prefix guesswork.
--
-- key_scoped is false for vendors whose /models is PUBLIC (sarvam, jina): such
-- a list describes the vendor, not the key, so it must never hide anything.
-- NULL means "never successfully fetched", which reads as "show the full static
-- catalog" - the fail-open default that keeps a working key usable when a
-- vendor is down, when a restricted OpenAI key is allowed to embed but not to
-- call /v1/models, or when the vendor serves no models endpoint at all (voyage
-- and perplexity).
--
-- SAFETY: additive, nullable, no backfill. Every existing row reads as NULL and
-- therefore behaves exactly as it does today. An unapplied 0022 means the
-- feature is simply inert.

alter table public.provider_keys
  add column if not exists models_json jsonb,
  add column if not exists models_fetched_at timestamptz;

comment on column public.provider_keys.models_json is
  'Parsed per-key model list: {llm:[], embedding:[], key_scoped:bool}. NULL = never fetched; readers fall back to the full static catalog.';
comment on column public.provider_keys.models_fetched_at is
  'When models_json was last refreshed. Drives the "last checked" hint in Settings.';
