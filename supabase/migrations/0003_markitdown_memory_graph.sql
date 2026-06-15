alter table public.files
  add column if not exists content_type text,
  add column if not exists source_extension text,
  add column if not exists markdown_storage_path text,
  add column if not exists conversion_error text;
