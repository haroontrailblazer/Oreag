-- Stem the lexical half in the language the documents are actually written in.
--
-- Since 0031 the full-text column has been built with the 'english'
-- configuration for every project on the server, because a generated column
-- takes a CONSTANT configuration and there was nowhere to put a per-project
-- one. For an English corpus that is right. For every other corpus it means
-- the words are lower-cased, split, and then run through an English stemmer
-- that knows none of their morphology - so a query in any inflected language
-- only matches when the user happens to type the exact surface form the
-- document used.
--
-- MEASURED against this database, not assumed. One sentence per language and
-- one query word that appears in it in a DIFFERENT grammatical form - the
-- ordinary case, since a Russian noun has twelve forms and a Turkish one has
-- dozens. Under 'english' the search FAILS; under the language's own
-- configuration it succeeds:
--
--   Russian, German, Spanish, Portuguese, Italian, Dutch, Hindi, Nepali,
--   Arabic, Indonesian - and Greek, Hungarian, Serbian, Swedish, Catalan,
--   Basque, Yiddish
--
-- Seventeen languages whose keyword search does not work today and does
-- afterwards. Russian is the clearest illustration:
--
--   english   godovye kompaniya obyazana otchyoty podavat   (8 lexemes, none stemmed)
--   russian   godov kompan obyaza otchet podava             (7 lexemes, stemmed, stopword dropped)
--
-- A query for the nominative "otchet" finds the plural "otchyoty" only in the
-- second. The stopword list comes along too, which is why one token fewer.
--
-- HOW. `to_tsvector(regconfig, text)` is IMMUTABLE - unlike the one-argument
-- form, which reads a GUC and is merely STABLE - so a generated column may
-- take its configuration from another COLUMN of the same row. Verified on
-- this server (17.6) before this migration was written. So:
--
--   chunks.ts_config    regconfig, defaulting to 'english'
--   chunks.content_tsv  generated from ts_config instead of a literal
--
-- WHY THIS IS SAFE TO DEPLOY. Every existing row gets 'english', which is the
-- configuration it already had, so content_tsv comes out byte-identical and
-- no query changes behaviour until a project opts in.
--
-- WHY A COLUMN RATHER THAN A SETTING READ AT QUERY TIME. Changing a project's
-- language then costs one UPDATE - the generated column recomputes itself on
-- write, verified - instead of deleting and re-embedding the corpus on the
-- user's own paid API key. Nothing is re-chunked and nothing is re-embedded.
--
-- WHY THE QUERY SIDE STILL PASSES A CONSTANT. The GIN index is on
-- content_tsv, and an index scan needs the tsquery on the other side of `@@`
-- to be constant for the whole scan. A project has exactly one configuration,
-- so retrieval passes that one value as a bind parameter rather than reading
-- the column per row; checked with EXPLAIN that the bind-parameter form still
-- produces a Bitmap Index Scan on chunks_content_tsv_idx.
--
-- The index side and the query side MUST agree - a stemmed index against an
-- unstemmed query means the terms never meet, and that failure looks exactly
-- like "this corpus had no keyword matches". backend/tests/
-- test_text_search_config.py parses this file and
-- backend/app/services/retrieval.py and fails the build on drift.
--
-- Written with \u escapes rather than literal characters so the executable
-- SQL stays ASCII, and with NO percent sign anywhere - comments included -
-- because psycopg scans the whole statement for placeholders and
-- scripts/apply_migration.py would otherwise refuse the file.
--
-- SET EXPRESSION rewrites the table and rebuilds the GIN index under ACCESS
-- EXCLUSIVE, the same cost 0033 and 0038 each paid. Run it when ingestion is
-- quiet.

set local lock_timeout = '5s';

-- Catalog-only on PostgreSQL 11+: the default is a constant, so no rewrite
-- happens here. The rewrite below is the only one.
alter table public.chunks
  add column if not exists ts_config regconfig not null default 'english';

comment on column public.chunks.ts_config is
  'Postgres text-search configuration this row''s content_tsv was built with. Set from the owning project''s document language at ingest; changing it rewrites content_tsv on UPDATE, with no re-embedding.';

-- NULL means English, which is what every project has had until now.
alter table public.projects
  add column if not exists document_language text;

comment on column public.projects.document_language is
  'Language the project''s DOCUMENTS are written in, which selects the stemmer for keyword search. Distinct from answer_language, which is the language answers are written in. NULL means English.';

do $migration$
declare
  -- ONE definition, used by both branches. Dollar-quoted so the backslashes
  -- reach the SQL parser untouched. The only change from 0038 is the first
  -- argument: a column instead of a quoted literal.
  expr constant text := $expr$
    to_tsvector(
      ts_config,
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
