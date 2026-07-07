-- Suspend a project without deleting it: pauses all external access (the public
-- /v1 API and the MCP server return 403) while keeping every key, file, chunk
-- and memory intact. The owner can resume it from the dashboard at any time.

alter table public.projects
  add column if not exists suspended boolean not null default false;
