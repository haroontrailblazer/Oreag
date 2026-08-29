-- Make the lexical half of hybrid search work for scripts without spaces.
--
-- WHAT WAS BROKEN
--
-- Postgres has no word segmenter for Chinese, Japanese or Thai, and none of
-- the 29 text-search configurations on this server is for any of them. The
-- default parser splits on whitespace and punctuation, so an entire Han run
-- became ONE token:
--
--   to_tsvector('english', '阿育吠陀药物的专利申请流程')
--     -> '阿育吠陀药物的专利申请流程':1        (1 lexeme)
--
-- No substring query can ever match that. Searching 专利 - a term the document
-- literally contains - returned nothing. Measured across 20 languages, the
-- lexical half was dead for exactly three: Chinese, Japanese and Thai. Every
-- other script tested, including all 22 scheduled Indian languages and Korean,
-- delimits words with spaces and already worked.
--
-- This was NOT caused by 0031's move to 'english'. 'simple' produces the
-- identical single lexeme and the identical misses; the config was never the
-- problem, the absence of segmentation was.
--
-- THE FIX
--
-- Segmentation is not strictly required. If every character of an unspaced
-- script becomes its own token on BOTH the index side and the query side, a
-- multi-character term matches as a conjunction of its characters. One
-- regexp_replace does it, and it is immutable, so a generated column accepts
-- it and no extension is needed - zhparser and pg_bigm are not available on
-- managed Postgres anyway.
--
--   -> '专':8 '利':9 '吠':3 '流':12 '物':6 '申':10 ...   (13 lexemes)
--
-- WHY THIS IS SAFE FOR EVERY OTHER LANGUAGE
--
-- The character class contains ONLY unspaced scripts. Verified against the
-- live database: English, Hindi and Korean tsvectors come out byte-identical
-- before and after, so no existing query changes behaviour and the identifier
-- case that hybrid search exists for (ERR_5521) is untouched. Hangul is
-- deliberately excluded - modern Korean is space-delimited and already worked.
--
-- THE TRADE-OFF, STATED
--
-- Per-character tokens mean AND-matching, not substring matching: a query for
-- 专利申请 becomes 专 & 利 & 申 & 请, which also hits a document containing
-- those four characters scattered rather than adjacent. Measured, a decoy like
-- that ranks 0.02 against 0.10 for a real match - a 5x separation that
-- ts_rank_cd and then RRF order correctly, and the semantic half is unaffected
-- either way. Recall is the lexical half's job in a hybrid system; precision
-- comes from the fusion.
--
-- phraseto_tsquery would give exact adjacency (verified: it rejects that decoy
-- outright) but it forces EVERY term adjacent, which would break ordinary
-- multi-word English questions. Per-run phrase construction is the upgrade
-- path if CJK precision ever matters more than English recall.
--
-- BOTH SIDES MUST MOVE TOGETHER. The identical expression is applied to
-- :question in retrieval.py. If one side is transformed and the other is not,
-- lexical search silently returns nothing - no error, exactly the failure 0031
-- warned about. backend/tests/test_text_search_config.py parses both files and
-- fails the build on drift.
--
-- Written with \u escapes in an E'' string rather than literal CJK characters,
-- so this file stays pure ASCII: an encoding mishap in an editor, a terminal
-- or a diff tool cannot silently corrupt the character class into one that
-- matches nothing - which would fail the way the original bug did, quietly.
--
--   一-鿿  CJK unified ideographs
--   㐀-䶿  CJK extension A
--   ぀-ヿ  Hiragana + Katakana
--   ฀-๿  Thai
--
-- Hangul is deliberately absent; see above.

drop index if exists chunks_content_tsv_idx;

alter table public.chunks drop column if exists content_tsv;

alter table public.chunks
  add column content_tsv tsvector
  generated always as (
    to_tsvector(
      'english',
      regexp_replace(
        content,
        E'([\u4E00-\u9FFF\u3400-\u4DBF\u3040-\u30FF\u0E00-\u0E7F])',
        ' \1 ',
        'g'
      )
    )
  ) stored;

create index if not exists chunks_content_tsv_idx
  on public.chunks using gin (content_tsv);

comment on column public.chunks.content_tsv is
  'Full-text index. Unspaced scripts (CJK, Thai) are split per character so '
  'they are searchable at all; every other script is passed through unchanged. '
  'The SAME regexp must be applied to the query in retrieval.py.';
