-- Non-fatal conversion notes surfaced to the uploader, e.g. "audio was
-- transcribed with the free Google endpoint because none of your API keys
-- support speech-to-text". Distinct from conversion_error: the file indexed
-- fine, the user just deserves to know how.
alter table files add column if not exists conversion_note text;
