-- Per-key upload permission. API keys are read-only by default; only keys with
-- can_upload = true may POST documents to /v1/projects/{id}/files. This keeps a
-- leaked/consumption key from ingesting content (and incurring embedding cost).
alter table public.api_keys
  add column if not exists can_upload boolean not null default false;
