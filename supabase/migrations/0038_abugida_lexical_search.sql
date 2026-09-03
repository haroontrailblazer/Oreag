-- Finish what 0033 started: Lao, Khmer and Burmese.
--
-- 0033 made the lexical half of hybrid search work for scripts Postgres has no
-- segmenter for, by injecting a space around every character so a run of them
-- stops being ONE token. It covered Chinese, Japanese and Thai. Three more
-- scripts written without word spaces were missed, and for them the lexical
-- half has been dead exactly as it was for CJK before 0033:
--
--   Lao      U+0E80-U+0EFF   adjacent to Thai and skipped by one code point
--   Myanmar  U+1000-U+109F   Burmese and the minority languages sharing it
--   Khmer    U+1780-U+17FF
--
-- MEASURED, not assumed. Against this database, a Khmer phrase of five words
-- produced ONE token and a search for a word inside it returned nothing. With
-- these ranges added it produces eleven and the word is found. Same for Lao
-- (1 -> 13) and Burmese (1 -> 9).
--
-- WHY TIBETAN IS NOT HERE
--
-- It looks like it belongs - Tibetan has no word spaces either - and the same
-- measurement says otherwise. Tibetan delimits SYLLABLES with a tsheg
-- (U+0F0B), which the default parser already treats as punctuation, so a
-- Tibetan phrase tokenises into four syllable tokens today, finds the word
-- being searched for, and correctly REJECTS the same letters in a different
-- order. Adding it would replace four meaningful tokens with nine letters and
-- start matching scrambled text. It is not a gap; it already works.
--
-- WHAT THIS COSTS IN PRECISION
--
-- Per-character tokens are letters here, not morphemes as they are for Han, so
-- a query matches any document containing the same letters in any order. That
-- is a real loss - and it is the SAME loss 0033 already accepted for Chinese,
-- verified in the same measurement: a Chinese query matches scrambled Chinese
-- today. Recall from nothing to something, at a precision the product already
-- ships elsewhere, and the semantic half of hybrid search is unaffected either
-- way.
--
-- The expression must stay byte-identical to _UNSPACED_SPLIT in
-- backend/app/services/retrieval.py. backend/tests/test_text_search_config.py
-- parses both files and fails the build on drift, because a mismatch means the
-- indexed form and the queried form never meet - and that failure looks
-- exactly like "this corpus had no keyword matches".
--
-- Written with \u escapes rather than literal characters so the file stays
-- ASCII and survives any editor, and with NO percent sign anywhere - comments
-- included - because psycopg scans the whole statement for placeholders and
-- scripts/apply_migration.py would otherwise refuse the file.
--
-- SET EXPRESSION rewrites the table: every chunk's tsvector is recomputed and
-- the GIN index rebuilt, under ACCESS EXCLUSIVE. That is the same cost 0033
-- paid, and the reason this is one migration rather than three.

do $migration$
declare
  -- ONE definition, used by both branches below. Dollar-quoted so the
  -- backslashes reach the SQL parser untouched.
  expr constant text := $expr$
    to_tsvector(
      'english',
      regexp_replace(
        content,
        E'([\u4E00-\u9FFF\u3400-\u4DBF\u3040-\u30FF\u0E00-\u0E7F\u0E80-\u0EFF\u1000-\u109F\u1780-\u17FF])',
        ' \1 ',
        'g'
      )
    )
  $expr$;
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'chunks'
      and column_name = 'content_tsv'
  ) then
    -- In place - no drop, so the index is preserved and rebuilt rather than
    -- lost. Concatenation rather than format(), for the percent-sign reason
    -- in the header.
    execute 'alter table public.chunks '
         || 'alter column content_tsv set expression as (' || expr || ')';
  else
    -- A database that somehow never ran 0012. Same end state.
    execute 'alter table public.chunks '
         || 'add column content_tsv tsvector generated always as ('
         || expr || ') stored';
  end if;
end
$migration$;

-- Present already on any database that ran 0012; created here for the branch
-- above that had to add the column.
create index if not exists chunks_content_tsv_idx
  on public.chunks using gin (content_tsv);
