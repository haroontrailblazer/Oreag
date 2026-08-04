-- Let a re-index reuse the markdown it already produced.
--
-- THE WASTE
--
-- Re-embedding (a model change, or growing a Matryoshka dimension back up)
-- deletes the chunks and re-runs the whole ingest. That step downloads the
-- ORIGINAL file and converts it again - even though the converted markdown is
-- already sitting in storage at files.markdown_storage_path from the first
-- pass.
--
-- For text and PDFs that is wasted CPU. For images and audio it is wasted
-- MONEY: image captioning re-runs against the project's vision model and audio
-- re-runs speech-to-text, both on the user's own BYOK keys. So growing a
-- dimension on a project full of scans or recordings paid twice - once for
-- embeddings, which is unavoidable, and once for conversion, which is not.
--
-- WHY A VERSION AND NOT JUST "REUSE IF PRESENT"
--
-- Conversion output is deterministic for an unchanged file, but only for a
-- FIXED conversion pipeline. When that pipeline is fixed or improved, every
-- blob written before the change is stale. A live example: PyMuPDF emits 0x00
-- for glyphs it cannot map, and markdown written before that was stripped
-- still carries those bytes. Reusing it blindly would resurrect a bug that has
-- already been fixed, and do it silently.
--
-- So the row records WHICH pipeline produced its markdown. Reuse happens only
-- when that matches services/conversion.py CONVERSION_VERSION; anything older
-- converts once more and is re-stamped. Bump the constant whenever a change
-- alters conversion OUTPUT, and the fleet self-heals one file at a time.
--
-- SAFETY: additive and nullable. Every existing row reads as NULL, which never
-- matches the current version, so all of them re-convert exactly as they do
-- today - the feature only starts saving work on the second pass. An unapplied
-- 0023 means the column is missing and the reuse path is skipped entirely.

alter table public.files
  add column if not exists conversion_version integer;

comment on column public.files.conversion_version is
  'Which conversion pipeline produced markdown_storage_path. Re-index reuses that markdown only when this equals the running CONVERSION_VERSION; NULL or older means convert again.';
