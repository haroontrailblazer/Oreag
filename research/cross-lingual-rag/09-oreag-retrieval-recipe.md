# Oreag retrieval recipe: the cross-lingual repair, mapped onto Postgres + pgvector + tsvector

Audience: the engineer who owns `search()` and `supabase/migrations/`. Everything below is scoped to a hybrid of pgvector HNSW + a generated `content_tsv` column fused by rank-only RRF at `RRF_K = 60`. Every claim carries its source. Numbers the source record could not confirm are marked **UNVERIFIED**.

---

## 1. What the pipeline does now, and exactly where it loses

### The three components, stated precisely

| Arm | Mechanism | What it matches on | Cross-lingual behaviour |
|---|---|---|---|
| **Semantic** | pgvector, cosine distance, HNSW ANN, `openai/text-embedding-3-large`; exact scan below a chunk-count threshold | position in a learned vector space | Works, weakly. Carries 100% of the cross-lingual load. |
| **Lexical** | Postgres FTS: generated `content_tsv` built with ONE `regconfig` from `projects.document_language` (migration 0039); `ts_rank_cd` for ranking | post-analysis lexemes — stemmed surface forms | Contributes nothing across scripts. Structurally, not by misconfiguration. |
| **Fusion** | Reciprocal Rank Fusion, `k = 60`, rank-only; cosine similarity carried on rows for thresholds + UI "match %" | ranks only, scores discarded | Degenerate: with one empty list it reproduces the other list's order exactly. |

### Where the lexical arm loses, mechanically

Lexical retrieval scores over the **intersection** of query terms and document terms. A Devanagari query token and an English stemmed lexeme are different byte strings, so the intersection is empty and there is nothing to rank. This is published behaviour, not a bug: on cross-lingual MKQA, BM25 gets Recall@100 **39.9** against **75.1** for a dense multilingual model ([BGE-M3, arXiv 2402.03216](https://arxiv.org/abs/2402.03216)), and that paper attributes it to limited term overlap between different languages. The same paper shows a *learned* sparse arm does not rescue it either: its sparse head reaches only **45.3** R@100 on MKQA vs **75.1** dense, so `Dense+Sparse` (75.3) beats `Dense` (75.1) by **+0.2** cross-lingually ([BGE-M3](https://arxiv.org/abs/2402.03216)).

Contrast the *monolingual* case, which is where "BM25 is a strong baseline" comes from: tuned BM25 averages MRR@100 **0.333** on Mr. TyDi vs mDPR's **0.167**, beating dense retrieval in 10 of 11 languages ([Mr. TyDi, arXiv 2108.08787](https://arxiv.org/abs/2108.08787)), and scores nDCG@10 **0.458** on MIRACL Hindi — with a *Devanagari* query ([MIRACL, arXiv 2210.09984](https://arxiv.org/abs/2210.09984)). Your 28/28 zero-row result is the correct output of the right tool applied to the wrong query.

### Three things about your lexical arm that are worse than you probably assume

1. **`ts_rank_cd` is not BM25 and has no IDF.** The docs state it outright: "It is important to note that the ranking functions do not use any global information" ([textsearch-controls](https://www.postgresql.org/docs/current/textsearch-controls.html)). A match on a common term ranks comparably to a match on a rare discriminative one. Do not attribute BM25's published strength to this arm.
2. **The default length normalization is 0**, i.e. document length is ignored ([textsearch-controls](https://www.postgresql.org/docs/current/textsearch-controls.html)). The flags that actually reorder by length are `1` (divide by 1+log(length)) and `2` (divide by length). Flag `32` divides the rank by itself+1 — a strictly monotonic transform, so under **rank-only RRF it changes nothing end-to-end**.
3. **A Devanagari chunk in an `english` config is *indexed*, not lost.** The default parser's letter test follows the database `lc_ctype`, so non-ASCII letters tokenize as token type `word` ([textsearch-parsers](https://www.postgresql.org/docs/current/textsearch-parsers.html)), and the English Snowball stemmer finds no ASCII vowel region so returns the token unchanged. What you lose is *Hindi stemming*, not *reachability* — except under a `C` ctype. Verify in ten seconds: `SHOW lc_ctype;` and `SELECT to_tsvector('english','भारत की राजधानी');`.

**Therefore: your 28/28 measurement is a vocabulary-mismatch failure, not a stemmer failure.** No `regconfig` change of any kind fixes it. Only putting corpus-language text in front of the query (translation), or query-language text into the index (document translation / expansion), or a shared multilingual vector space, can.

### Two failures you have not measured yet

- **Hinglish is invisible to your gate.** A Unicode script gate asks "is this script absent from the corpus?". Romanized Hindi is Latin script, so the gate never fires and the query falls through to an English stemmer and stopword list. That is arguably *worse* than the clean zero-rows case, because the lexical arm returns a few junk rows instead of none. Code-switched queries cost multilingual retrievers up to **27%** on the CS-MTEB benchmark ([arXiv 2604.17632](https://arxiv.org/abs/2604.17632)) — and that benchmark covers English-Chinese and English-Japanese only; a full-text search of it for "Hindi"/"Hinglish" returns zero hits, so **no published number exists for romanized-Hindi retrieval**. You would be first.
- **You may not have a working HNSW index at all.** `text-embedding-3-large` emits **3072** dimensions ([OpenAI embeddings guide](https://developers.openai.com/api/docs/guides/embeddings)). pgvector's HNSW caps the `vector` type at **2,000 dimensions** and `halfvec` at **4,000** ([pgvector README](https://github.com/pgvector/pgvector)). A plain `vector(3072)` column therefore *cannot* take an HNSW index. Either you are on `halfvec`, you are passing `dimensions` to reduce, or you are silently exact-scanning. Check this before anything else in section 5.

---

## 2. Postgres schema options for a mixed-language lexical arm

First, the constraint as PostgreSQL actually states it. A generated column's expression "can only use immutable functions and cannot use subqueries or reference anything other than the current row in any way" ([ddl-generated-columns](https://www.postgresql.org/docs/current/ddl-generated-columns.html)). Only the **two-argument** `to_tsvector(regconfig, text)` qualifies: "Only text search functions that specify a configuration name can be used in expression indexes... because the index contents must be unaffected by `default_text_search_config`" ([textsearch-tables](https://www.postgresql.org/docs/current/textsearch-tables.html)).

The constraint is that the config must be **constant**, not that there be **one**. That distinction opens options B and C below at zero conceptual cost.

### Availability on your platform (this gates half the list)

The Supabase Postgres build manifest at [`supabase/postgres` `nix/ext`](https://github.com/supabase/postgres/tree/develop/nix/ext) contains `pgvector`, `pgroonga`, `rum`, `pg_cron`, `pgmq`, `postgis`, `timescaledb`, `wrappers` and others. It contains **no `pg_search`/ParadeDB, no `vchord`, no `pg_tokenizer`, no `pg_bigm`**. PGroonga additionally has a first-class Supabase docs page ([Supabase PGroonga](https://supabase.com/docs/guides/database/extensions/pgroonga)); ParadeDB Community is also AGPL-3.0 ([paradedb/paradedb](https://github.com/paradedb/paradedb)), a separate question for a commercial product.

### The options

| # | Option | Migration? | Fixes mixed corpora? | Fixes Hindi→English? |
|---|---|---|---|---|
| A | Status quo: one constant regconfig | — | No | No |
| B | Concatenated multi-config generated column | Column rewrite | Yes | No |
| C | N generated columns, one regconfig each | Additive columns + indexes | Yes | No |
| D | Trigger + per-row `regconfig` column | Drop generated col, backfill | Yes | No |
| E | Expression GIN index on a `regconfig` column | Additive index + column | Yes | No |
| F | Per-row regconfig *inside* a generated column | Column rewrite | Yes (if legal) | No |
| G | Per-language partial indexes | Additive | Partly | No |
| H | `PARTITION BY LIST (document_language)` | Table rebuild | Yes | No — actively harmful |
| I | PGroonga (n-gram, no regconfig) | Additive extension + index | Yes | No |
| J | pg_search / vchord_bm25 (real BM25) | **Not installable on Supabase** | Yes | No |
| K | pg_trgm third arm | Additive index | Within-script only | No |
| L | Pivot-language second tsvector (doc translation) | Additive col + index + ingest | Yes | **Yes — if the corpus is non-English** |
| M | Dense-only when scripts mismatch | Code only | N/A | It is the honest fallback |

---

#### A. Status quo — constant regconfig

```sql
content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
```

**Cost:** already paid; recomputed on every insert and non-HOT update, one GIN index.
**Failure mode:** silent. Feeding Devanagari through `'english'` does not error; it indexes with no Hindi stemming and no Hindi stopword removal — PostgreSQL 17 ships stemmers for ~30 languages but **stopword files for only 15**, and `hindi.stop` and `tamil.stop` are not among them ([snowball Makefile](https://raw.githubusercontent.com/postgres/postgres/master/src/backend/snowball/Makefile)). Combined with `ts_rank_cd`'s absent IDF, high-frequency Hindi function words will dominate cover-density ranking.
**Keep for:** every single-language project. This is the right default.

#### B. Concatenated multi-config generated column — cheapest, but it hurts your ranker

```sql
ALTER TABLE chunks ALTER COLUMN content_tsv SET EXPRESSION AS (
  to_tsvector('english', coalesce(content,'')) ||
  to_tsvector('simple',  coalesce(content,''))
) STORED;   -- PG17+; earlier: DROP + ADD COLUMN
```

Legal because `tsvector || tsvector` is defined and each regconfig is a parse-time literal ([functions-textsearch](https://www.postgresql.org/docs/current/functions-textsearch.html)).
**Cost:** index size grows roughly linearly in the number of configs; `SET EXPRESSION AS` rewrites existing data under `ACCESS EXCLUSIVE`, so it is a full table rewrite plus GIN rebuild.
**Failure mode, specific to your stack:** the `||` docs say "the second input's positions are adjusted accordingly" — positions are *offset* past the first vector's. `ts_rank_cd` is cover-density ranking that requires positional information and scores proximity ([textsearch-controls](https://www.postgresql.org/docs/current/textsearch-controls.html)). After concatenation, two words adjacent in the source sit hundreds of positions apart if they matched in different sub-vectors, and any cover spanning sub-vectors is meaningless. **Concatenation degrades the ranker you actually use.** Prefer C and fuse the columns as separate RRF arms.
Caps to respect: 16,383 positions per tsvector, 256 positions per lexeme, 1 MB total ([textsearch-limitations](https://www.postgresql.org/docs/current/textsearch-limitations.html)).

#### C. Multiple generated columns, one regconfig each

```sql
ALTER TABLE chunks
  ADD COLUMN tsv_simple tsvector GENERATED ALWAYS AS
    (to_tsvector('simple', coalesce(content,''))) STORED;
CREATE INDEX ON chunks USING gin (tsv_simple);
```

**Cost:** N tsvectors + N GIN indexes per row; write amplification scales with N. Practical ceiling ~3 columns before storage dominates.
**Failure mode:** unbounded column growth as languages are added; the query must decide which column(s) to hit.
**Why it beats B here:** you get a *separate score per analysis*, so each column feeds the RRF you already own as an extra ranked list, and you can log which column matched. This is Elasticsearch's published multilingual pattern — identify language at ingest, route into per-language analyzed fields, query with `multi_match`/`best_fields` (max-score fusion) ([Elastic multilingual search](https://www.elastic.co/blog/multilingual-search-using-language-identification-in-elasticsearch)) — reimplemented in the fusion layer you already have.
`pg_catalog.hindi` exists and is UTF-8-only ([snowball Makefile](https://raw.githubusercontent.com/postgres/postgres/master/src/backend/snowball/Makefile)); it also routes ASCII tokens to `english_stem` (`%ascii_languages = ('hindi' => 'english', ...)` in [snowball_create.pl](https://raw.githubusercontent.com/postgres/postgres/master/src/backend/snowball/snowball_create.pl)), so **one `hindi` config stems Devanagari with Hindi rules and Latin tokens with English rules** — the closest thing to a native Hinglish config Postgres has.

#### D. Trigger with a per-row `regconfig` column — the documented per-row route

```sql
ALTER TABLE chunks DROP COLUMN content_tsv;
ALTER TABLE chunks ADD COLUMN content_tsv tsvector,
                   ADD COLUMN tsv_config regconfig NOT NULL DEFAULT 'pg_catalog.simple';
CREATE TRIGGER chunks_tsv BEFORE INSERT OR UPDATE ON chunks
  FOR EACH ROW EXECUTE FUNCTION
  tsvector_update_trigger_column(content_tsv, tsv_config, content);
```

The docs are explicit: "the second trigger argument is the name of another table column, which must be of type `regconfig`. This allows a per-row selection of configuration to be made" ([textsearch-features](https://www.postgresql.org/docs/current/textsearch-features.html)).
**Cost:** a row-level BEFORE trigger instead of a generated column — measurably slower bulk ingest. Plus a full backfill and GIN rebuild. Plus a language-detection step at ingest that Postgres does not provide.
**Failure modes:** (a) **a trigger cannot write a GENERATED column**, so migration 0039's column must be dropped, not amended — this is not additive; (b) NULL values are skipped; (c) the built-in triggers "treat all the input columns alike", so `setweight` needs a hand-written PL/pgSQL trigger; (d) a bad language tag writes a permanently wrong tsvector with no error; (e) the page itself calls triggers "obsoleted by the use of stored generated columns" — that note assumes a constant config and does not apply here, but you are choosing a deprecated mechanism deliberately ([textsearch-features](https://www.postgresql.org/docs/current/textsearch-features.html)).

#### E. Expression GIN index over a `regconfig` column — the additive per-row route

```sql
ALTER TABLE chunks ADD COLUMN tsv_config regconfig NOT NULL DEFAULT 'pg_catalog.simple';
CREATE INDEX chunks_fts ON chunks USING GIN (to_tsvector(tsv_config, content));
-- the query MUST match the expression:
--   WHERE to_tsvector(tsv_config, content) @@ websearch_to_tsquery('english', $1)
```

Documented verbatim: "It is possible to set up more complex expression indexes wherein the configuration name is specified by another column... This allows mixed configurations in the same index while recording which configuration was used for each index entry. This would be useful, for example, if the document collection contained documents in different languages. Again, queries that are meant to use the index must be phrased to match" ([textsearch-tables](https://www.postgresql.org/docs/current/textsearch-tables.html)).
**Cost:** no stored tsvector, so the expression is recomputed at index-maintenance time on every write, and again in the `SELECT` list if you want `ts_rank_cd` ([indexes-expressional](https://www.postgresql.org/docs/current/indexes-expressional.html)).
**Failure mode:** losing the stored column means every ranking call recomputes `to_tsvector` over full chunk text. For a ranked hybrid that is the wrong trade — prefer D or F.

#### F. Per-row regconfig *inside* a generated column

```sql
-- lang MUST be typed regconfig, never text::regconfig
tsv tsvector GENERATED ALWAYS AS (to_tsvector(lang, content)) STORED
```

This *should* be legal: `to_tsvector(regconfig, text)` carries no `provolatile` override in [`pg_proc.dat`](https://github.com/postgres/postgres/blob/REL_17_STABLE/src/include/catalog/pg_proc.dat) and `provolatile` defaults to immutable in [`pg_proc.h`](https://github.com/postgres/postgres/blob/REL_17_STABLE/src/include/catalog/pg_proc.h), while the one-argument form explicitly carries `provolatile => 's'`; generated columns reject only mutable expressions, via `contain_mutable_functions_after_planning()` in [`heap.c`](https://github.com/postgres/postgres/blob/REL_17_STABLE/src/backend/catalog/heap.c). **UNVERIFIED — never executed against a live server in the source record.** Test it in 30 seconds:

```sql
CREATE TABLE t(c text, lang regconfig,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector(lang, c)) STORED);
```

**The trap:** `to_tsvector(lang_text::regconfig, c)` is rejected, because `regconfigin` is `provolatile => 's'` (name→OID resolution depends on `search_path`). That is the most likely source of a confusing "generation expression is not immutable" error. If the test fails, fall back to D.

#### G. Per-language partial indexes

```sql
CREATE INDEX chunks_fts_hi ON chunks USING gin (to_tsvector('hindi', content))
  WHERE doc_language = 'hi';
```

**Failure mode — the docs disqualify this pattern themselves:** "a partial index can be used in a query only if the system can recognize that the WHERE condition of the query mathematically implies the predicate of the index"; "Matching takes place at query planning time, not at run time. As a result, parameterized query clauses do not work with a partial index"; and "You might be tempted to create a large set of non-overlapping partial indexes... **This is a bad idea!**" ([indexes-partial](https://www.postgresql.org/docs/current/indexes-partial.html)). Your app binds `$1`. Skip.

#### H. `PARTITION BY LIST (document_language)`

Partitions "may have their own indexes, constraints and default values, distinct from those of other partitions" ([ddl-partitioning](https://www.postgresql.org/docs/current/ddl-partitioning.html)), so each partition can carry its own regconfig — genuine per-document stemming, engine-enforced.
**Cost:** "the constraint's columns must include all of the partition key columns" ([ddl-partitioning](https://www.postgresql.org/docs/current/ddl-partitioning.html)), so `document_language` invades every PK/unique constraint and breaks chunk identity. No global indexes. Vector queries fan out across N HNSW graphs and merge, each with its own `ef_search`.
**Failure mode:** partitioning by language and filtering to the query's language *guarantees* the Hindi question never sees the English chunks — the opposite of what cross-lingual retrieval wants. If you ever partition, partition by `project_id`, which is what pgvector's own multitenancy example does ([pgvector README](https://github.com/pgvector/pgvector)), and handle language with D.

#### I. PGroonga — the one multilingual FTS extension you can actually install

```sql
create extension pgroonga with schema extensions;
CREATE INDEX chunks_pgroonga ON chunks USING pgroonga (content);
-- WHERE content &@~ 'query terms' ; rank via pgroonga_score(tableoid, ctid)
```

Supabase's own page: native Postgres FTS "is limited to alphabet and digit based languages" while PGroonga "offers a wider range of character support making it viable for a superset of languages supported by Postgres including Japanese, Chinese, etc." ([Supabase PGroonga](https://supabase.com/docs/guides/database/extensions/pgroonga)). It takes **no regconfig at all**, which dissolves the one-project-one-stemmer constraint outright and would let you delete `projects.document_language`.
**Cost and failure modes, be strict:** (a) its default `TokenBigram` "uses bigram tokenization for non ASCII characters and **white space based tokenization for ASCII characters**" ([PGroonga CREATE INDEX reference](https://pgroonga.github.io/reference/create-index-using-pgroonga.html)) — so out of the box English gets whole-word matching with **no stemming**, which is *less* forgiving on Latin morphology than your current tsvector; you must set `tokenizer='TokenBigramSplitSymbolAlphaDigit'` to bigram Latin text. (b) Ranking is TF-only: "Score is 'how many keywords are included' (TF, Term Frequency) for now" and "Groonga supports customizing how to score. But PGroonga doesn't support yet it for now" ([PGroonga](https://pgroonga.github.io/)) — no IDF, no BM25. (c) Bigram indexes are materially larger than lexeme GIN. (d) It still returns zero for a Devanagari query against English prose. **PGroonga solves tokenization, not translation.**

#### J. Real BM25 in Postgres — pg_search / vchord_bm25

`pg_search` gives Tantivy BM25 scoring, tokenizers including `icu`, `lindera`, `jieba`, `ngrams`, and **multiple tokenizers per field** via casts and aliases ([ParadeDB tokenizers](https://www.paradedb.com/docs/documentation/tokenizers/multiple-per-field.md)) — technically the richest option here, though its stemmer list omits Hindi ([same page](https://www.paradedb.com/docs/documentation/tokenizers/multiple-per-field.md)). `vchord_bm25` + `pg_tokenizer.rs` gives Block-WeakAnd BM25 with a Snowball stemmer set that **includes Hindi** ([pg_tokenizer text-analyzer docs](https://github.com/tensorchord/pg_tokenizer.rs/blob/main/docs/05-text-analyzer.md)).
**Blocker:** neither appears in [Supabase's build manifest](https://github.com/supabase/postgres/tree/develop/nix/ext), and both are Rust extensions needing `shared_preload_libraries`. Adopting either is a platform migration, not a retrieval decision.

#### K. pg_trgm as a third arm

```sql
CREATE EXTENSION pg_trgm;
CREATE INDEX ON chunks USING gin (title gin_trgm_ops);  -- narrow column, never full body
```

Trigram extraction and the `%` / `<->` / `word_similarity` operators are documented, with `pg_trgm.similarity_threshold` defaulting to 0.3 ([pgtrgm](https://www.postgresql.org/docs/current/pgtrgm.html)). It is mechanically script-agnostic — `trgm_op.c` walks characters with `pg_mblen_unbounded()` and hashes multibyte trigrams to three bytes ([contrib/pg_trgm/trgm_op.c](https://github.com/postgres/postgres/blob/master/contrib/pg_trgm/trgm_op.c)) — but the docs say nothing about multibyte behaviour, so test rather than assume.
**Cost:** GIN over raw text is much larger and slower to build than a tsvector GIN, and "a pattern with no extractable trigrams will degenerate to a full-index scan" ([pgtrgm](https://www.postgresql.org/docs/current/pgtrgm.html)).
**Failure mode:** Devanagari and Latin share no trigrams, so it does **nothing** for the motivating case. Its real use is Hinglish spelling variance and transliterated proper nouns ("Bengaluru"/"Bangalore") within Latin script. Adding a noisy third list to a rank-only RRF is risky — see section 3.

#### L. Pivot-language second tsvector (document translation at ingest)

```sql
ALTER TABLE chunks ADD COLUMN content_en text;   -- written by the ingest pipeline
ALTER TABLE chunks ADD COLUMN content_en_tsv tsvector GENERATED ALWAYS AS
  (to_tsvector('english', coalesce(content_en,''))) STORED;
CREATE INDEX ON chunks USING gin (content_en_tsv);
```

Two columns, not one: an LLM call is neither immutable nor part of the current row, so it cannot live in a generation expression ([ddl-generated-columns](https://www.postgresql.org/docs/current/ddl-generated-columns.html)).
**This is the only document-side option that revives a dead lexical arm.** CLIRudit (English queries, 16,389 French documents) measures BM25 nDCG@10 **0.196** untranslated → **0.417** with query translation → **0.579** with document translation, while the dense arm barely moves (NV-Embed-v2 0.616 → 0.621) ([CLIRudit, arXiv 2504.16264](https://arxiv.org/abs/2504.16264)). NAVER's MIRACL-winning system translated all 16 corpora to English: BM25 39.3 → T-SPLADE 54.5 nDCG@10, hybrid 57.8 → 70.0 ([arXiv 2302.14723](https://arxiv.org/abs/2302.14723)).
**Cost:** one MT/LLM call per chunk at ingest, forever, re-paid on every version bump; a second text column and GIN index. NAVER's own caveats: NLLB-200 emitted junk they had to filter manually and only the first 128 tokens were translated ([arXiv 2302.14723](https://arxiv.org/abs/2302.14723)) — so pair it with a relevance filter, worth **up to 16%** effectiveness, **23%** faster queries and a **33%** smaller index on its own ([Doc2Query--, arXiv 2301.03266](https://arxiv.org/abs/2301.03266)).
**The direction trap:** your corpus is *already English*. For Hindi-question-over-English-corpus this is a **no-op** — the pivot is already satisfied. It becomes correct the moment a customer uploads a non-English corpus. For an English corpus the document-side analogue is **multilingual doc2query**: generate pseudo-queries per chunk in the expected query languages so Devanagari lexemes enter the index. Monolingual doc2query lifts BM25 MRR@10 from 0.184 to 0.277 on MS MARCO ([docTTTTTquery](https://cs.uwaterloo.ca/~jimmylin/publications/Nogueira_Lin_2019_docTTTTTquery-v2.pdf); original method [arXiv 1904.08375](https://arxiv.org/abs/1904.08375)) — but **no published cross-lingual doc2query evaluation exists** (UNVERIFIED as a cross-lingual technique; the monolingual backing is strong).

#### M. Dense-only when scripts mismatch

Not a schema at all: when the question's script is absent from the project's regconfig script, do not run the lexical arm. This is what your system already does *accidentally* (empty list → RRF reproduces dense order). Making it explicit costs one branch and buys a log line. Strategic support: ColBERT-X's MLIR follow-up found that indexing documents in their **native language** with a pretrained XLM-R retained "98% of that MAP score... with an 84% reduction in indexing time" versus neural document translation ([arXiv 2209.01335](https://arxiv.org/abs/2209.01335)).

### Language coverage — publish this in the product

PostgreSQL 17 ships UTF-8 Snowball stemmers for ~30 languages including **hindi, tamil, nepali, arabic, armenian, greek, serbian, turkish, indonesian** ([snowball Makefile](https://raw.githubusercontent.com/postgres/postgres/master/src/backend/snowball/Makefile)). It ships **no** stemmer for **Bengali, Telugu, Urdu, Marathi, Gujarati, Punjabi, Malayalam, Kannada, Chinese, Japanese, Korean, Thai** — Snowball itself has no algorithm for most of these ([Snowball algorithms](https://snowballstem.org/algorithms/)). For those the best core option is `simple`, which only lowercases and checks stopwords ([textsearch-dictionaries](https://www.postgresql.org/docs/current/textsearch-dictionaries.html)) — and for CJK/Thai that is doubly broken because the parser cannot find word boundaries either; PGroonga is the answer there ([Supabase PGroonga](https://supabase.com/docs/guides/database/extensions/pgroonga)). Even where a stemmer exists, morphology costs recall: BEIR-PL found "BM25 achieved significantly lower scores for Polish than for English, which can be attributed to high inflection and intricate morphological structure" ([arXiv 2305.19840](https://arxiv.org/abs/2305.19840)). Do not silently give a Bengali customer an English tsvector.

---

## 3. The fusion problem: what rank-only RRF at k=60 actually does

`RRF(d) = Σ_runs 1/(k + rank_run(d))`, k=60 chosen empirically, and the design point is that it "combines ranks without regard to the arbitrary scores returned by particular ranking methods" ([Cormack et al., SIGIR'09](http://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)). That indifference buys robustness to scale mismatch and costs you any way to say "this arm is garbage".

### Three regimes, and only one of them is what you measured

| Regime | What RRF does | Verdict |
|---|---|---|
| **Lexical arm returns 0 rows** (your 28/28) | Every fused score is `1/(60 + rank_dense)`, strictly decreasing in dense rank ⇒ **final order is identical to dense-only** | **Harmless.** You already degrade to the correct fallback, silently. |
| **Lexical arm returns 1–3 junk rows** (Hinglish, shared numerals, product codes) | Lexical rank 1 scores `1/61 = 0.016393`, exactly tying the dense arm's rank-1 hit and beating its rank-2 (`1/62 = 0.016129`) | **The real bug.** Unmeasured. |
| **Both arms non-empty but disjoint** | Equal-weight RRF is arithmetically identical to **round-robin interleaving**: a doc unique to A at rank rA beats a doc unique to B at rank rB iff rA < rB | Round-robin is the worst merge in the CLEF record |

### What the literature says about regimes two and three

- **Weakest link.** Across 11 real-world datasets: a "weakest link phenomenon, where a weak path can substantially degrade overall accuracy, highlighting the need for path-wise quality assessment before fusion" ([arXiv 2508.01405](https://arxiv.org/abs/2508.01405)).
- **A hybrid can lose to its better arm.** On Khmer web search, character-n-gram BM25 alone reached R@10 0.943 / nDCG@10 0.876 while BM25+dense hybrid got 0.929 / 0.871 ([arXiv 2608.21365](https://arxiv.org/abs/2608.21365)). Caveat: monolingual, silver labels with only partial human verification, 3,000 documents — an illustration, not a measurement of your case.
- **Round-robin's cost is measured.** In CLEF multilingual merging, round-robin reaches 64.0% / 65.0% of the theoretical optimum, normalized-score merging 69.3–73.6%, and 2-step RSV 85.8% / 86.5% ([Martínez-Santiago et al., IR Journal 2006](https://link.springer.com/content/pdf/10.1007/s10791-005-5722-4.pdf)). Braschler independently: plain interleaving 0.3249 average precision, collection-size-weighted interleaving 0.3369, an *optimally* merged run 0.4876 ([Braschler, IR Journal 2004](https://digitalcollection.zhaw.ch/bitstreams/17870429-2895-4ba1-aec5-e013307f1685/download)). Both settings merge *separate collections*, not two functions over one table — the interleaving arithmetic transfers, the absolute penalty does not.
- **Fusion theory says when not to fuse.** Vogt & Cottrell derive that linear combination is warranted when at least one system performs well and both return *similar sets of relevant documents*; empirically, of 91,500 system-pair/query triples, 88% improved on training but only 40% of those also improved on test, with the average test change **−14%** relative to the better component ([Vogt & Cottrell, IR Journal 1999](https://link.springer.com/content/pdf/10.1023/A:1009980820262.pdf)). Their result is for the linear-combination model specifically, and they say so; the transferable rule is that **overlap is the precondition for fusion**, and your non-English queries have none.

### Weight, normalise, or gate?

**Weight the arms — do this.** Weighted RRF is `w_lex/(k+r_lex) + w_sem/(k+r_sem)`. Supabase's own hybrid-search reference function already exposes `full_text_weight` and `semantic_weight` (defaults 1, `rrf_k` 50) ([Supabase hybrid search](https://supabase.com/docs/guides/ai/hybrid-search)). Published effect: MMMORRF found unweighted RRF gave "only a marginal improvement without statistical significance" at 0.562 nDCG@10 on MultiVENT 2.0, while weighted WRRF reached 0.586, "a statistically significant 4.2% improvement" — but on TVR weighting **lost** on R@1 (0.201 vs 0.232), and the authors call their weighting heuristic "ad hoc" ([MMMORRF, arXiv 2503.20698](https://arxiv.org/abs/2503.20698)). Validate per corpus.

**Normalise scores — test, gated.** Theoretical min-max convex combination (TM2C2) beats RRF on all nine of Bruch et al.'s datasets: MS MARCO nDCG@1000 0.425→0.454 (+6.8%), NQ 0.514→0.542, Quora 0.877→0.901, NFCorpus 0.312→0.327, HotpotQA 0.675→0.699, FEVER 0.721→0.744 ([Bruch et al., arXiv 2210.11934](https://arxiv.org/abs/2210.11934)). Their argument against RRF is precise: "because rrf is a function of ranks, it disregards the distribution of scores and, as such, discards useful information."
**But score fusion is *more* fragile cross-lingually, not less.** Empirical min-max forces every arm's best hit to exactly 1.0 regardless of quality — it manufactures confidence out of a dead arm. That is why Weaviate's `relativeScoreFusion` (their default since v1.24, ~6% recall over `rankedFusion` on FIQA) is the wrong normaliser here ([Weaviate hybrid search](https://docs.weaviate.io/weaviate/search/hybrid)). And **you cannot faithfully implement TM2C2 on your lexical arm anyway**: `ts_rank_cd` has a theoretical floor of 0 but no theoretical maximum, and the docs say ranks are not comparable across queries ([textsearch-controls](https://www.postgresql.org/docs/current/textsearch-controls.html)). Cosine needs care too — pgvector's `<=>` is a *distance* in [0,2], so similarity is `1 − distance` and the infimum is −1 ([pgvector README](https://github.com/pgvector/pgvector)). If you try it, gate it: normalised score fusion when the question script matches `document_language`, dense-only when it does not.

**Gate the lexical arm off — do this first.** The literature is lukewarm on *learned* adaptive weighting: a financial-retrieval study found fusion itself worth "roughly 28 percent" Hit@10 over either component, an oracle weight grid worth 21.8% headroom, and yet "none of the three lightweight adaptive routers... establishes a statistically reliable improvement over the fixed blend" ([arXiv 2608.00183](https://arxiv.org/abs/2608.00183)). But that argues against *learning a continuous weight from a noisy confidence estimate*. You have a **hard, deterministic signal**: script mismatch is a proof that the term intersection is empty, not a guess. The published counterpart is QPP-weighted fusion, which on rank-only RRF lifts TREC DL'19 nDCG@10 from .737 to .755 and DL'20 from .715 to .736 — with the paper's own caveat that "QPP estimates work more effectively in conjunction with retrieval scores than reciprocal ranks", i.e. gains are larger for score fusion than for the rank-only RRF you run ([arXiv 2601.17339](https://arxiv.org/abs/2601.17339)).

### Concrete fusion changes, in order

1. If the lexical arm returns 0 rows, return dense-only **explicitly** and log it. Same output, now intentional and measurable.
2. If the question's script is absent from the project's regconfig script, set `w_lex = 0` — or skip the lexical query entirely and save the round trip.
3. If the lexical arm returns fewer than ~3 rows for a multi-term query, treat it as unreliable and drop it rather than let 1–2 junk rows tie your best semantic hit.
4. Do **not** add a third noisy arm (pg_trgm over full bodies) until 1–3 are shipped and logged.
5. Leave `k` alone. Cormack's own sweep has k=80 marginally beating k=60 (.2147 vs .2145) with a 0.6% spread across k ∈ [20,100], and his conclusion that k=60 "was near-optimal, but the choice was not critical" ([Cormack et al.](http://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)). k is not the lever.
6. Over-fetch before fusing. Supabase's reference function pulls `least(match_count, 30) * 2` per arm before fusion ([Supabase hybrid search](https://supabase.com/docs/guides/ai/hybrid-search)); a wider pool protects the weaker arm, which for you is always the lexical one.

---

## 4. The gate: your weak-similarity floor is a QPP predictor, and it is the weakest one

### What it is called

Thresholding the single highest retrieval score is the **Max Score** predictor, a standard baseline in the query performance prediction literature: "a simple predictor might be the Maximum Score among the retrieved documents" ([arXiv 2310.11405](https://arxiv.org/abs/2310.11405)). Your "best similarity below a floor" gate is exactly this, with a hand-set threshold.

### How well that class correlates with retrieval success

Kendall τ against nDCG@10 on TREC DL'19/'20 ([arXiv 2310.11405](https://arxiv.org/abs/2310.11405)):

| Predictor | DL'19 BM25 | DL'19 ANCE | DL'19 TCT-ColBERT | DL'20 BM25 |
|---|---|---|---|---|
| **Max** | .157 (n.s.) | .316 | .250 | .214 |
| **NQC** (std dev of top-k scores) | .281 | .463 | .243 | .438 |

Max is beaten on 3 of 4 cells by a dispersion statistic computed from **the same numbers at the same cost**. On Robust04 the whole cheap family sits in a narrow band (Pearson ρ): `n(σ_x%)` **.589**, WIG .546, SMV .534, `σ_k` .522, Clarity .528, NQC .516, RSD .455 ([arXiv 2204.11489](https://arxiv.org/abs/2204.11489)).

Three constraints bound how far any of this can be trusted:

1. **Predictors do not transfer across collections.** NQC's Pearson r vs nDCG is **.354** on ROBUST/BM25 and **−.010** on MS MARCO/BM25 ([arXiv 2504.01101](https://arxiv.org/abs/2504.01101)). If a predictor cannot survive a change of English corpus, you cannot inherit a threshold from a paper — or from another project.
2. **They degrade on neural rankers.** Pre-retrieval predictors' mean correlation collapses from **25.6%** (traditional IR) to **6.2%** (neural IR) on Robust04, while post-retrieval predictors "perform similarly on TIR and NIR (34.5% vs 32.3%)" ([arXiv 2302.09947](https://arxiv.org/abs/2302.09947)). Since your surviving arm is dense, this argues specifically for **post-retrieval, score-based** signals.
3. **QPP predicts ranking, not answers.** In a RAG variant-selection study, NQC correlated r ≈ **0.33** with nDCG@5 on a dense retriever but **−0.004** with the Nugget-All answer-quality metric; an oracle maximising nDCG@5 on BM25 raised retrieval from .285 to .644 yet delivered only .344 answer quality, while an oracle optimising answer quality directly delivered .536 ([arXiv 2604.22661](https://arxiv.org/abs/2604.22661), n = 56 queries — small). In agentic RAG, Spearman ρ between first-iteration QPP and final answer F1 tops out at **.2497** across six retriever/predictor cells ([arXiv 2507.10411](https://arxiv.org/abs/2507.10411)).

**No QPP predictor in the published record has been calibrated cross-lingually.** That is a documented gap, not an omission — you must fit your own threshold.

### Cheaper / better predictors you could swap in

| Predictor | Inputs | Cost | Why it beats a bare max floor |
|---|---|---|---|
| **UQC** — unnormalised score variance over top-k | the cosines already on your rows | one pass over ≤k floats | Beats NQC on 3 of 4 ROBUST cells (.407/.439 vs .354/.295) and needs no corpus baseline ([arXiv 2504.01101](https://arxiv.org/abs/2504.01101)) |
| **σ-50%** — std dev over docs scoring ≥50% of the top score | same | same | Best Pearson (.589) of seven classical predictors on Robust04 ([arXiv 2204.11489](https://arxiv.org/abs/2204.11489)); defined *relative to the top score*, so a threshold survives the compressed cosine range of a cross-lingual query. Definition in [arXiv 2604.22661](https://arxiv.org/abs/2604.22661) |
| **SMV** — mean and variance combined | same | same | The principled version of "use max AND spread together"; Robust04 ρ .534, level with NQC ([arXiv 2204.11489](https://arxiv.org/abs/2204.11489)) |
| **Largest-gap (Adaptive-k)** | sorted scores, first differences, cut at the max gap, +5 buffer, top 90% only | free | Scale-free cutoff — gap *location* is invariant under affine rescaling. Cuts context tokens 99.24% on HotpotQA at 63% accuracy vs 74% for an oracle fixed-25k ([arXiv 2506.08479](https://arxiv.org/abs/2506.08479)): a token lever, not an accuracy lever |
| **df-coverage** — fraction of query lexemes with `ndoc > 0` in this project | a `ts_stat` term-df table refreshed at ingest | one lookup, **pre-retrieval** | Fires *before* either search runs, is script-agnostic, and catches Hinglish where a Unicode gate is blind. External corpus-frequency features matched LLM-uncertainty methods at ~1.0 LM calls vs 1.7–2.0 across six QA datasets ([arXiv 2505.04253](https://arxiv.org/abs/2505.04253)) |
| **A-Pair-Ratio** — coherence of top- vs bottom-ranked retrieved embeddings | k² dot products on vectors you already have | sub-ms at k=20 | Best of four predictors on a dense retriever (ρ .2497) in agentic RAG, beating both NQC and Max ([arXiv 2507.10411](https://arxiv.org/abs/2507.10411)) |
| **Calibration** (a wrapper, not a predictor) | labelled (question, did-retrieval-succeed) pairs | one logistic/isotonic fit per language group | Turns "is cosine > 0.35" into "is P(success) > 0.5", which *is* comparable across languages. Out-of-fold ECE dropped 0.643 → 0.009 on NQ, 0.275 → 0.062 on TriviaQA, 0.711 → 0.031 on MS MARCO ([arXiv 2606.29959](https://arxiv.org/abs/2606.29959)) |

**Two traps.** (a) **Do not use IDF-max as the routing signal.** `IDF = log(N/df)` is *maximal* for a term with `df = 0`, so a Devanagari or Hinglish query against an English index scores as maximally *specific*, and a rule that picks the highest-scoring variant will pick the untranslated query. Read raw `df`/coverage instead, with an explicit `df = 0` policy. (A pre-retrieval predictor *did* win the RAG variant-selection study — IDFmax lifted BM25 Nugget-All 0.273 → 0.398, +45.8% ([arXiv 2604.22661](https://arxiv.org/abs/2604.22661)) — but that study is monolingual English at n=56, and the sign inverts out of vocabulary.) (b) **Do not build an elaborate router.** Threshold selection between BM25 and BM25+QE on ROBUST: BM25 alone .5106, BM25+QE .5322, oracle .5393, UQC-selective .5325; a trained SVM router between BM25 and SPLADE captured 0.15 of a 3.70-point oracle gap. The paper's words: "QPP-driven selective query processing offers only marginal gains" ([arXiv 2504.01101](https://arxiv.org/abs/2504.01101)). A coarse binary gate for one cheap fallback is the right ambition.

### Fix the gate's *trigger*, not just its statistic

Your Unicode script gate structurally cannot fire on Hinglish. Sentence-level LID is the wrong replacement on the *query* side — Elastic's own guidance warns that "search queries tend to be short. Like, really short!" (average 2.4 terms) and that "many language identification algorithms work best with more than 50 characters" ([Elastic multilingual search](https://www.elastic.co/blog/multilingual-search-using-language-identification-in-elasticsearch)). Two things that do work:

- **Romanized LID.** IndicLID is "the first LID for romanized text in Indian languages", built precisely because romanized Hindi and Urdu are near-inseparable ([Bhasha-Abhijnaanam, arXiv 2305.15814](https://arxiv.org/abs/2305.15814)). Synthetic training with realistic spelling variation raises romanized-LID F1 on 20 Indic languages from 74.7% to **85.4%**, and **88.2%** with harvested text ([arXiv 2504.21540](https://arxiv.org/abs/2504.21540)). Word-level Hinglish LID reaches 94.52% on SAIL ICON 2017 with a single-layer LSTM over sub-word representations ([arXiv 2011.11263](https://arxiv.org/abs/2011.11263)). Being wrong is cheap both ways: a false positive costs one translation call; a false negative is your current behaviour.
- **Document-side LID at ingest** (if you go per-row regconfig): GlotLID-M covers 1,665 languages and scores F1 **0.978** on FLORES-200 and **0.868** on UDHR, against CLD3's 0.753 / 0.544 and fastText lid.176's 0.775 / 0.566 ([GlotLID, arXiv 2310.16248](https://arxiv.org/abs/2310.16248)). CLD3's repo "was archived by the owner on Jun 15, 2024" ([google/cld3](https://github.com/google/cld3)); fastText `lid.176.ftz` is 917 kB ([fastText LID](https://fasttext.cc/docs/en/language-identification.html)). Store the label plus a confidence and fall back to `simple` when confidence is low.

---

## 5. The ranked, costed plan

Ordered by value ÷ effort, cheapest first. **[C]** = config/code only, no schema. **[M]** = migration. **[S]** = new service or dependency.

---

### 1. Instrument the fusion. **[C]** — half a day

Log, per query: detected script/language, whether the translation gate fired, lexical row count, semantic row count, `|lexical ∩ semantic|` over the candidate sets, top cosine, σ-50% of the cosines, and which fusion branch executed.

**Experiment that proves/kills it:** none needed — this is the measurement everything else depends on. The two numbers to get out of it: **what fraction of queries have zero overlap between the arms** (those are round-robin, per section 3), and **how often the lexical arm returns 1–3 rows on a non-English query** (that is the junk-ties-your-best-hit case, currently invisible).
**Dataset:** production traffic, one week, split by detected script. You already meter tokens through Langfuse, so the plumbing exists.

---

### 2. Audit the vector index and turn two knobs. **[C]** — one day

Three checks, in order:

- `SELECT extversion FROM pg_extension WHERE extname='vector';` and confirm the embedding column's actual type and dimension. **A 3072-dim `vector` cannot take an HNSW index** (cap 2,000; `halfvec` 4,000) ([pgvector README](https://github.com/pgvector/pgvector)). If you are silently exact-scanning, that is your latency story, not your recall story.
- `SET hnsw.ef_search = 100;` (default 40) — "A higher value provides better recall at the cost of speed" ([pgvector README](https://github.com/pgvector/pgvector)).
- `SET hnsw.iterative_scan = relaxed_order;` if pgvector ≥ 0.8.0 (released 2024-10-30). Without it, "filtering is applied after the index is scanned. If a condition matches 10% of rows, with HNSW and the default `hnsw.ef_search` of 40, only 4 rows will match on average" ([pgvector README](https://github.com/pgvector/pgvector)). Every one of your queries filters on `project_id`. `relaxed_order` costs nothing because RRF re-ranks anyway.

**Experiment:** replay the 28 non-English questions at `ef_search` 40 / 100 / 200 and against the exact-scan fallback path — which is effectively `ef_search = ∞` and gives you free ground truth. Measure recall@20. If the exact path finds chunks the HNSW path misses, that gap **is** the `ef_search` deficit.
**Kill criterion:** no recall difference between 40 and 200 ⇒ the gate is not being starved by ANN; move on.
**Dataset:** the 28 questions plus a matched English control set of the same size.

---

### 3. Make the fusion honest: gate and weight the lexical arm. **[C]** — one to two days

```sql
ORDER BY ( coalesce(1.0/(60 + r_lex), 0) * :w_lex
         + coalesce(1.0/(60 + r_sem), 0) * :w_sem ) DESC
```

Drive `w_lex` from the signal you already compute: 0 when the question's script is absent from the project's regconfig script, or when the lexical arm returned fewer than 3 rows on a multi-term query; 1 otherwise. Log which branch fired. Do not touch `k`.

**Experiment:** A/B on the instrumented traffic from step 1, reporting (a) nDCG@10 against your labelled set and (b) **answer quality from the Langfuse judges** — because retrieval-optimal ≠ answer-optimal, and that divergence is documented, not hypothetical ([arXiv 2604.22661](https://arxiv.org/abs/2604.22661)).
**Kill criterion:** if step 1 shows the lexical arm essentially never returns 1–3 junk rows, the weight change is a no-op and you ship only the explicit dense-only branch, for loggability.
**Dataset:** production replay + the 28-question set.
**Prior art for the shape:** [Supabase hybrid search](https://supabase.com/docs/guides/ai/hybrid-search) exposes exactly these two weights; measured effect of weighting ranges from +4.2% to a regression depending on corpus ([MMMORRF, arXiv 2503.20698](https://arxiv.org/abs/2503.20698)).

---

### 4. Route the translation you already pay for into the lexical arm. **[C]** — one to two days

You already generate an LLM translation of the question and feed it to the embedder. Feed the same string to `websearch_to_tsquery(<project regconfig>, translated)`. This converts your 28/28 zero-row measurement into non-zero lexical rows using code you already have, with no schema change.

Three refinements, all query-side:

- **Do not collapse to one translation.** Single-best substitution scores average precision **0.0391** on TREC5C-long; ORing the synonym set scores **0.2306**; probability-weighted scores **0.2735** ([Xu & Weischedel, EMNLP/VLC 2000](https://aclanthology.org/W00-1312/)). Manual human disambiguation of translations improved results only 17% / 4% / −1% and was not statistically significant — keeping ambiguity is the point, not a compromise. Change the prompt to emit 3–8 English alternatives per content word and OR them.
- **Build the tsquery in application code.** Postgres cannot express per-term probabilities: `ts_rank`/`ts_rank_cd`'s optional weights array is `{D,C,B,A}` *document-side* lexeme labels set by `setweight`, defaulting to `{0.1,0.2,0.4,1.0}`; query-side `:A`/`:B` labels are match *filters*, not weights ([textsearch-controls](https://www.postgresql.org/docs/current/textsearch-controls.html)). Also, `to_tsquery` raises syntax errors on unsanitised tokens and `plainto_tsquery` ANDs everything — so build each alternative with `plainto_tsquery` under the project regconfig and combine with `||`. If you want probability weighting, issue 2–3 tsqueries by probability tier and fuse them as extra RRF arms, machinery you already own.
- **Add a run, do not replace the query.** Exp4Fuse runs the same retriever on the original and expanded query and fuses with a modified RRF at k=60, lifting BM25 nDCG@10 from 50.6 to 62.0 on DL'19 and R@1k from 75.0 to 87.0 ([arXiv 2506.04760](https://arxiv.org/abs/2506.04760)). Four arms — lexical×{original, translated}, semantic×{original, translated} — means a bad translation dilutes rather than destroys.

**Expected magnitude, honestly:** query translation is the *weakest* of the classical repairs. On NeuCLIR 2022 Chinese, query-translation BM25 gets nDCG@20 0.1830 vs document translation's 0.3705 — half the effectiveness — while Persian (0.3331 vs 0.3665) and Russian (0.3564 vs 0.3693) barely move ([Lin et al., arXiv 2304.01019](https://arxiv.org/abs/2304.01019)). Averaged over 8 collections / 456 topics, QT-BM25 gets R@100 0.477 / MAP 0.267 vs DT-BM25's 0.546 / 0.302 and PSQ-HMM's 0.585 / 0.332 ([arXiv 2404.18797](https://arxiv.org/abs/2404.18797)). The gap widens with linguistic distance — your case.
**The upside case is nonetheless large:** a Sinhala/Tamil→English e-government RAG study measured R@15 of **8.2% / 4.2%** with a monolingual English embedder and no adaptation, rising to **92.4% / 93.0%** with plain Google-Translate query translation ([arXiv 2608.12820](https://arxiv.org/abs/2608.12820)) — 500 QA pairs over 1,699 contexts with one gold passage per query, an easier setting than a production chunk store.
**Experiment:** the 28 questions, measuring lexical rows returned, recall@20 of the fused list, and judge-scored answer quality. Ablate translated-into-lexical alone vs + alternatives vs + four-arm fusion.
**Kill criterion:** lexical rows go non-zero but fused recall@20 does not move ⇒ the dense arm was already finding everything the lexical arm can, and you stop here rather than escalating to steps 7 and 8.

---

### 5. Build the eval set, then replace the gate's statistic. **[C]** — three to five days

Nothing else in this plan is decidable without this, and it is the item most likely to be skipped.

Build four slices: (a) the 28 non-English questions with known-good gold chunk ids; (b) a matched English control set; (c) **parallel chunks** — the same content in both languages; (d) romanized-Hinglish rewrites of the 28. Slice (c) matters because single-number retrieval metrics *hide* language bias: evaluating 31 retrievers, MLAIRE found "semantically strong retrievers may return correct content in a non-query language, while retrievers with stronger query-language preference may retrieve less semantically relevant passages" ([arXiv 2605.07249](https://arxiv.org/abs/2605.07249)), and language identity "can inflate similarity for same-language pairs and crowd out relevant evidence written in other languages" ([LANGSAE, arXiv 2601.04768](https://arxiv.org/abs/2601.04768)). Slice (d) is the only way to see the Hinglish failure at all, since no published benchmark covers it.

Then swap Max for a two-term gate: **σ-50% over the cosines** ([arXiv 2604.22661](https://arxiv.org/abs/2604.22661); best Pearson of seven on Robust04 per [arXiv 2204.11489](https://arxiv.org/abs/2204.11489)) plus **df-coverage** from a per-project term-df table built with `ts_stat` and refreshed at ingest ([textsearch-features](https://www.postgresql.org/docs/current/textsearch-features.html)). Fit a logistic regression per language group mapping (max, σ-50%, lexical-row-count, df-coverage) → P(retrieval succeeded) and gate on the calibrated probability rather than a raw cosine constant ([arXiv 2606.29959](https://arxiv.org/abs/2606.29959)).

Two SQL gotchas: `stddev_samp` returns NULL for n < 2 — exactly the one-strong-hit case — and NULLs sort first under `ORDER BY ... DESC` in Postgres, so use `stddev_pop` or `COALESCE(..., 0)` and exclude lexical-only rows carrying no cosine. Window functions are also illegal in `WHERE`, so σ-50% needs two query levels, not one CTE.

**Experiment:** held-out split. Report gate precision/recall against "did retrieval find the gold chunk", plus calibrated ECE. Track billed tokens and p50/p95 latency with the gate always-on / always-off / conditional — if the gate produces neither a token-and-latency win nor an answer-quality win, collapse it in one direction ([cost-aware routing framing, arXiv 2606.02581](https://arxiv.org/abs/2606.02581) — n=28 queries, single-author preprint, **UNVERIFIED** as a magnitude claim; use the framing only).
**Kill criterion:** σ-50% does not beat the max floor on held-out data ⇒ keep the max floor, now knowing it is fine, and you have the eval set regardless.

---

### 6. Fix the Hinglish blind spot. **[C] + small [S]** — two to four days

Add romanized language identification alongside the Unicode script check: if the query is Latin-script but classified as romanized Hindi/Tamil/etc. rather than English, open the cross-lingual path. An 85–88% F1 classifier is enough to gate on ([arXiv 2504.21540](https://arxiv.org/abs/2504.21540)); a word-level LSTM reaches 94.52% on Hindi-English ([arXiv 2011.11263](https://arxiv.org/abs/2011.11263)). Or fold the question into the LLM call you already make.

**Do not** add a separate transliteration step. Romanized-Hindi → Devanagari does not help against an *English* corpus — you need translation — and IndicXlit's Hindi Top-1 word accuracy on Dakshina is **60.56** ([Aksharantar, arXiv 2205.03018](https://arxiv.org/abs/2205.03018)), so compounding a ~60% word-accuracy step into an MT step is worse than one LLM call. GPT-family models already "generally outperform other LLMs and IndicXlit for most instances" on Indic transliteration ([arXiv 2505.19851](https://arxiv.org/abs/2505.19851)). Keep IndicXlit filed for the future case where a customer's `document_language` is Hindi and users type romanized — the one configuration where Roman→Devanagari is the right transform.

Optionally add a narrow `pg_trgm` index over titles or entity spans for Hinglish spelling variance, gated on "Latin script but not English" ([pgtrgm](https://www.postgresql.org/docs/current/pgtrgm.html)). Do **not** put it over full chunk bodies and do not let it into the default fusion.

**Experiment:** slice (d) of the eval set. Measure gate fire rate on Hinglish before and after, then end-to-end answer quality.
**Kill criterion:** production logs from step 1 show negligible Latin-script non-English traffic ⇒ defer.

---

### 7. Bake off the embedder — this is the root cause. **[M]** — one to two weeks

Your entire cross-lingual capability rests on one embedder you have never benchmarked, and the published numbers put it near the bottom of exactly your task shape. XTREME-UP MRR@10 (non-English query → English passage), averaged over 20 largely-Indic languages ([Gemini Embedding, arXiv 2503.07891](https://arxiv.org/abs/2503.07891)):

| Model | Avg | Hindi | Marathi | Gujarati | Punjabi | Tamil |
|---|---|---|---|---|---|---|
| text-embedding-3-large | **18.8** | 40.4 | 25.5 | 14.6 | 11.3 | 6.0 |
| multilingual-e5-large-instruct | 18.7 | 30.6 | — | — | — | — |
| Gecko i18n | 35.0 | — | — | — | — | — |
| voyage-3-large | 39.2 | 54.3 | 45.5 | 46.7 | 48.4 | 36.0 |
| **Gemini Embedding** | **64.3** | 69.1 | 68.8 | 70.3 | 69.5 | 68.6 |

Corroborating: XOR-Retrieve Recall@5kt 68.76 vs Gemini's 90.42; MTEB(Multilingual) Mean(Task) 58.92 vs 68.32 ([arXiv 2503.07891](https://arxiv.org/abs/2503.07891)). MIRACL nDCG@10 average: text-embedding-3-large **54.9** vs mE5-large 66.6 ([BGE-M3, arXiv 2402.03216](https://arxiv.org/abs/2402.03216)). MKQA cross-lingual R@100: text-embedding-3-large **69.5**, mE5-large 70.9, BGE-M3 dense **75.1** ([BGE-M3](https://arxiv.org/abs/2402.03216)) — i.e. roughly 30% of cross-lingual questions have no relevant passage in the top 100 for your current embedder, and no reranker recovers those.

**Two bonuses.** (a) A 1024- or 1536-dim replacement fits under pgvector's plain-`vector` HNSW ceiling of 2,000, so the migration *simplifies* your indexing and cuts storage 2–3× ([pgvector README](https://github.com/pgvector/pgvector)). text-embedding-3-large itself accepts a `dimensions` parameter and "can be shortened to a size of 256 while still outperforming an unshortened text-embedding-ada-002 embedding with a size of 1536" ([OpenAI embeddings guide](https://developers.openai.com/api/docs/guides/embeddings)), with jina-v3's measured MRL curve showing 1024→256 costing only 0.63 nDCG@10 (63.35 → 62.72) ([arXiv 2409.10173](https://arxiv.org/abs/2409.10173)). (b) A near-free alternative to test *first*: LIR post-hoc removal of the language-identity direction from stored embeddings "yields almost 100% relative improvement in MAP for weak-alignment models" on LAReQA ([arXiv 2109.04727](https://arxiv.org/abs/2109.04727)); the related SHIFT lifts mE5-large from 0.494 to 0.649 nDCG@20 on MLQA and 0.816 to 0.910 on Belebele, but gains are model-dependent — BGE-M3 improves only ~0.3% ([arXiv 2606.18801](https://arxiv.org/abs/2606.18801)) — and there is **no published number for text-embedding-3-large** (UNVERIFIED).

**Migration reality:** dimensionality is part of the column *type*, so this is DDL on the hot table plus a full re-embed and index rebuild. Every similarity floor, the weak-similarity gate, and the UI "match %" must be **re-calibrated**; absolute cosines are not comparable across embedders. RRF itself is rank-only and survives untouched.
**Experiment — the acceptance criterion, and it is not MTEB average:** LAReQA-style *mixed-pool strong alignment*, i.e. Hindi question against a candidate pool containing both the English gold chunk and unrelated Hindi distractors. The paper's warning is exactly on point: "the embedding baseline that performs the best on LAReQA falls short of competing baselines on zero-shot variants of our task that only target weak alignment" ([arXiv 2004.05484](https://arxiv.org/abs/2004.05484)). Run it on slices (a)–(c) of your own eval set, not on published averages.
**Kill criterion:** the incumbent is within a few points of the challengers on *your* data ⇒ skip the migration and spend the budget on steps 4 and 8.

---

### 8. Add a reranker on the translated query — only after steps 2 and 7. **[S]** — one week

Reranking is the only cross-lingual repair that touches no schema: it sits between RRF and generation. But it has a hard ceiling and a real failure mode.

- **Feed it the English translation, not the Hindi original.** On CIRAL (top-100 off BM25-DT, nDCG@20), RankGPT-4 goes 0.3577 / 0.3268 / 0.2991 / 0.4738 cross-lingual → 0.3967 / 0.3812 / 0.3694 / 0.5355 in English, and RankZephyr 0.2741 / 0.2996 / 0.2881 / 0.4218 → 0.3686 / 0.3622 / 0.3601 / 0.4887 ([arXiv 2312.16159](https://arxiv.org/abs/2312.16159)). Independently: "Without MT, current state-of-the-art rerankers fall severely short when directly applied in CLIR" — RankZephyr 0.365 native vs 0.477 document-translated ([arXiv 2509.14749](https://arxiv.org/abs/2509.14749)). This is one line of code given step 4.
- **Pick K = 25–50, not 300.** Across academic and enterprise datasets, rerankers improved Recall@10 for at least one K in 85.0% / 88.9% of experiments, but "Helps & Never Hurts" held in only 23.3% / 22.2%, and scaling K produced Recall@10 *worse* than retrieval alone 53.3% / 44.4% of the time ([Drowning in Documents, arXiv 2411.11767](https://arxiv.org/abs/2411.11767)). Depth is not the lever: Rank-K got its NeuCLIR jump (RankZephyr 0.281 → Rank-K 0.440 average nDCG@20 on the BM25 pool) at depth **20**, purely by swapping an English-trained reranker for a multilingual one ([arXiv 2505.14432](https://arxiv.org/abs/2505.14432)).
- **Model choice.** On MMTEB-R, Qwen3-Reranker-0.6B scores **66.36** vs jina-reranker-v2-multilingual 63.73 and bge-reranker-v2-m3 58.36, with FollowIR (instruction following) +5.41 vs −0.68 and −0.01 ([Qwen3 Embedding, arXiv 2506.05176](https://arxiv.org/abs/2506.05176)) — and its instruction slot lets you literally state that language mismatch is expected. LAURA independently finds Qwen3 far less language-biased than BGE (its fairness fix gained +6.86 PEER on BGE but only +1.14 on Qwen3), and measures BGE-reranker-v2-m3 putting more than 70% of its top-5 in English or the query language across 13 languages ([arXiv 2604.20199](https://arxiv.org/abs/2604.20199)). Cohere Rerank is the lowest-integration hosted option, with Hindi in its documented language list and a documented 4096-token context for the v3 generation ([Cohere Rerank docs](https://docs.cohere.com/docs/rerank)); note that billing splits documents over 500 tokens into separately counted chunks ([Cohere pricing](https://cohere.com/pricing)). You have no GPU on Render, so a hosted API or a 0.6B model on a new worker are the only real choices — LLM listwise reranking costs ~11s/query at GPT-3.5 and ~32s at GPT-4 for top-100 ([RankGPT, arXiv 2304.09542](https://arxiv.org/abs/2304.09542)) and is out of the question in the request path.
- **Measure the ceiling first.** A reranker cannot exceed its candidate pool. Compute Recall@50 of your dense branch on the 28 questions before buying anything: if the gold chunk is not in the top 50, no reranker setting fixes it and you are back at step 7. Oracle reranking on CIRAL reaches 0.754 nDCG@20 with an M3 first stage vs 0.646 with BM25-DT ([arXiv 2509.14749](https://arxiv.org/abs/2509.14749)) — a perfect reranker on a worse pool still loses.
- **Do not translate the retrieved chunks before generation.** CrossRAG translates retrieved documents into a common language ([arXiv 2504.03616](https://arxiv.org/abs/2504.03616)), which costs a translation per chunk and corrupts the evidence you cite. Instead, note that XRAG finds "all evaluated models struggle with response language correctness" in the monolingual-retrieval setting — exactly your configuration ([arXiv 2505.10089](https://arxiv.org/abs/2505.10089)) — so **pin the output language explicitly in the generation prompt and add an answer-language check to your Langfuse judges**. Pass a translation-reliability signal into the prompt rather than rewriting the evidence ([QTT-RAG, arXiv 2510.23070](https://arxiv.org/abs/2510.23070)).

**Kill criterion:** dense Recall@50 on the 28 questions is low ⇒ skip the reranker entirely and do step 7.

---

### Deferred, with the reason

| Item | Why not now |
|---|---|
| Per-row regconfig migration (D/F) | The highest-value answer to the *stated* hard constraint, near-zero value for the *measured* failure. Ship when a real customer has a mixed-language corpus. Prerequisites: LID at ingest, a `simple` default, and dropping migration 0039's generated column ([textsearch-features](https://www.postgresql.org/docs/current/textsearch-features.html)) |
| PGroonga | Genuinely dissolves one-project-one-stemmer and is installable today ([Supabase PGroonga](https://supabase.com/docs/guides/database/extensions/pgroonga)) — but it is TF-only with no IDF ([PGroonga](https://pgroonga.github.io/)) and replaces `ts_rank_cd` wholesale. Becomes mandatory if a CJK or Thai customer appears |
| pg_search / vchord_bm25 | Not in [Supabase's build](https://github.com/supabase/postgres/tree/develop/nix/ext). A platform migration, not a retrieval decision |
| PSQ with a trained alignment table | Beats both QT and DT (R@100 .585 vs .477 / .546) but needs a per-pair alignment model and can inflate an index "as much as 20 times" ([arXiv 2404.18797](https://arxiv.org/abs/2404.18797)). No off-the-shelf Hindi table exists — [hltcoe/psq_translation_tables](https://huggingface.co/hltcoe/psq_translation_tables) covers de/es/fa/fr/it/ru/zh only. Take its *idea* cheaply in step 4 instead |
| Learned sparse (SPLADE / MILCO) | MILCO is the only model that makes a lexical arm cross the boundary (MKQA 76.6 R@100 vs BGE-M3 sparse 45.3) ([arXiv 2510.00671](https://arxiv.org/abs/2510.00671)) but needs a 560M encoder at ingest *and* query time. pgvector `sparsevec` caps HNSW at 1,000 non-zeros and IVFFlat does not support it at all ([pgvector README](https://github.com/pgvector/pgvector)). Watch, do not build |
| Learned fusion router | Oracle headroom is 21.8% and no lightweight router captured it reliably ([arXiv 2608.00183](https://arxiv.org/abs/2608.00183)); QPP-driven pipeline selection "offers only marginal gains" ([arXiv 2504.01101](https://arxiv.org/abs/2504.01101)). Use the deterministic script/df signal instead |
| `unaccent` | European Latin diacritics only ([unaccent](https://www.postgresql.org/docs/current/unaccent.html)); nothing for Devanagari, and it adds a custom regconfig your migrations must manage. Revisit for French/Spanish/Portuguese corpora |
| ICU tokenization in core Postgres | Does not exist. PostgreSQL's ICU integration is a *collation* provider governing ordering, comparison, case conversion and pattern matching ([collation](https://www.postgresql.org/docs/current/collation.html)); there is no ICU word-break path into `tsvector`. Recorded as a verified negative |
| `rum` index | Available on Supabase, gives in-index ranking without a heap scan, at slower build and insert ([postgrespro/rum](https://github.com/postgrespro/rum)). An optimization for a latency problem you have not demonstrated |

---

## One-paragraph summary for standup

Your lexical arm is dead across scripts for a structural reason no `regconfig` fixes, and rank-only RRF is currently hiding that behind a benign degeneracy — the danger is the *unmeasured* case where a Hinglish query returns two junk lexical rows that tie your best semantic hit. Instrument it, verify your HNSW index is real at 3072 dims, gate the lexical arm off on script mismatch, and route the translation you already pay for into `to_tsquery` as an OR of alternatives rather than a single best string. Then build the eval set — with parallel chunks and Hinglish variants — because the published numbers say your embedder averages 18.8 MRR@10 on Indic→English against 64.3 for the best available, and that, not the schema, is where the cross-lingual capability actually lives.
