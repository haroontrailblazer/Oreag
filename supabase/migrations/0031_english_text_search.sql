-- Stem the lexical half of hybrid search.
--
-- WHAT WAS WRONG WITH 'simple'
--
-- 0012 chose the 'simple' config deliberately, reasoning that exact-token
-- matching is the lexical half's job while the semantic half handles
-- paraphrase. That is a fair division of labour, but 'simple' does not do
-- exact-token matching of WORDS - it does exact matching of CHARACTER STRINGS.
--
-- So "investing" did not match "invest", "savings" did not match "saving", and
-- "companies" did not match "company". Those are not paraphrases the embedding
-- should have to cover; they are the same word wearing a different suffix, and
-- the half of the search that exists to catch literal terms was missing them.
-- In practice that made the lexical half close to dead weight on prose, and
-- every hybrid result was carried by the vector side alone.
--
-- 'english' stems, so all three now match. Identifiers, error codes and names -
-- the things 'simple' was chosen to protect - do not stem, so they behave
-- exactly as before.
--
-- THE TRADE-OFF, STATED
--
-- 'english' also applies English stop words and English stemming rules to
-- non-English text. Oreag transcribes and answers in other languages (Sarvam
-- covers Indic ones), and for that content this is roughly neutral rather than
-- helpful - it mostly lowercases. The semantic half is language-agnostic and
-- carries those cases already, which is why one config is worth more than the
-- complexity of per-project text-search configuration.
--
-- BOTH SIDES MOVE TOGETHER OR NEITHER WORKS
--
-- content_tsv is what gets INDEXED and websearch_to_tsquery is what gets
-- SEARCHED. Stemmed index + unstemmed query means the terms never meet and
-- lexical search silently returns nothing - no error, just an empty half. The
-- query side changes in services/retrieval.py in the same commit as this file.
--
-- A generated column cannot be redefined in place: it is dropped and re-added,
-- which recomputes it for every row. Nothing is lost - it is derived from
-- `content` - but it takes an ACCESS EXCLUSIVE lock for the rewrite, so run it
-- when ingestion is quiet on a large corpus.

drop index if exists chunks_content_tsv_idx;

alter table public.chunks drop column if exists content_tsv;

alter table public.chunks
  add column content_tsv tsvector
  generated always as (to_tsvector('english', content)) stored;

create index if not exists chunks_content_tsv_idx
  on public.chunks using gin (content_tsv);
