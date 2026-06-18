-- Public bucket for user profile pictures. Files live at {user_id}/<file>, so a
-- user can only write inside their own folder, but anyone can read (avatars are
-- public). The username + avatar URL themselves live in auth user_metadata, not
-- a table.
insert into storage.buckets (id, name, public)
values ('avatars', 'avatars', true)
on conflict (id) do nothing;

-- Public read (these are public profile pictures).
create policy "avatars public read"
  on storage.objects for select
  using (bucket_id = 'avatars');

-- A signed-in user may only manage objects inside their own {uid}/ folder.
create policy "avatars owner insert"
  on storage.objects for insert to authenticated
  with check (
    bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "avatars owner update"
  on storage.objects for update to authenticated
  using (
    bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "avatars owner delete"
  on storage.objects for delete to authenticated
  using (
    bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text
  );
