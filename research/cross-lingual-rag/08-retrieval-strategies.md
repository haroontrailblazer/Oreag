# 08 — Retrieval Strategies: The Catalogue

**Scope.** Every search strategy that has been published for the case *query language ≠ document language*, rated against one concrete stack: Postgres + pgvector (HNSW, cosine, `text-embedding-3-large`) + a `content_tsv` generated column with one constant `regconfig` per project, fused by rank-only RRF at k=60.

**The measurement this document exists to explain.** Against an English `content_tsv`, all 28 non-English test questions returned **zero** lexical rows. That is not a bug in the lexical arm. It is the correct output of an inverted index whose posting lists are English stemmed lexemes, queried with Devanagari byte strings. The intersection is empty, so the BM25/`ts_rank_cd` sum is over zero terms and no document enters the candidate set.

---

## 1. Framing: a language boundary can only be crossed in three places

Every method below is one of three moves. Knowing which one you are making tells you what it costs and what it cannot do.

| Where | What you change | Cost model | Examples |
|---|---|---|---|
| **Query side** | Rewrite the query into the corpus language before it hits the index | Per query, forever, on the latency critical path | Query translation, PSQ / weighted-OR structured queries, dictionary expansion, transliteration, cross-lingual HyDE |
| **Index / document side** | Put corpus-language *or* query-language text into the index at ingest | Per document, once, off the critical path | Document translation into a pivot, doc2query into query languages, per-row `regconfig`, a second `simple` tsvector |
| **Inside the representation** | Train or choose a model whose vector or vocabulary space is shared across languages | Model training or vendor selection; per-token inference at ingest and query | Multilingual dense embedders, ColBERT-X, MILCO, SPLADE-X, BLADE, LIR/SHIFT post-hoc de-biasing |

Two structural consequences follow immediately.

1. **No amount of stemmer configuration is a language-boundary move.** Stemming is a within-language normalizer. Changing `regconfig` alters which lexemes a *Hindi document* produces; it cannot make a Hindi query share a lexeme with an English document. Per-row `regconfig` fixes mixed-language *corpora*; it does not touch this failure.
2. **Rank-only RRF makes the empty-arm case benign and the noisy-arm case dangerous.** With an empty lexical list every fused score reduces to `1/(60 + rank_dense)`, a strictly decreasing function of dense rank, so the output order is identical to dense-only — the current 28/28 result is silently degrading to pure semantic ranking, which is the correct fallback. But a lexical arm that returns *one* junk row scores `1/61 = 0.01639`, exactly what the dense arm's #1 result gets ([Cormack et al., SIGIR'09](http://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)). RRF has no vocabulary for "this arm found nothing good."

---

## 2. The master table

`Boundary` = does the method survive query-language ≠ document-language. **Yes** = designed for it; **Degrades** = works but measurably worse; **Breaks** = structurally returns nothing; **n/a** = infrastructure or evaluation, not a retrieval mechanism.

`PG?` = feasible on Postgres, and specifically on managed Supabase (the platform constraint: [`supabase/postgres` `nix/ext`](https://github.com/supabase/postgres/tree/develop/nix/ext) ships pgvector, pgroonga, rum, pg_cron, timescaledb and others — **no `pg_search`/ParadeDB, no `vchord`, no `pg_bigm`**).

### Lexical / sparse

| Method | One line | Boundary | Cost | PG? |
|---|---|---|---|---|
| [BM25](https://lucene.apache.org/core/9_10_0/core/org/apache/lucene/search/similarities/BM25Similarity.html) | IDF × saturating TF with length normalisation over post-analysis tokens | **Breaks** | Cheapest possible | Not on Supabase (no `pg_search`) |
| [Postgres `tsvector` + `ts_rank_cd`](https://www.postgresql.org/docs/current/textsearch-controls.html) | Cover-density ranking over Snowball lexemes; **no IDF at all** | **Breaks** | Already paid | Deployed |
| [BM25F](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf) | Pool per-field weighted TFs, *then* saturate and apply IDF | **Breaks** (orthogonal) | Negligible | Only a weaker analogue (`setweight` + `ts_rank_cd` weights) |
| [Snowball stemming](https://snowballstem.org/algorithms/) | Suffix-strip to a shared lexeme, one language per config | **Breaks** | Free where a stemmer exists | 28 UTF-8 stemmers bundled inc. `hindi`; only 15 stopword lists |
| [`simple` config](https://www.postgresql.org/docs/current/textsearch-dictionaries.html) | Lowercase + stopword check, no stemming, any script | **Breaks** (but never mis-stems) | Larger index, lower in-language recall | Built in |
| [`unaccent`](https://www.postgresql.org/docs/current/unaccent.html) | Diacritic folding before the stemmer | **Breaks** (Latin-only) | Trivial | Trusted extension |
| [`pg_trgm`](https://www.postgresql.org/docs/current/pgtrgm.html) | Character-trigram set overlap; script-agnostic *within* a script | **Breaks** across scripts | Large GIN, slow on long text | Ships with Postgres |
| [Character n-gram BM25](https://arxiv.org/abs/2608.21365) | Abandon word tokenisation; index 2–4-char n-grams | **Breaks** (but best option where no stemmer/segmenter exists) | Index size grows substantially | Only via PGroonga |
| [CJK bigram](https://lucene.apache.org/core/9_10_0/analysis/common/org/apache/lucene/analysis/cjk/CJKBigramFilter.html) | Overlapping character bigrams for unspaced scripts | **Breaks** | ~2× terms | PGroonga only (its `TokenBigram` passes Latin runs through; `pg_bigm` does not, and is unavailable) |
| [PGroonga](https://supabase.com/docs/guides/database/extensions/pgroonga) | Groonga n-gram FTS, **no regconfig at all** | **Breaks** | Bigger index, lower write throughput | **Yes — on Supabase**; TF-only scoring, no IDF |
| [`pg_search` / ParadeDB](https://github.com/paradedb/paradedb) | Real Tantivy BM25 in Postgres, ICU tokenizer, multiple analyzers per field | **Breaks** | New extension, AGPL-3.0 | **No** — absent from Supabase's build |
| [VectorChord-bm25](https://github.com/tensorchord/VectorChord-bm25) | Block-WeakAnd BM25 with pretrained/multilingual tokenizers | **Breaks** | AGPLv3/ELv2, Rust pgrx | **No** — absent from Supabase |
| [`pg_bigm`](https://github.com/pgbigm/pg_bigm) | 2-gram GIN FTS | **Breaks** | Unverified | **No** — absent from Supabase |
| [RUM](https://github.com/postgrespro/rum) | GIN successor storing positions → ranking without a heap scan | n/a | Slower build/insert than GIN | **Yes — on Supabase** |
| [tsvector impact encoding](https://www.postgresql.org/docs/current/textsearch-limitations.html) | Smuggle learned weights in via A/B/C/D or repeated lexemes | n/a | ~40× index bloat; caps bite | Technically yes, practically no |

### Learned sparse

| Method | One line | Boundary | Cost | PG? |
|---|---|---|---|---|
| [SPLADE v2 / v3](https://arxiv.org/abs/2403.06789) | MLM head emits a weight per vocabulary term; expansion + inverted index | **Breaks** (English WordPiece) | BERT pass per chunk; CC-BY-NC-SA licence | `sparsevec` storable, no WAND |
| [SPLADE-Doc / inference-free query](https://huggingface.co/opensearch-project/opensearch-neural-sparse-encoding-doc-v3-gte) | Expansion only at index time; query = tokenizer + weight lookup | **Breaks** | Ingest-only GPU; query ≈ BM25 | Best serving fit; doc nnz pushes the 1,000-nnz HNSW cap |
| [uniCOIL](https://arxiv.org/abs/2106.14807) | One learned scalar per *existing* term, no expansion | **Breaks** (definitionally exact-match) | One BERT pass/chunk | Yes via `sparsevec` |
| [DeepImpact / DeeperImpact](https://arxiv.org/abs/2405.17093) | Impact scores over docT5query-expanded text | **Breaks** | Two model passes at ingest | Yes, but BEIR avg 0.415 < BM25 0.429 |
| [TILDE / TILDEv2](https://arxiv.org/abs/2108.08513) | Single-pass query-term prediction as cheap expansion | **Breaks** | 1 forward pass vs docT5query's 140× | Expansion output is plain text → trivial |
| [SPARTA / DeepCT](https://arxiv.org/abs/2307.10488) | First-generation learned term weighting | **Breaks** | n/a | Irrelevant |
| [ELSER](https://www.elastic.co/docs/explore-analyze/machine-learning/nlp/ml-nlp-elser) | Elastic's production LSR — **shipped English-only by the vendor** | **Breaks** | Elastic ML node | No |
| [BGE-M3 sparse arm](https://arxiv.org/abs/2402.03216) | `ReLU(W·H)` weight per *present* token, scored over `q ∩ p` | **Degrades to ~BM25** | MIT; one pass gives dense+sparse+multivec | `sparsevec`; chunk must stay <1,000 unique tokens |
| [OpenSearch multilingual LSR v1](https://huggingface.co/opensearch-project/opensearch-neural-sparse-encoding-multilingual-v1) | 160M doc encoder, 105,879 dims, inference-free query, Apache-2.0 | **UNVERIFIED cross-lingually** | Ingest-only; CPU-viable query path | Excellent fit (138 nnz → 1,120 B) |
| [SPLADE-X](https://ceur-ws.org/Vol-3480/paper-06.pdf) | mBERT with output vocab masked to 33k English sub-words | **Yes, if trained per pair** | 4–8 V100s × 60–100k steps *per language pair* | No public checkpoint |
| [BLADE](https://doi.org/10.1145/3539618.3591644) | Vocabulary pruning + cross-language intermediate pretraining | **Yes** | One model per (query lang, doc lang) | Effectiveness numbers **UNVERIFIED** (paywalled) |
| [MILCO](https://arxiv.org/abs/2510.00671) | Multilingual connector projects any language into a **shared English lexical space**; `[ECHO]` head preserves entities | **Yes** | 560M encoder at ingest *and* query | `sparsevec` viable; needs GPU serving |
| [PSQ (index-time)](https://arxiv.org/abs/2404.18797) | Multiply doc TF vector by a word-alignment matrix → query-language pseudo-TFs | **Yes** | Up to 20× index; 1,975 GB unpruned for NeuCLIR ru | Wrong shape; fractional TFs unrepresentable |
| [pgvector `sparsevec`](https://github.com/pgvector/pgvector) | Storage layer for any of the above | n/a | 8·nnz+16 bytes | Type: 1e9 dims / 16,000 nnz; **HNSW: 1,000 nnz**; IVFFlat unsupported |

### Dense (single-vector)

| Method | One line | Boundary | Cost | PG? |
|---|---|---|---|---|
| [DPR](https://aclanthology.org/2020.emnlp-main.550/) | Dual BERT encoders, in-batch negatives, MIPS | **Breaks** (English) | 1 vector/chunk | This is the baseline shape |
| [mDPR](https://arxiv.org/abs/2108.08787) | Same, with mBERT/XLM-R, zero-shot | **Degrades badly** | Same | Trivially |
| [LaBSE](https://aclanthology.org/2022.acl-long.62/) | Translation-ranking dual encoder with additive margin | **Yes for bitext, weak for QA** | BERT-base, 768d | Native HNSW |
| [Multilingual distillation](https://arxiv.org/abs/2004.09813) | Force a translation and its source onto one frozen English teacher vector | **Yes (canonical strong-alignment recipe)** | Student fine-tune on parallel text | Self-hosting |
| [mSimCSE](https://arxiv.org/abs/2211.06127) | English-only contrastive training that exposes latent alignment | **Yes** | No parallel data needed | Yes |
| [LIR](https://arxiv.org/abs/2109.04727) | Post-hoc removal of the language-identity principal components | **Yes (repairs weak alignment)** | One matrix multiply; one full re-projection + reindex | Yes, but rebuild HNSW |
| [SHIFT](https://arxiv.org/abs/2606.18801) | Subtract a per-(model, language) offset vector at index time | **Yes** | Near zero; offline estimation | Yes; re-transform + REINDEX |
| [BGE-M3 dense](https://arxiv.org/abs/2402.03216) | XLM-R 560M, 1024d, 8192 tokens, 100+ languages | **Yes** | Self-hosted GPU | 1024d → native HNSW |
| [multilingual-E5](https://arxiv.org/abs/2402.05672) | XLM-R + 1B weak pairs + MIRACL fine-tune; needs `query:`/`passage:` prefixes | **Degrades** (strong multilingual, weak cross-lingual) | Free weights, 512-token max | 1024d native |
| [`text-embedding-3-large`](https://arxiv.org/abs/2503.07891) | The incumbent; 3072d, MRL-capable, training regime undisclosed | **Degrades badly on Indic** | API | 3072d **exceeds the 2,000-dim HNSW cap for `vector`** — must be `halfvec` or reduced |
| [Gemini Embedding](https://arxiv.org/abs/2503.07891) | Gemini-initialised embedder, MRL at 1536/768 | **Yes — current SOTA on Indic→English** | Paid API | 1536d → native HNSW |
| [voyage-3-large / -4](https://docs.voyageai.com/docs/embeddings) | Commercial, 32k context, selectable dims | **Degrades less than incumbent** | Paid API | 1024d default → native |
| [Cohere embed-v3/v4](https://docs.cohere.com/docs/cohere-embed) | 100+ languages, asymmetric `input_type`, binary embeddings | **UNVERIFIED — no published cross-lingual numbers** | Paid API | 1024/1536d; binary → pgvector `bit` |
| [jina-embeddings-v3](https://arxiv.org/abs/2409.10173) | 570M XLM-R + task LoRA adapters + MRL | **Not disaggregated** | CC-BY-NC weights | 1024d native |
| [Matryoshka (MRL)](https://arxiv.org/abs/2205.13147) | Nested embeddings; truncate + renormalise | **Orthogonal — neither creates nor destroys alignment** | Free (negative) | Turns 3072 into an indexable 1024/1536 |
| [Artificial code-switched training](https://arxiv.org/abs/2305.05295) | Lexicon-substitute terms in training pairs so language identity stops being a relevance signal | **Yes** | Fine-tune + host your own retriever | Different embedding column + full re-embed |

### Multi-vector (late interaction)

| Method | One line | Boundary | Cost | PG? |
|---|---|---|---|---|
| [ColBERT-X](https://arxiv.org/abs/2201.08471) | XLM-R late interaction (MaxSim), zero-shot or translate-train | **Yes** | Index 4.7–154 GB per collection | **No** MaxSim operator in pgvector |
| [Translate-Distill](https://arxiv.org/abs/2401.04810) | Distil a mono-English cross-encoder teacher into a CLIR student | **Yes — strongest published CLIR training regime** | MT of training set + 13B teacher inference | Released students are ColBERT-X |
| [Multilingual Translate-Distill](https://arxiv.org/abs/2405.00977) | Same for a *mixed-language* collection; score comparability across languages | **Yes** | + MT into every collection language | Training-side only |
| [BGE-M3 multi-vector](https://arxiv.org/abs/2402.03216) | ColBERT head alongside dense + sparse | **Yes** | GPU | Not indexable in pgvector |

### Query side

| Method | One line | Boundary | Cost | PG? |
|---|---|---|---|---|
| [Query translation (single-best)](https://arxiv.org/abs/2304.01019) | One MT/LLM call, then ordinary monolingual retrieval | **Yes, weakest of the translation repairs** | ~200–800 ms/query | **Yes — you already produce the string** |
| [Pirkola structured queries](https://aclanthology.org/W00-1312/) | OR all dictionary translations as one synonym concept, pooled df | **Yes** | A bilingual dictionary file | Yes — build the tsquery in app code |
| [Query-side PSQ (weighted OR)](https://arxiv.org/abs/2404.18797) | Same, but alternatives carry alignment probabilities | **Yes** | Query time only; ~50–200 MB table | Partially — **tsquery cannot carry per-term weights** |
| [PSQ-HMM scorer](https://trec.nist.gov/pubs/trec31/papers/umcp.N.pdf) | Background-smoothed query likelihood over the translation table | **Yes** | Arithmetic only | Only as a rescore over ~1k candidates |
| [Dictionary translation (naive)](https://aclanthology.org/W00-1312/) | Substitute the single best dictionary sense | **Yes but catastrophic** | Free | Yes |
| [Embedding-based query translation](https://arxiv.org/abs/1608.01561) | Learn a linear map between monolingual spaces from a seed dictionary | **Yes** | Two embedding models + 5k seed pairs | Offline table build |
| [Transliteration (Hinglish → Devanagari)](https://arxiv.org/abs/2205.03018) | IndicXlit seq2seq romanised↔native conversion | **Only helps if the corpus contains romanised/native forms** | ~11M params, MIT | Query-string preprocessing |
| [Romanised-script normalisation](https://arxiv.org/abs/2511.22769) | Normalise Hinglish before embedding | **UNVERIFIED for retrieval** | One model call | App layer |
| [Cross-lingual generative QE](https://arxiv.org/abs/2511.19325) | Translate → LLM writes a corpus-language pseudo-document → retrieve | **Yes** | 2 LLM calls/query | Yes — pseudo-doc is just a longer string |
| [HyDE](https://arxiv.org/abs/2212.10496) | Generate a hypothetical answer, embed *that* | **Never published cross-lingually** | 1 generation + 1 embed; +25–40% latency | Yes |
| [query2doc](https://arxiv.org/abs/2303.07678) | Concatenate query + pseudo-doc, repeat the query n× for BM25 | **Breaks** unless translated first | 1 few-shot generation | Repeat-trick does **not** work in `ts_rank` |
| [GRF](https://arxiv.org/abs/2304.13157) | Feedback LM built from LLM-generated long text, not from top-k | **Survives an empty first pass** — unlike PRF | 1 long generation | Yes (GRF); RM3 weights inexpressible |
| [CSQE](https://arxiv.org/abs/2402.18031) | LLM picks pivotal sentences from the *retrieved corpus* to expand with | **Needs a non-empty first pass** | 1 selection call | Yes |
| [Rocchio/RM3 over HyDE output](https://arxiv.org/abs/2511.19349) | Extract and weight expansion terms instead of concatenating | n/a | Negligible | Extraction yes, weighting no |
| [Step-back prompting](https://arxiv.org/abs/2310.06117) | Abstract the question to a higher-level concept | **Breaks** — wrong failure mode | 1 LLM call | Yes, but pointless here |
| [Query embedding interpolation](https://arxiv.org/abs/2606.13537) | Convex-combine the query vector with its translation's vector | **Helps non-English indices, ~zero on English ones** | 1 extra embed | Yes, client-side |
| [Multi-query rewriting (DMQR-RAG)](https://arxiv.org/abs/2411.13154) | N diverse rewrites, adaptive strategy selection | **Yes once rewrites are in the corpus language** | N generations + N searches | Yes, cost is linear |

### Document side

| Method | One line | Boundary | Cost | PG? |
|---|---|---|---|---|
| [Document translation into a pivot](https://arxiv.org/abs/2504.16264) | MT the corpus into one language at ingest, search monolingually | **Yes — strongest classical repair** | 1 MT call/chunk + 2nd tsvector + GIN | Yes: plain `content_en text` + generated tsvector over it |
| [T-SPLADE (translate corpus, then English LSR)](https://arxiv.org/abs/2302.14723) | Translate all corpora to English, fine-tune per-corpus SPLADE | **Yes — won MIRACL 2023** | 16 models + NLLB over the corpus | Only the translation half transfers |
| [doc2query / docT5query](https://arxiv.org/abs/1904.08375) | Append predicted queries to the chunk before indexing | **Breaks by default; the natural place to inject query-language vocabulary** | Autoregressive gen/chunk; 140× TILDE | Append into `content` = no migration |
| [doc2query--](https://arxiv.org/abs/2301.03266) | Filter hallucinated expansions with a relevance model | n/a | 1 scoring pass | App-side; do this for any ingest-time generation |
| [Doc2Token](https://arxiv.org/abs/2406.19647) | Predict missing tokens instead of whole queries | **Breaks** | Cheaper than doc2query | Same |
| [HyPE](https://arxiv.org/abs/2607.29402) | Generate hypothetical *questions* per chunk at ingest; question-to-question match | **UNVERIFIED cross-lingually; structurally attractive** | N generations/chunk, zero query latency | Dense half yes; lexical half hits the regconfig constraint |
| [Per-row `regconfig`](https://www.postgresql.org/docs/current/textsearch-features.html) | Each chunk stemmed under its own config | **Breaks** (fixes mixed corpora, not cross-lingual) | Trigger or expression index; full backfill | **Yes — documented in core Postgres** |
| [Concatenated multi-config tsvector](https://www.postgresql.org/docs/current/functions-textsearch.html) | `to_tsvector('english',c) \|\| to_tsvector('simple',c)` in one generated column | **Breaks** | Index grows ~linearly in configs | Legal, but **damages `ts_rank_cd`** (positions are offset) |
| [Multiple generated tsvector columns](https://www.postgresql.org/docs/current/ddl-generated-columns.html) | One column + GIN per regconfig, fused as extra RRF lists | **Breaks** | N× storage and write amplification | Yes; cap at ~3 |
| [Per-language partial indexes](https://www.postgresql.org/docs/current/indexes-partial.html) | `WHERE doc_language='hi'` expression indexes | **Breaks** | Planner must prove implication | Docs call the many-partial-index pattern "a bad idea" |
| [LIST partitioning by language](https://www.postgresql.org/docs/current/ddl-partitioning.html) | Physically separate rows per language | **Actively harmful** | PK must absorb the key; HNSW fans out | Yes — don't |
| [Chunk-level LID](https://arxiv.org/abs/2310.16248) | GlotLID/OpenLID tag each chunk at ingest | n/a (enabling primitive) | 917 kB model, µs/chunk | App layer → `chunks.language regconfig` |

### Fusion

| Method | One line | Boundary | Cost | PG? |
|---|---|---|---|---|
| [RRF k=60](http://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf) | `Σ 1/(k + rank)`, ranks only, scores discarded | **Degenerates safely on an empty arm; dangerous on a short noisy one** | Zero | Deployed |
| [Weighted RRF](https://arxiv.org/abs/2503.20698) | Per-arm (or per-doc) weight on each reciprocal-rank term | **Yes — the cheapest cross-lingual fix in this table** | Two multiplications | One line of SQL |
| [TM2C2 / theoretical min-max](https://ar5iv.labs.arxiv.org/html/2210.11934) | Normalise against the score's *theoretical* infimum, then convex-combine | **More fragile than RRF cross-lingually** | One MAX() per arm + a tuned α | `ts_rank_cd` has no theoretical max — only approximable |
| [Empirical min-max / Relative Score Fusion](https://docs.weaviate.io/weaviate/search/hybrid) | Rescale each arm to [0,1] using its own min and max | **Breaks — manufactures false confidence** | MIN()+MAX() | Yes; don't |
| [Z-score](https://ar5iv.labs.arxiv.org/html/2210.11934) | Standardise each arm's score distribution | **Partially survives; degenerate σ on short lists** | AVG+STDDEV | `stddev_samp` returns NULL at n=1 → NULLs sort **first** on DESC |
| [CombSUM / CombMNZ](http://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf) | Sum normalised scores, × number of arms that found the doc | **Breaks** — with 2 arms the multiplier is only 1 or 2 | Cheap | Pointless here |
| [Condorcet / Borda](http://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf) | Pairwise majority vote / positional points | **Breaks** — undefined with 2 voters | Condorcet is O(n²) | Borda trivial, both useless |
| [Round-robin interleaving](https://digitalcollection.zhaw.ch/bitstreams/17870429-2895-4ba1-aec5-e013307f1685/download) | One doc from each list in turn | **Breaks** | Zero | This is what RRF *becomes* on disjoint lists |
| [Collection-size-weighted interleaving](https://digitalcollection.zhaw.ch/bitstreams/17870429-2895-4ba1-aec5-e013307f1685/download) | Take from each list in proportion to its collection size | **Yes (analogically)** | Static constant | Requires adding a weight term |
| [Raw-score merging](https://link.springer.com/content/pdf/10.1023/B:INRT.0000009445.19495.46.pdf) | Sort the union by each engine's native score | **Breaks across dissimilar scorers** | Zero | Never mix raw `ts_rank_cd` with raw cosine |
| [Normalised-score merging (÷ max)](https://link.springer.com/content/pdf/10.1007/s10791-005-5722-4.pdf) | `RSV / max(RSV)` per list, then merge | **Degrades gracefully** | One MAX() per arm | Cleanest score-fusion upgrade available |
| [CORI](https://doi.org/10.1145/215206.215328) | Weight each source's docs by an independent *collection* relevance score | **Yes, structurally** | A per-source estimate | Degenerate 2-source form = weighted score fusion |
| [SSL regression / SAFE](https://doi.org/10.1145/564376.564382) | Fit a per-query calibration from overlap with a centralised sample index | **Breaks — needs overlap, which is exactly what's missing** | CSI + sampling + per-query fit | Overkill |
| [LTR / random-forest merging](https://www.emerald.com/insight/content/doi/10.1108/DTA-06-2021-0156/full/pdf) | Learn the merge function from labelled data | **Yes if the failure is in the training data** | Labels + training + serving | App layer |
| [Logistic regression on score + ln(rank)](https://link.springer.com/content/pdf/10.1007/s10791-005-5722-4.pdf) | `z = α + β₁·ln(rank) + β₂·rsv` per source | **Yes** | Per-language relevance judgements | Scoring trivial; *fitting* is the blocker |
| [2-step RSV](https://link.springer.com/content/pdf/10.1007/s10791-005-5722-4.pdf) | Pool document frequencies across a term and its translations, then rescore | **Yes — best merging result in the CLEF record** | Query-time rescore, no reindex | Needs a second-language lexeme stream to pool with |
| [Exp4Fuse](https://arxiv.org/abs/2506.04760) | RRF over an original-query run *and* an LLM-expanded-query run, k=60 | **Yes — makes expansion fail-safe** | 1 generation + N extra searches | **Best fit: it is your existing RRF with more input lists** |
| [Multi-vector query fusion](https://arxiv.org/abs/2411.03881) | Search with the original *and* translated embeddings, fuse the two lists | **Yes** | +1 embed, +1 ANN probe | Another input list to RRF |
| [QPP-weighted RRF](https://arxiv.org/abs/2601.17339) | Replace RRF's uniform prior with a per-arm confidence estimate | **Yes** | µs + a multiply | Yes — but gains are smaller on rank-only fusion |
| [IDF-weighted RRF (vstash)](https://arxiv.org/abs/2604.15484) | Pre-retrieval query IDF profile sets the lexical weight | **Careful — IDF is *maximal* for OOV terms** | One df lookup | Needs a per-project term-df table |
| [Single merged multilingual index](https://link.springer.com/content/pdf/10.1007/s10791-005-5722-4.pdf) | Index everything in one index, query with all translations | **Breaks** — merging the index does not merge the score spaces | Zero | Documented as disappointing |

### Rerank

| Method | One line | Boundary | Cost | PG? |
|---|---|---|---|---|
| [bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) | 0.568B XLM-R cross-encoder | **Yes, with measured language bias** | CPU: seconds for 50 chunks | App layer |
| [jina-reranker-v2-base-multilingual](https://jina.ai/news/jina-reranker-v2-for-agentic-rag-ultra-fast-multilingual-function-calling-and-code-search/) | 278M, 1024-token context, throughput-oriented | **Yes** | ~½ BGE's params | App layer |
| [Qwen3-Reranker 0.6B/4B/8B](https://arxiv.org/html/2506.05176v1) | Decoder LLM, yes/no logits, **instruction slot**, 32k ctx, Apache-2.0 | **Yes — strongest open multilingual reranker** | 0.6B decoder; GPU for interactive use | App layer |
| [Cohere Rerank multilingual](https://docs.cohere.com/docs/rerank) | Hosted cross-encoder, 100+ languages incl. Hindi | **Claimed; no published numbers** | Per-search billing; >500-token docs auto-chunked | HTTP call |
| [Voyage rerank-2.5](https://docs.voyageai.com/docs/reranker) | Hosted, 32k context, ≤1,000 docs/request | **UNVERIFIED — Hindi not listed** | Per-token | HTTP call |
| [mMARCO cross-encoders](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1) | 100M distilled XLM-R on translated MS MARCO | **Yes for short QA, collapses on long docs** | Cheapest credible multilingual CE | Plausibly in-process on CPU |
| [RankGPT listwise](https://arxiv.org/html/2304.09542v3) | LLM emits a permutation over a sliding window of 20 | **Yes** | 11 s (GPT-3.5) to 32 s (GPT-4) per query at top-100 | App layer; destroys streaming UX |
| [Rank-K](https://arxiv.org/html/2505.14432v1) | QwQ-32B reasoning listwise reranker over top-20 | **Yes** | ~2,400 reasoning tokens/call | Not deployable here |
| [Translate-then-rerank](https://arxiv.org/html/2312.16159v1) | Put query and documents in the same language before scoring | **Yes — the cheapest reranking win** | Free (reuse the existing translation) | One string swap |
| [Permutation distillation](https://arxiv.org/html/2304.09542v3) | Distil an LLM reranker's orderings into a small cross-encoder | **UNVERIFIED cross-lingually** | ~$40 teacher + fine-tune (English demo) | Offline |
| [LAURA](https://arxiv.org/abs/2604.20199) | Realign a reranker toward downstream generative utility, not language match | **Yes (bias measurement + fix)** | Reranker training | Not applicable |
| [LAMAR](https://arxiv.org/abs/2607.22042) | Cross-encoder trained to *prefer the query's language* | **Deliberately hostile to this use case** | Training | Avoid |

### Routing / gating

| Method | One line | Boundary | Cost | PG? |
|---|---|---|---|---|
| [Unicode script gate](https://www.postgresql.org/docs/current/textsearch-parsers.html) | Is the question's script absent from the corpus? | Works for Devanagari; **blind to Hinglish** | Zero | Deployed |
| [Sentence LID (fastText / GlotLID)](https://fasttext.cc/docs/en/language-identification.html) | Classify query language, not just script | **Better than a script gate** | 917 kB, sub-ms | App layer |
| [Word-level code-mixed LID](https://arxiv.org/abs/2011.11263) | Per-token language labels for Hinglish | **The only method that sees Hinglish** | Small LSTM | App layer |
| [Max Score (the current gate)](https://ar5iv.labs.arxiv.org/html/2310.11405) | Top retrieval score as a confidence proxy | n/a — **uncalibrated across languages** | Free | Already there |
| [NQC / UQC](https://arxiv.org/html/2504.01101v1) | Std dev of the top-k scores | n/a | One pass over k floats | `stddev_samp` over the CTE |
| [σ-50% / n(σₓ%)](https://arxiv.org/html/2604.22661v1) | Dispersion over documents scoring ≥50% of the top score | **Scale-free → portable across languages** | Same | Two-level select (window fns are illegal in WHERE) |
| [SMV / WIG / Clarity / RSD](https://ar5iv.labs.arxiv.org/html/2204.11489) | Other classical post-retrieval predictors | Clarity **breaks** (it is a lexical statistic) | WIG needs a corpus baseline | WIG's baseline = one centroid dot product |
| [Pre-retrieval IDF/ICTF/SCQ/SCS](https://arxiv.org/html/2604.22661v1) | Predict difficulty from query + corpus stats before searching | **Careful — IDF is maximal for OOV terms** | One df lookup | Needs a per-project df table |
| [Selective query processing](https://arxiv.org/abs/2504.01101) | QPP picks which retrieval pipeline to run | n/a — **published as a near-null result** | Cheap | Yes; don't over-invest |
| [Adaptive hybrid weighting](https://arxiv.org/abs/2608.00183) | Learn the sparse/dense interpolation weight per query | n/a — **routers do not reach the oracle** | Low (rule) to high (learned) | Rule-based is trivial |
| [Adaptive-k](https://arxiv.org/abs/2506.08479) | Cut the result list at the largest score gap | **Cut point is scale-free; "gap too small" is not** | Free | `lag()` over the ranked CTE |
| [Calibrated budget allocation](https://arxiv.org/abs/2606.29959) | Convert raw confidence into P(correct) via out-of-fold calibration, then threshold | **The right tool for a language-dependent floor** | A labelled set + a logistic fit | App layer |
| [Adaptive-RAG](https://arxiv.org/html/2403.14403v2) | Complexity classifier routes to no-/single-/multi-step retrieval | Routing half transfers; iterative half does not | Small classifier | App layer |
| [Self-RAG](https://arxiv.org/abs/2310.11511) | Reflection tokens make retrieval a generation-time decision | **Entangles retrieval language with generation language** | Fine-tune the generator | Forecloses hosted models |
| [FLARE](https://arxiv.org/abs/2305.06983) | Retrieve when the *generator's* next-sentence confidence is low | n/a — gates on the wrong signal for a multilingual product | Multiple generation passes | Needs logprobs |
| [LLM-independent adaptive retrieval](https://arxiv.org/html/2505.04253v1) | 27 pre-computable external features instead of model uncertainty | **Frequency features are script-agnostic** | Table lookup | Needs a df table; word n-grams are **not** derivable from tsvector |

---

## 3. Family notes

### 3.1 Lexical / sparse

**BM25 is not weak cross-lingually; it is absent.** The failure is discontinuous, not gradual. BM25 sums over the intersection of query terms and document terms; across a script boundary that intersection is empty, so the document never enters the candidate set. The contrast is stark in the same literature: monolingually, tuned BM25 averages MRR@100 **0.333** on Mr. TyDi vs mDPR's **0.167**, beating the dense model in 10 of 11 languages ([Mr. TyDi](https://arxiv.org/abs/2108.08787)); cross-lingually on MKQA it scores Recall@100 **39.9** against **75.1** for BGE-M3 dense ([BGE-M3](https://arxiv.org/abs/2402.03216)).

> **Do not quote MIRACL BM25 numbers across papers.** [MIRACL's own paper](https://arxiv.org/abs/2210.09984) reports BM25 nDCG@10 of 0.458 (Hindi), 0.508 (Bengali), 0.494 (Telugu), 0.551 (Finnish) but 0.183 (French) and 0.180 (Chinese), averaging 0.393 with Anserini language-specific analyzers. [BGE-M3](https://arxiv.org/abs/2402.03216) reports 31.9 for BM25 on the same benchmark with a different implementation. Both are correct; quoting them together implies BM25 halved.

**Your lexical arm is weaker than BM25.** PostgreSQL states it plainly: "It is important to note that the ranking functions do not use any global information, so it is impossible to produce a fair normalization to 1% or 100% as sometimes desired" ([textsearch-controls](https://www.postgresql.org/docs/current/textsearch-controls.html)). `ts_rank_cd` is Clarke/Cormack/Tudhope cover density — no IDF, no corpus statistics. A match on a common term ranks comparably to a match on a rare discriminative one. Two consequences: the lexical arm's ordering is noisier than RRF assumes, and none of BM25's published strength transfers to it.

**Corrections to two widely-repeated beliefs about the schema:**

- *"A Hindi document in an English-config project is unreachable."* False on a normal UTF-8 database. The default parser's alphabetic test follows `lc_ctype`, so Devanagari tokenises as token type `word`, and the English Snowball stemmer finds no ASCII vowel region and returns it unchanged — the lexeme is stored, and a Hindi question run through `to_tsvector('english', q)` matches it. What is lost is Hindi *stemming*, not reachability. It becomes genuinely unreachable only under a `C` ctype. Verify in ten seconds: `SHOW lc_ctype;` and `SELECT to_tsvector('english','भारत की राजधानी');`
- *"One project = one stemmer is a Postgres limitation."* It is a limitation of writing a *literal* config into a generated column. PostgreSQL documents the alternative verbatim: "It is possible to set up more complex expression indexes wherein the configuration name is specified by another column… This would be useful, for example, if the document collection contained documents in different languages" ([textsearch-tables](https://www.postgresql.org/docs/current/textsearch-tables.html)). The trigger form is equally documented: "the second trigger argument is the name of another table column, which must be of type `regconfig`. This allows a per-row selection of configuration to be made" ([textsearch-features](https://www.postgresql.org/docs/current/textsearch-features.html)). **Gotcha:** the column must be *typed* `regconfig`. `lang_text::regconfig` is `provolatile => 's'` (search_path-dependent) and will be rejected by the generated-column immutability check — this is the most likely way to get a confusing "not immutable" error.

**Language coverage is a product surface, not a detail.** PostgreSQL 17 ships UTF-8 Snowball stemmers for exactly 28 languages (`src/backend/snowball/Makefile`): arabic, armenian, basque, catalan, danish, dutch, english, finnish, french, german, greek, **hindi**, hungarian, indonesian, irish, italian, lithuanian, nepali, norwegian, portuguese, romanian, russian, serbian, spanish, swedish, tamil, turkish, yiddish — plus `simple`. Czech, Polish, Estonian, Esperanto and Sesotho exist in [Snowball](https://snowballstem.org/algorithms/) but are not bundled. Bengali, Telugu, Urdu, Chinese, Japanese, Korean and Thai have no stemmer anywhere. And only **15** languages ship a stopword list — there is no `hindi.stop` and no `tamil.stop`, so Devanagari tokens under the `hindi` config get neither IDF (see above) nor stopword removal, and high-frequency Hindi function words will dominate cover-density ranking.

One useful bonus: `snowball_create.pl` sets `%ascii_languages = ('hindi' => 'english', 'russian' => 'english')`, so the bundled `hindi` config already routes `asciiword` tokens to `english_stem`. For a Hindi+English mixed corpus a single `hindi` regconfig may beat per-row regconfig at zero schema cost.

**Character n-grams are the right answer where word tokenisation fails.** On Khmer web search, character-n-gram BM25 reached R@10 **0.943** / nDCG@10 **0.876** / MRR@10 **0.906** vs multilingual-E5-small at **0.563 / 0.523 / 0.558** — the lexical arm beat the dense arm by ~0.35 nDCG, attributed to "ambiguous word boundaries", "weak support in multilingual embedding models", and "frequent mixed Khmer-English usage" ([KSE-Web](https://arxiv.org/abs/2608.21365)). **Caveat: 300 queries with silver relevance labels and only partial human verification, on a 3,000-document corpus** — not NeuCLIR-grade, and it is monolingual, not cross-lingual. The transferable finding is the hybrid row: BM25+dense scored **0.929 / 0.871**, i.e. no better than the n-gram arm alone. A hybrid can be no better than its better arm.

**Platform reality.** [PGroonga is a first-class Supabase extension](https://supabase.com/docs/guides/database/extensions/pgroonga) — "PGroonga offers a wider range of character support making it viable for a superset of languages supported by Postgres including Japanese, Chinese, etc." Its default `TokenBigram` bigrams non-ASCII and whitespace-splits ASCII, so English prose passes through as words. But be strict about what it buys: PGroonga's docs state "Score is 'how many keywords are included' (TF, Term Frequency) for now" and "Groonga supports customizing how to score. But PGroonga doesn't support yet it for now." **It solves tokenisation, not ranking** — TF-only, no IDF, weaker than `ts_rank_cd` on ranking while far better on segmentation. And like every lexical method it still returns zero for a Devanagari query against English text.

### 3.2 Learned sparse

The hard result: **learned sparse inherits BM25's vocabulary problem almost exactly**, because every LSR model scores as a dot product over one vocabulary. BGE-M3's own numbers are the cleanest statement of it ([BGE-M3](https://arxiv.org/abs/2402.03216), MKQA Recall@100, avg over 25 non-English query languages against an English corpus):

| | BM25 | M3-Sparse | mDPR | mContriever | OpenAI-3 | mE5-large | M3-Dense | M3-All |
|---|---|---|---|---|---|---|---|---|
| MKQA R@100 | 39.9 | **45.3** | 60.6 | 67.9 | 69.5 | 70.9 | **75.1** | 75.5 |

Dense+Sparse is 75.3 and All is 75.5 — **the sparse arm is worth +0.2 over dense alone cross-lingually**. On monolingual MIRACL the same arm is worth +1.1 nDCG@10, and on long documents (MLDR: BM25 53.6, M3-Sparse **62.2**, M3-Dense 52.5, Dense+Sparse 64.8) it is worth **+12.3** and beats dense outright. So: a learned sparse arm is a long-document play, not a cross-lingual one.

> **Version warning.** BGE-M3 v1 differs from v2/v3/v4 on baselines and dense scores (MIRACL M3-Dense reads 67.8 in v2/v3 and 69.2 in v4; M3-All 70.0 vs 71.5). Cite a version. The two figures that are stable across versions and load-bearing here are **BM25 31.9** and **M3-Sparse 53.9** on MIRACL — a learned sparse arm is worth ~1.7× a classical one *monolingually*.

**Naive multilingualisation makes it worse, not better.** [SPLADE-X](https://ceur-ws.org/Vol-3480/paper-06.pdf) on CLEF 2003 (MAP, de/fr/it/es):

| Run | de | fr | it | es |
|---|---|---|---|---|
| Mono BM25 (human-translated queries) | 0.296 | 0.406 | 0.387 | 0.431 |
| QMT BM25 (Marian MT queries) | 0.260 | 0.370 | 0.306 | 0.400 |
| **PSQ** | 0.322 | 0.363 | 0.307 | 0.347 |
| SPLADE-X zero-shot | 0.213 | 0.277 | 0.210 | 0.253 |
| SPLADE-X translate-train | 0.300 | 0.383 | 0.318 | 0.310 |
| SPLADE-X bilingual | 0.317 | 0.393 | 0.314 | 0.331 |
| **RRF(PSQ + SPLADE-X BI)** | **0.405\*** | **0.458\*** | **0.367\*** | **0.392\*** |

\* significant over PSQ. The paper's own conclusion: "none of the SPLADE-X variants consistently outperform the PSQ baseline." Zero-shot mBERT SPLADE loses ~34% to a statistical-translation baseline in German. What wins is **fusing a translation-based run with a learned-sparse run** — which is exactly the shape of the RRF layer you already have. (SPLADE-X's output vocabulary is 33,000 masked English sub-words, ~30% of mBERT's 110k — not 1%, a widely-repeated error. That matters because 33k is far above pgvector's 4,000-dim `halfvec` HNSW ceiling, so it can only live in `sparsevec`.)

**MILCO is the on-point research.** It projects queries *and* documents from any language into a shared **English lexical space**, so retrieval is always an English-on-English sparse dot product, and matches stay human-readable. Its `LexEcho` head exists because "uncommon entities are often lost when projected into English." Numbers ([MILCO](https://arxiv.org/abs/2510.00671), ICLR 2026): MIRACL avg nDCG@10 **72.3** (Hindi **64.4**), MLDR 74.4, MKQA R@100 **76.6** (vs M3-Sparse's 45.3 — a 69% relative gain, and it edges M3-Dense's 75.1), MTEB v2 66.83. The abstract's headline is that at ~30 active dimensions it beats Qwen3-Embed 0.6B's 1024 dense dims with 3× lower retrieval latency and a 10× smaller index.

> **Read the pruning curve, not just the abstract.** MILCO's Table 12 gives ~29.2 tokens/doc at **62.2** MIRACL nDCG@10 — a 10.1-point drop from 72.3. SOTA needs ~300 tokens (Table 11: 300 → 72.1, "achieves SOTA at 300 tokens, with only marginal gains beyond"). In pgvector terms that is 8·300+16 = **2,416 B/chunk** (≈5× smaller than your 3072-dim vector, not 48×) with 3.3× headroom under the 1,000-nnz HNSW cap — not 256 B at SOTA quality. Any GB/latency figures circulating for MILCO are **fabricated**: the paper contains no storage table and no latency table.

**The one Apache-2.0 multilingual LSR with released weights** is [`opensearch-neural-sparse-encoding-multilingual-v1`](https://huggingface.co/opensearch-project/opensearch-neural-sparse-encoding-multilingual-v1): 160M doc encoder, 105,879 output dims, avg 138 non-zeros (75 pruned), **inference-free query path** (tokenizer + weight lookup, no GPU at query time), MIRACL avg nDCG@10 **0.629** vs BM25's 0.305, Hindi 0.486. But every published number is MIRACL, which is **monolingual**. The card publishes no cross-lingual evaluation. Do not assume it crosses scripts.

**Vendor evidence.** Elastic ships ELSER as English-only — "This model is recommended for English language documents and queries" — and directs non-English users to a dense E5 model ([ELSER docs](https://www.elastic.co/docs/explore-analyze/machine-learning/nlp/ml-nlp-elser)). The largest commercial vendor of learned sparse retrieval independently arrived at the architecture you already have: let the embedder carry cross-lingual.

**Storage in pgvector**, verified from `src/sparsevec.h` and the [README](https://github.com/pgvector/pgvector): `SPARSEVEC_MAX_DIM = 1000000000`, `SPARSEVEC_MAX_NNZ = 16000`, storage `8·nnz + 16` bytes, **HNSW limited to 1,000 non-zero elements**, IVFFlat does not support `sparsevec` at all, operators `<->` `<#>` `<=>` `<+>`. Three attempts to raise the 1,000-nnz cap to 1,200 have failed to land (issue #749 open with maintainer pushback; PRs #868 and #994 closed unmerged). Comparative per-chunk storage:

| Representation | Bytes/chunk |
|---|---|
| MILCO @ 30 nnz | 256 |
| MILCO @ 300 nnz (SOTA operating point) | 2,416 |
| OpenSearch multilingual @ 138 nnz | 1,120 |
| BGE-M3 sparse @ ~300 unique tokens | 2,416 |
| **`vector(3072)` — current** | **12,296** |

**No published recall/latency/build-time benchmark for HNSW-over-`sparsevec` at learned-sparse scale was found.** HNSW is approximate graph search, not the WAND/MaxScore dynamic pruning that the LSR literature assumes, so published effectiveness numbers may not transfer. This is testable in an afternoon on your own data and should be tested *before* choosing a model.

### 3.3 Dense

The load-bearing distinction is not "multilingual vs monolingual" but [LAReQA](https://arxiv.org/abs/2004.05484)'s **strong vs weak alignment**. Strong alignment requires semantically related cross-language pairs to be closer than unrelated same-language pairs; weak alignment only requires working within each language. The paper's warning is the one that matters for vendor selection: "the embedding baseline that performs the best on LAReQA falls short of competing baselines on zero-shot variants of our task that only target weak alignment." A leaderboard win on a monolingual multilingual benchmark predicts nothing about Hindi→English.

**The incumbent's cross-lingual numbers.** XTREME-UP MRR@10 (query in an under-represented, largely Indic language → English passage), from the [Gemini Embedding report](https://arxiv.org/abs/2503.07891):

| Model | Avg (20 langs) | hi | mr | ur | gu | ml | kn | as | pa | or | ta |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **text-embedding-3-large** | **18.8** | 40.4 | 25.5 | 22.0 | 14.6 | 15.6 | 17.1 | 18.2 | 11.3 | 8.3 | 6.0 |
| mE5-large-instruct | 18.7 | 30.6 | — | — | — | 8.6 | — | — | — | — | — |
| Gecko i18n | 35.0 | — | — | — | — | — | — | — | — | — | — |
| voyage-3-large | 39.2 | 54.3 | 45.5 | 45.6 | 46.7 | 45.3 | 41.5 | 34.3 | 48.4 | 32.3 | 36.0 |
| **Gemini Embedding** | **64.3** | 69.1 | 68.8 | 64.8 | 70.3 | 70.8 | 69.5 | 69.2 | 69.5 | 65.8 | 68.6 |

Corroborating: XOR-Retrieve Recall@5kt 68.76 (3-large) vs 90.42 (Gemini) vs 65.67 (Gecko); MIRACL nDCG@10 avg 54.9 (3-large) vs 66.6 (mE5-large) vs ~69 (BGE-M3 dense); MTEB(Multilingual) Mean(Task) 58.92 vs 68.32, with Gemini also ahead on MTEB(Eng v2) 73.30 vs 66.43 — it is not trading English away. Gemini's weakest languages are Bodo 25.7 and Manipuri 44.4.

Note the asymmetry this creates: since your lexical arm returns zero rows on non-English queries, **RRF is degenerate and the fused order IS the dense order**. The entire non-English experience is one model scoring 18.8 average on the exact benchmark shape of the motivating case.

**Two cheap alternatives to swapping the model.** Both rest on the same finding — that cross-lingual signal is present in multilingual spaces and being *masked* rather than missing.

- [LIR](https://arxiv.org/abs/2109.04727): the top principal components encode language identity; factoring them out post-hoc "yields almost 100% relative improvement in MAP for weak-alignment models" on LAReQA. Model-agnostic, no retraining, pure linear algebra. Validated on mBERT-class models, **not on commercial API embedders**.
- [SHIFT](https://arxiv.org/abs/2606.18801) (EMNLP 2026 Findings): estimate a per-(model, language) offset from parallel pairs and subtract it from document embeddings at index time. With multilingual-e5-large, nDCG@20/Recall@20: Belebele 0.816→0.910 / 0.812→0.907; MLQA 0.494→0.649 / 0.523→0.721; XQuAD 0.855→0.944 / 0.900→0.963; MultiEuP-v2 0.367→0.442 / 0.302→0.375. **But gains are strongly model-dependent**: embeddinggemma-300m moves 0.758→0.765 average nDCG, and bge-m3 gains ~0.3% relative. There is no published number for `text-embedding-3-large`.
- [mSimCSE](https://arxiv.org/abs/2211.06127) independently supports the premise: "contrastive learning on English data can surprisingly learn high-quality universal cross-lingual sentence embeddings without any parallel data."

**The counterweight to "just use a better embedder."** [MLAIRE](https://arxiv.org/abs/2605.07249) evaluated 31 retrievers and found standard metrics obscure a language-preference effect: "semantically strong retrievers may return correct content in a non-query language, while retrievers with stronger query-language preference may retrieve less semantically relevant passages." [LANGSAE](https://arxiv.org/abs/2601.04768) states the mechanism: language identity "can inflate similarity for same-language pairs and crowd out relevant evidence written in other languages." A single nDCG number cannot tell you whether your embedder found the right *content* or the right *language*. Scale of the in-language gap: for Amharic, the strongest zero-shot multilingual retriever underperforms the strongest **monolingual** retriever by 23% relative MRR@10 ([arXiv 2605.24556](https://arxiv.org/abs/2605.24556)).

**Matryoshka is orthogonal and free.** Truncation preserves whatever alignment the full vector had; it neither creates nor destroys it. jina-v3's measured retrieval nDCG@10 by dimension — 1024→63.35, 512→63.16, 256→62.72, 128→61.64, 64→58.54, 32→52.54 ([jina-v3](https://arxiv.org/abs/2409.10173)) — shows 1024→256 costs 0.63 points. OpenAI: "a text-embedding-3-large embedding can be shortened to a size of 256 while still outperforming an unshortened text-embedding-ada-002 embedding with a size of 1536," with the caveat that manual truncation requires L2 renormalisation. Emitting 1024/1536 instead of 3072 gets you a native `vector` HNSW index instead of a `halfvec` workaround, 2–3× less storage, and faster probes.

### 3.4 Multi-vector

[ColBERT-X](https://arxiv.org/abs/2201.08471) MAP, title queries — per-token embeddings with MaxSim, XLM-R backbone:

| Collection | BM25 human-translated Q | BM25 MT Q | ColBERT-X ZS | ColBERT-X TT |
|---|---|---|---|---|
| HC4 Chinese | 0.301 | 0.237 | **0.450** | 0.408 |
| HC4 Persian | 0.276 | 0.211 | 0.297 | **0.310** |
| CLEF German | 0.304 | 0.263 | 0.328 | **0.397** |
| CLEF French | 0.403 | 0.387 | 0.382 | **0.422** |
| CLEF Italian | **0.350** | 0.275 | 0.272 | 0.339 |

Late interaction beats *human* query translation on the script-distant pair and narrows or reverses on European languages — **cross-lingual gains are largest exactly where scripts diverge**. [Translate-Distill](https://arxiv.org/abs/2401.04810) (ECIR 2024) is the strongest published training regime; within-collection on NeuCLIR 2022 nDCG@20: BM25+RM3 with document translation 0.340/0.355/0.292 (zh/fa/ru) → ColBERT-X translate-train 0.441/0.438/0.470 → Translate-Distill 0.492/0.484/0.522.

**The finding to keep, not the method.** The [MLIR follow-up](https://arxiv.org/abs/2209.01335) reports that "98% of that MAP score can be achieved with an 84% reduction in indexing time by using a pretrained XLM-R multilingual language model to index documents in their native language, and that 2% difference in effectiveness is not statistically significant" — 0.05 s/doc native vs 0.32 s/doc via neural MT. That is direct published support for carrying cross-lingual on the embedder rather than on a translated index. It is a statement about a *dense* index, though; it says nothing about a dead lexical one.

MaxSim is not available in pgvector: no multi-vector abstraction, no MaxSim operator. Emulating it with a token-vector table and `GROUP BY max()` explodes row counts (~100–300 rows per chunk) and makes HNSW near-useless. VectorChord ships a real `@#` MaxSim operator over `vector(n)[]`, but VectorChord is not in Supabase's build.

### 3.5 Query side

**Query translation is the cheapest repair and the weakest of the translation family.** Queries are short, so one mistranslated term corrupts a large fraction of the query. On NeuCLIR 2022 title queries (nDCG@20, [Lin et al.](https://arxiv.org/abs/2304.01019)): query-translation BM25 scores 0.1830 (zh) / 0.3331 (fa) / 0.3564 (ru) while document-translation BM25 scores 0.3705 / 0.3665 / 0.3693. **Query translation loses half its effectiveness on the script-distant pair** and barely degrades on Persian and Russian. The greater the linguistic distance, the worse it does relative to document translation.

Averaged over 8 collections and 456 topics ([PSQ reproduction](https://arxiv.org/abs/2404.18797)):

| Method | R@100 | MAP |
|---|---|---|
| QT-BM25 (Google Translate) | 0.477 | 0.267 |
| DT-BM25 (Sockeye) | 0.546 | 0.302 |
| **PSQ-HMM** | **0.585** | **0.332** |

PSQ is statistically significantly better than both, microaveraged over 456 topics. Per-language R@100: fr 0.808, it 0.657, de 0.677, es 0.620, NTCIR-zh 0.523, NeuCLIR fa 0.488, ru 0.467, zh 0.456.

**The single most important query-side result for this stack is 26 years old.** [Xu & Weischedel (EMNLP/VLC 2000)](https://aclanthology.org/W00-1312/) isolated exactly the choice you are about to make — average precision, long queries:

| Translation strategy | TREC5C | TREC6C | TREC4S |
|---|---|---|---|
| Single-best substitution | 0.0391 | 0.0941 | 0.0935 |
| Unweighted synonym-set OR | 0.2306 | 0.3842 | 0.1594 |
| Probability-weighted (HMM) | 0.2735 | 0.4206 | 0.1729 |

Substitution → unweighted OR is a **5.9×** jump on TREC5C-long; weighting adds a further ~19%. Full CLIR reached 67–84% of monolingual (avg ~76%). And the disambiguation result is the punchline: native speakers manually picking the single correct translation for every term improved results by only +17% (TREC5C-medium), −1% (TREC6C-medium), +4% (TREC4S), and the one positive was not significant at p=0.05. Their explanation: "the word 'flood' (as in 'flood control') has 4 valid Chinese translations. Using all of them achieves the desirable effect of query expansion."

**This is the trap an LLM-translate-the-query implementation walks straight into**, because an LLM returns one fluent translation, not a weighted alternative set. Keeping ambiguity is not a compromise; it is the mechanism.

**Cross-lingual query expansion is real but thinly published.** [Macmillan-Scott et al. (Alan Turing Institute)](https://arxiv.org/abs/2511.19325) is the closest work: translate → have a multilingual LLM write a corpus-language pseudo-document → retrieve with the translated query + pseudo-doc. CLIRMatrix Hit@10 / Recall@50 / MRR: original query 69.35 / 10.09 / 41.35 → Gemma 3 12B zero-shot **85.12 / 13.24 / 62.03**; Aya Expanse 8B zero-shot 84.06 / 13.32 / 60.78. mMARCO Recall@10 / R@50 / MRR: 38.55 / 79.27 / 15.39 → Gemma 3 12B few-shot 41.70 / 80.77 / 20.26. Overall gains "up to approximately 15% on CLIRMatrix and 10% on mMARCO." Three operational details worth copying: **the largest recall improvements are observed for English documents** (your corpus is the best-case target); zero-shot wins for short title-like queries and few-shot for longer ones (Gemma 3 12B few-shot on CLIRMatrix is *worse* than zero-shot, 79.59); and CoT/RaR prompting emits meta-text — "To answer this query, I will provide information about…" — which "adversely affects BM25 retrieval." Strip meta-text before building the tsquery.

**HyDE cross-lingually is unpublished territory, but the recipe is one token away.** [HyDE's](https://arxiv.org/abs/2212.10496) own Mr.TyDi prompt is literally "Please write a passage in Swahili/Korean/Japanese/Bengali to answer the question in detail" — the output language is named explicitly in the instruction. Its Mr.TyDi evaluation is *monolingual non-English*, not cross-lingual, and the Turing paper explicitly lists zero-shot cross-lingual generation as future work. Two caveats before betting on it: a leakage audit found HyDE's gains concentrated on claims whose generated documents contained sentences entailed by gold evidence ([arXiv 2504.14175](https://arxiv.org/abs/2504.14175)), so expect smaller gains on a private customer corpus; and a deployment study measured HyDE at a **25–40% increase in response time** versus plain RAG ([arXiv 2506.21568](https://arxiv.org/abs/2506.21568)).

**Do not concatenate a pseudo-document into a tsquery.** `to_tsquery` will not accept prose at all (a 300-word passage raises a syntax error), and `plainto_tsquery` ANDs every token, which matches essentially nothing. query2doc's fix — repeat the query n=5 times to rebalance term weights — does not work in Postgres: `ts_rank` calls `SortAndUniqItems()` on the query operands, so repeating a lexeme is a literal no-op; `ts_rank_cd` does not de-duplicate, but that is an undocumented implementation detail with no defined weighting semantics. [Jedidi & Lin](https://arxiv.org/abs/2511.19349) independently find that running the pseudo-document through Rocchio to *extract and weight* expansion terms substantially beats concatenation. In Postgres: extract the top ~15–20 content terms, strip meta-text, keep the translated question's own terms, and let RRF do the weighting.

**Embedding interpolation is measured, and the measurement says skip it for an English corpus.** [Zhu et al. (ACL 2026)](https://arxiv.org/abs/2606.13537) sweep λ over the convex combination of a query embedding and its translation's embedding across 105 language-pair settings on BGE-M3/mMARCO. Optimal mixing beats the best monolingual endpoint in 88/105 (83.8%) settings overall — but split by whether English is in the index: **without English, mean Δ = +0.95 and every group is positive; with English in the index, mean Δ = −0.04 and λ\* = 0 in 8/13 cases.** The paper states the asymmetry directly: "mixing a non-English query with English improves performance for non-English document retrieval, but mixing English with another language does not help retrieve English documents." One nuance worth a cheap test: in 11 English-inclusive settings ΔnDCG@10 < 0 but ΔRecall@10 > 0 — mixing surfaced more relevant passages while reordering the top badly, which for RAG may still be useful. A zero-compute lookup table picking λ from (L1, L2, doc_lang) hit the oracle ratio in 200/273 held-out settings (mean 29.35 vs oracle 29.40).

**Hinglish.** [Aksharantar](https://arxiv.org/abs/2205.03018) provides 26M transliteration pairs across 21 Indic languages and 12 scripts and releases IndicXlit (~11M params, MIT), improving accuracy by 15% on the Dakshina testset. Per-language Dakshina Top-1: hin **60.56**, kan 77.18, tel 73.38, tam 68.10, ben 55.49, urd 42.12. **But direction matters and transliteration is probably the wrong tool here**: converting a romanised Hindi query into Devanagari makes it *more* distant from an English index, not less. Transliteration pays off only where the corpus itself contains romanised or native forms (names, brands, loanwords, code-mixed source documents). What you actually need is romanised-Hindi → English, and a single LLM call does that better than transliterate-then-translate, which compounds a ~60%-word-accuracy step into an MT step. Independent benchmarking finds GPT-family models "generally outperform other LLMs and IndicXlit for most instances" ([arXiv 2505.19851](https://arxiv.org/abs/2505.19851)).

### 3.6 Document side

**Document translation into a pivot is the strongest classical repair, and its economics invert your case.** [CLIRudit](https://arxiv.org/abs/2504.16264) (English queries, 16,389 French documents) measures exactly the failure and its fix:

| System | nDCG@10 | R@100 |
|---|---|---|
| BM25, no translation | 0.196 | 0.416 |
| BM25 + query translation | 0.417 | 0.706 |
| **BM25 + document translation** | **0.579** | **0.832** |
| BGE-M3 dense, none → doc-translated | 0.492 → 0.540 | 0.811 → 0.840 |
| mGTE dense, none → doc-translated | 0.484 → 0.504 | 0.820 → 0.837 |
| NV-Embed-v2, none → doc-translated | 0.616 → 0.621 | 0.895 → 0.892 |

Document translation is worth **+0.162 nDCG@10 on the sparse side** and essentially nothing on the dense side — the embedder was already doing the work. NAVER reached the same verdict independently: "much to our dismay, document translation worked the best out of all tested strategies" ([arXiv 2303.11171](https://arxiv.org/abs/2303.11171)).

**But your corpus is already English.** The "document translation" direction is satisfied by construction; translating an English corpus into English is a no-op. Your analogue is either (a) translating the corpus into each *expected query* language — N parallel indexes, wrong economics for a general-purpose product — or (b) doc2query into query languages, which is the same idea at a fraction of the cost.

**T-SPLADE is the strongest published instance of the pivot idea** and the reason it is worth understanding even though you cannot copy it. NAVER translated all 16 MIRACL corpora with NLLB-200 and fine-tuned 16 per-corpus SPLADE++ models ([Lassance](https://arxiv.org/abs/2302.14723)), winning both MIRACL 2023 tracks:

| System | nDCG@10 | R@20 | R@100 |
|---|---|---|---|
| BM25 | 39.3 | 60.9% | 78.7% |
| mDPR | 41.5 | 62.8% | 78.8% |
| T-SPLADE | 54.5 | 71.3% | 83.3% |
| BM25 + mDPR | 57.8 | 83.0% | 93.7% |
| **+ T-SPLADE** | **70.0** | **90.4%** | **97.2%** |

Yoruba: BM25 40.6 → T-SPLADE **82.7**; "what really helped us was translating to English and then searching in English." Honest caveats the paper states: only the **first 128 tokens** of each document were translated; the distilled NLLB caused "a very sharp drop in performance" on corpora >4M docs; and NLLB emitted junk ("I don't know it", "I won't translate this") that had to be filtered manually. Note that T-SPLADE is sixteen *learned* per-language sparse models on top of the translated corpus, and the paper never evaluates plain BM25 over the translated corpus — the +12.2 does not transfer to an English tsvector on its own.

**doc2query is the most schema-compatible technique in this catalogue and the natural place to inject cross-lingual vocabulary.** MS MARCO dev MRR@10: BM25 0.184 → docTTTTTquery 0.277, a **+50% relative gain with no change to the retriever** ([docTTTTTquery](https://cs.uwaterloo.ca/~jimmylin/publications/Nogueira_Lin_2019_docTTTTTquery-v2.pdf); the earlier [doc2query](https://arxiv.org/abs/1904.08375) is 0.218). Nothing in the mechanism requires generated queries to be in the document's language — generating Hindi and Hinglish pseudo-queries for an English chunk would put Devanagari and romanised lexemes into the sparse index, which is **the only way an English corpus can ever produce a non-zero lexical row for a Hindi question**. No published cross-lingual doc2query evaluation exists; treat this as an extrapolation with strong monolingual backing.

Three implementation facts:
- **Filter the generations.** [doc2query--](https://arxiv.org/abs/2301.03266): "using a relevance model to remove poor-quality queries can improve the retrieval effectiveness of Doc2Query by up to 16%, while simultaneously reducing mean query execution time by 23% and cutting the index size by 33%." This applies to any ingest-time LLM output, translations included. Counter-evidence worth knowing: the filter "does not enhance retrieval quality when used with DeepImpact" ([DeeperImpact](https://arxiv.org/abs/2405.17093)) — it helps BM25-style scoring, not every downstream model.
- **Cheap expansion exists.** [SPRINT](https://arxiv.org/abs/2307.10488) finds docT5query "140x more computationally expensive than TILDE" while the two "perform comparably" for sparse models; docT5query wins clearly only for plain BM25, because it repeats keywords.
- **Weight the expansion down, separately.** Append into `content` for zero migration; if you want a separate column, use `setweight(to_tsvector('english', content),'A') || setweight(to_tsvector('english', expansion),'B')` inside the generated column (both `setweight` and `||` are IMMUTABLE). `ts_rank_cd`'s weights array is ordered `{D,C,B,A}`, defaulting `{0.1,0.2,0.4,1.0}`, so B-vs-A already down-weights expansion 0.4-to-1.0. And note doc2query's +50% was measured under BM25, whose length saturation limits the damage from repeated terms; `ts_rank_cd` at default normalization applies **no** length normalization at all, so expanded chunks will be systematically over-ranked unless you pass a length flag.

**Chunk-level LID is the enabling primitive, and it belongs on the document side only.** [GlotLID-M](https://arxiv.org/abs/2310.16248) (1,665 languages) on FLORES-200 F1/FPR: **0.978/0.0051** vs NLLB 0.947, OpenLID 0.923, FT176 0.775, CLD3 0.753; on the harder UDHR: **0.868** vs OpenLID 0.645, NLLB 0.641, FT176 0.566, CLD3 0.544. [OpenLID](https://aclanthology.org/2023.acl-short.75) reports macro-F1 0.93 / FPR 0.033% over 201 languages. CLD3 is archived read-only since 2024-06-15. Use one of the first two at ingest, store a confidence, fall back to `simple` when uncertain. **Do not put LID on the query path**: Elastic's guidance is blunt — "search queries tend to be short. Like, really short!" (a 2001 Excite study measured 2.4 terms average) and "many language identification algorithms work best with more than 50 characters."

**HyPE inverts HyDE's cost curve and is the most interesting untested idea here.** Generate hypothetical *questions* per chunk at ingest, embed those, point them at the chunk; retrieval becomes question-to-question matching with **zero query-time LLM call**. Across six datasets it improves retrieval context precision by up to 42 percentage points and claim recall by up to 45 ([HyPE, IEEE Access](https://arxiv.org/abs/2607.29402)), "while remaining compatible with re-ranking, multi-vector retrieval, query decomposition." The extrapolation: generate the hypothetical questions in *multiple languages*, and a Hindi question matches a Hindi hypothetical question that points at an English chunk, with no runtime translation. **The paper is monolingual throughout; this is inference, not a result.** And the lexical half runs straight into the one-regconfig constraint.

### 3.7 Fusion

RRF's selling point is that it "combines ranks without regard to the arbitrary scores returned by particular ranking methods" ([Cormack et al.](http://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)). That indifference buys robustness against uncalibrated scores and costs you any way to say "this arm is garbage."

**Stop tuning k.** Cormack's own pilot sweep (MAP, TREC 351–400, fusing 30 Wumpus configs): k=0 .2072, 10 .2123, 20 .2134, 30 .2139, 40 .2138, 50 .2144, **60 .2145**, 70 .2146, **80 .2147 (max)**, 90 .2145, 100 .2142, 500 .2098. Across k∈[20,100] the spread is 0.6%. The paper: k=60 "was near-optimal, but the choice was not critical." k is not the lever.

**The three regimes your fusion is actually in:**

1. **Empty lexical arm** (the measured 28/28) — harmless. Fused order ≡ dense order. Make this explicit and loggable rather than accidental.
2. **Disjoint non-empty lists** — equal-weight RRF is arithmetically identical to **round-robin interleaving**: doc unique to A at rank rₐ beats doc unique to B at rank r_b iff rₐ < r_b, ties at equal rank. Round-robin is the worst-scoring merge in the CLEF record: 0.221 (64.0%) / 0.219 (**65.0% — this cell does not reconcile against the stated optimum; UNVERIFIED**) of theoretical optimum, vs 0.240/0.245 (69.6%/73.6%) for min-max normalised merging and 0.296/0.288 (85.8%/86.5%) for 2-step RSV ([Martínez-Santiago et al., IR Journal 2006](https://link.springer.com/content/pdf/10.1007/s10791-005-5722-4.pdf)).
3. **Short noisy lexical arm** — the real bug. Rank-1 junk scores 1/61 = 0.016393, tying the dense arm's best result and beating its rank-2 (1/62 = 0.016129). This is the documented "weakest link phenomenon, where a weak path can substantially degrade overall accuracy, highlighting the need for path-wise quality assessment before fusion," measured across 11 real-world datasets ([arXiv 2508.01405](https://arxiv.org/abs/2508.01405)).

**Weighting works but is not free.** [MMMORRF (SIGIR 2025)](https://arxiv.org/abs/2503.20698): on MultiVENT 2.0 unweighted RRF gave 0.562 nDCG@10, "only a marginal improvement without statistical significance" over single arms (text 0.427, vision 0.375); weighted WRRF reached 0.586, "a statistically significant 4.2% improvement." **On TVR the weighting lost**: R@1 0.201 (WRRF) vs 0.232 (RRF), R@10 0.540 vs 0.537. The authors call their weighting heuristic "ad hoc." Weights must be validated per corpus.

Note that [Elasticsearch's RRF](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion) has no weights at all — "Each child retriever carries an equal weight as part of the RRF formula" — while [Supabase's reference hybrid function](https://supabase.com/docs/guides/ai/hybrid-search) exposes `full_text_weight` and `semantic_weight` (defaults 1, `rrf_k` 50) and over-fetches `least(match_count,30)*2` per arm before fusing. [ParadeDB's documented RRF](https://www.paradedb.com/docs/documentation/tokenizers/multiple-per-field.md) ships **asymmetric defaults**: k=60, text 1.0, vector 0.7.

**Score fusion beats RRF consistently and modestly.** [Bruch, Gai & Ingber (TOIS 2023)](https://ar5iv.labs.arxiv.org/html/2210.11934), NDCG@1000, TM2C2 = convex combination on *theoretical* min-max normalisation:

| Dataset | Lexical | Semantic | RRF(60) | TM2C2 | Oracle per-query α |
|---|---|---|---|---|---|
| MS MARCO | 0.309 | 0.441 | 0.425 | **0.454** (+6.8%) | 0.547 |
| NQ | 0.382 | 0.505 | 0.514 | **0.542** (+5.4%) | 0.637 |
| Quora | 0.800 | 0.889 | 0.877 | **0.901** (+2.7%) | 0.936 |
| NFCorpus (zero-shot) | — | — | 0.312 | **0.327** (+4.8%) | — |
| HotpotQA (zero-shot) | — | — | 0.675 | **0.699** (+3.6%) | — |
| FEVER (zero-shot) | — | — | 0.721 | **0.744** (+3.2%) | — |

"TM2C2 significantly outperforms rrf on all datasets in terms of NDCG." Their argument against RRF is precise: "because rrf is a function of ranks, it disregards the distribution of scores and, as such, discards useful information." They also show the mirror failure with *unnormalised* scores: adding raw lexical scores to a strong in-domain semantic ranking "leads to a severe degradation of ranking quality" because "adding the lexical scores which are on a very different scale distorts the rankings," concluding "we require that f_Hybrid be bounded."

> **Score fusion is MORE fragile cross-lingually than RRF, not less.** Empirical min-max forces every arm's best hit to exactly 1.0 regardless of quality — it manufactures false confidence out of a dead arm. Theoretical min-max at least anchors the floor. And `ts_rank_cd` has **no theoretical maximum** (it is an unnormalised cover-density heuristic), so faithful TM2C2 is not implementable on the lexical half; the closest legal construction is `ts_rank` with normalization bit 32, which maps into [0,1) by construction. Also note pgvector exposes cosine *distance* via `<=>` in [0,2], so the −1 infimum applies to `1 - distance`, and `MAX(sim) OVER ()` normalises over the ANN candidate set, which moves with your top-k and with the exact-scan fallback threshold.

**Empirical min-max is nonetheless the industry default.** Weaviate made `relativeScoreFusion` the default in v1.24, reporting "a ~6% improvement in recall over the rankedFusion method" on FIQA, and notes that autocut "requires Relative Score Fusion method because it uses actual similarity scores to detect cutoff points" ([Weaviate docs](https://docs.weaviate.io/weaviate/search/hybrid)). The transferable idea is the second half: thresholding needs real scores, which is why carrying similarity on the rows is right.

**Two-run fusion is the shape your architecture is already in.** [Exp4Fuse](https://arxiv.org/abs/2506.04760) runs the *same* retriever twice — once on the original query, once on an LLM-expanded query — and fuses with a modified RRF, `(w_i + n/10)·Σ 1/(k+r_i)` at k=60, where n∈{1,2} is the number of lists a document appears in. BM25 nDCG@10 50.6 (DL19) / 48.0 (DL20) → **62.0 / 56.6**; R@1k 75.0/78.6 → 87.0/87.3; MS MARCO MRR@10 18.4 → 20.7. SPLADE++ 73.1 → 77.6 on DL19. It beats query2doc and Contriever-FT+HyDE. **English-only evaluation**, but architecturally it is the safe way to add translation: you never *replace* the original query, so a bad translation dilutes rather than destroys.

**And two-run fusion beats vector interpolation.** Interpolation searches one point in the space and was measured worthless on English indices; two-run fusion searches two points and can retrieve chunks neither single vector ranks highly (e.g. chunks containing untranslated proper nouns), degrading gracefully because a garbage translation contributes a bad list rather than a corrupted vector. The cost difference is one ANN probe. No paper measures this exact configuration; it is supported by composition ([Exp4Fuse](https://arxiv.org/abs/2506.04760) + [synthetic query variant fusion](https://arxiv.org/abs/2411.03881) + [the interpolation endpoint analysis](https://arxiv.org/abs/2606.13537)).

**The classical merging literature's best answer is not a normaliser at all.** [2-step RSV](https://link.springer.com/content/pdf/10.1007/s10791-005-5722-4.pdf) groups a term and its translations into one shared document frequency, then re-indexes only the retrieved documents against that shared vocabulary and rescores — "the new 2-step RSV calculus does not need to download retrieved documents" and "only operates on a small" set. It reaches **~86% of theoretical optimum** where every traditional method sits at 64–76%, because it eliminates score incomparability rather than patching it. In Postgres you have both ingredients (an LLM translation of the question; one physical chunks table) and lack one: a second-language lexeme stream to pool document frequencies with. `ts_stat` gives you the df side.

**What the theory says about when to fuse at all.** [Vogt & Cottrell (IR Journal 1999)](https://link.springer.com/content/pdf/10.1023/A:1009980820262.pdf) derive the optimal linear-combination weight as a function of both systems' performance "as mediated by ratios of the number of documents in the overlaps," and give three conditions under which linear combination is warranted — including that both systems return **similar sets of relevant documents**, which is provably violated by your 28 zero-row questions. Their empirical warning is the one to internalise: of 91,500 pair/query triples, 80,324 (88%) improved on the *training* set over both components, but only 32,493 of those (40%) also improved on *test*, with an average change of **−14%** relative to the better component. Any fusion change here must be validated on held-out queries, not tuned on the 28. (Their scope note matters too: "this conclusion applies specifically to the LC model — other fusion models would presumably exploit other effects," and your fusion is rank-only RRF.)

### 3.8 Rerank

Reranking is the only cross-lingual repair here that needs **zero schema change** — it is application code between fusion and generation. It also has a hard ceiling and a language bias that runs against you in mixed corpora.

**The ceiling is first-stage recall, and there is a number for your exact embedder.** On MKQA cross-lingual R@100, `text-embedding-3-large` scores **69.5** ([BGE-M3](https://arxiv.org/abs/2402.03216)). Roughly 30% of cross-lingual questions have no relevant passage anywhere in the top 100, and no reranker recovers one of them. Oracle reranking ceilings confirm the same shape: on CIRAL, an M3 first stage gives an oracle of 0.754 nDCG@20 vs 0.646 for BM25-DT, and a +0.015 MAP retrieval gain yields only +0.024–0.05 after reranking ([arXiv 2509.14749](https://arxiv.org/abs/2509.14749)).

**Put both sides in the same language before scoring.** This is the cheapest reranking win and you already produce the string. On CIRAL (nDCG@20, top-100 off BM25-DT, [Adeyemi et al., ACL 2024](https://arxiv.org/html/2312.16159v1)) — Hausa / Somali / Swahili / Yoruba:

| Run | ha | so | sw | yo |
|---|---|---|---|---|
| BM25-DT first stage | 0.2142 | 0.2517 | 0.2260 | 0.4169 |
| RankGPT-4 cross-lingual | 0.3577 | 0.3268 | 0.2991 | 0.4738 |
| **RankGPT-4 in English** | **0.3967** | **0.3812** | **0.3694** | **0.5355** |
| RankZephyr cross-lingual | 0.2741 | 0.2996 | 0.2881 | 0.4218 |
| **RankZephyr in English** | **0.3686** | **0.3622** | **0.3601** | **0.4887** |

+10% to +34% relative, same model, just by collapsing both sides into English. Corroborated independently: "Without MT, current state-of-the-art rerankers fall severely short when directly applied in CLIR" — RankZephyr 0.365 native vs 0.477 document-translated — with the caveat that "the benefits of translation diminishes with stronger reranking models" ([arXiv 2509.14749](https://arxiv.org/abs/2509.14749)). Note the direction in these papers is English-query/foreign-documents; the English condition is reached by *document* translation, and translating toward the low-resource language mostly hurts. Your case (Hindi query, English corpus) is the collapse-into-English case, so it lands favourably — but say that explicitly rather than assuming symmetry.

**Model choice: the reranker's own multilinguality is what determines cross-lingual repair, not depth or first stage.** Same pool, same top-20, swapping an English-trained listwise reranker for a multilingual reasoning one moves NeuCLIR nDCG@10 from 0.281 to 0.440 ([Rank-K](https://arxiv.org/html/2505.14432v1); the widely-quoted "0.291 → 0.440" is the Persian-only column). On MMTEB-R (multilingual reranking) at comparable size, [Qwen3-Reranker-0.6B](https://arxiv.org/html/2506.05176v1) scores **66.36** vs bge-reranker-v2-m3's 58.36 and jina-v2-multilingual's 63.73, with FollowIR (instruction following) **+5.41** vs −0.01 and −0.68. Apache-2.0, 32k context, 100+ languages, and an instruction slot you can literally use to say "the document may be in a different language than the question."

**Rerankers are measurably language-biased.** [LAURA](https://arxiv.org/abs/2604.20199) measured bge-reranker-v2-m3 on MKQA across 13 languages: "more than 70% of the top-5 retrieved documents, averaged across 13 languages, originate from English and the query language alone," sitting 12.9–20 points below an oracle that picks answer-critical evidence (Llama-8B + BGE 48.9% vs 63.6% oracle). LAURA's fairness realignment gained +6.86 PEER on BGE but only +1.14 on Qwen3 — Qwen3 is already close to fair. **For an English-only corpus the English half of that bias is harmless and the query-language half is inert**, so language-balance reranking solves a problem you do not have — but it becomes live the moment a project holds mixed-language documents. And the opposite exists: [LAMAR](https://arxiv.org/abs/2607.22042) is explicitly trained to *prefer the query's language*, which would penalise every document you have. Test any candidate reranker for that behaviour before adopting it.

**Depth: 25–50, not 300.** [Drowning in Documents](https://arxiv.org/abs/2411.11767) (BM25 / voyage-2 / text-embedding-3-large first stages; jina-v2-multilingual, bge-reranker-v2-m3, cohere-rerank-english-v3.0, voyage rerankers, gpt-4o-mini listwise) found rerankers improved Recall@10 for *at least one* K in 85.0% (academic) / 88.9% (enterprise) of experiments, but "Helps & Never Hurts" held in only **23.3% / 22.2%**, and scaling K produced Recall@10 *worse* than retrieval alone **53.3% / 44.4%** of the time. All datasets are English; this is evidence about scaling K, not about language. The instinct "the cross-lingual miss is at rank 300, so retrieve 300" is where rerankers start preferring irrelevant documents.

**Cost.** LLM listwise reranking is out of budget for a streaming UX: RankGPT at top-100 costs $0.040 and ~11 s/query (gpt-3.5-turbo) or $0.596 and ~32 s (GPT-4); restricted to top-30, GPT-4 is $0.098. Independently, "Reranking 50 documents can take up to 1 minute using GPT-4 and/or Llama-70B on an H100 GPU" ([arXiv 2403.10407](https://arxiv.org/abs/2403.10407)). Hosted cross-encoder APIs are one network hop. Watch Cohere's billing rule: a search unit is "one query with up to 100 documents to be ranked," and documents over 500 tokens are split into chunks that each count — so k=50 with 800-token chunks can bill as 100+ documents.

**A CPU-only fallback exists but is weak on long documents.** `mmarco-mMiniLMv2-L12` (100M) beats GPT-4 on Mr.TyDi Bengali (65.98 vs 64.37), Telugu (68.92 vs 62.22) and Thai (68.36 vs 63.41) ([RankGPT](https://arxiv.org/html/2304.09542v3)) — a 100M multilingual cross-encoder is not a toy. But on MLDR recall@10 it scores **28.91** against jina-v2's 68.95 and BGE's 59.73, and MLDR is the closer analogue to chunked documents.

### 3.9 Routing

**Your weak-similarity gate has a name and it is the weakest predictor in its family.** It is Max Score: "the higher the maximum score, the more confident the retrieval system is that it has found a document that matches well the query" ([arXiv 2310.11405](https://ar5iv.labs.arxiv.org/html/2310.11405)). Kendall τ vs nDCG@10:

| Predictor | DL'19 BM25 | DL'19 ANCE | DL'19 TCT-ColBERT | DL'20 BM25 |
|---|---|---|---|---|
| Max | .157 (n.s.) | .316 | .250 | .214 |
| NQC (σ of top-k scores) | **.281** | **.463** | .243 | **.438** |

On Robust04 the whole cheap family sits in a narrow Pearson band — n(σₓ%) **.589**, WIG .546, SMV .534, Clarity .528, σ_k .522, NQC .516, RSD .455 ([arXiv 2204.11489](https://ar5iv.labs.arxiv.org/html/2204.11489)) — with **n(σₓ%)**, the standard deviation over documents scoring ≥50% of the top score, best. It costs the same as what you already do (one pass over the k similarity floats) and, because it is defined *relative to the top score*, it is the one predictor whose threshold is portable across query languages: a Hindi query whose top cosine is 0.41 and an English query whose top cosine is 0.68 are compared on the same footing.

Three hard caveats:

1. **Predictors do not transfer across collections, let alone languages.** NQC's Pearson r vs nDCG is .354 on ROBUST/BM25 and **−.010** on MS MARCO/BM25 ([arXiv 2504.01101](https://arxiv.org/abs/2504.01101)). You cannot inherit a threshold. Fit it on your own 28-question set plus a matched English control.
2. **QPP predicts ranking, not answers.** On TREC-RAG, NQC correlates 0.3286 with nDCG@5 (dense) but **−0.004** with Nugget-All (answer quality). Oracle selection optimised for nDCG@5 on BM25 raised retrieval from 0.285 to 0.644 while delivering only 0.344 answer quality; selecting directly for answer quality delivered 0.536 ([arXiv 2604.22661](https://arxiv.org/html/2604.22661v1)). **n=56 queries**, so treat magnitudes loosely. You have Langfuse judges; tune the gate on answer quality, not nDCG.
3. **Elaborate routers do not pay.** Threshold-based selection between BM25 and BM25+QE on ROBUST: BM25 alone .5106, +QE .5322, oracle .5393, best selective system .5325 — it beat neither the oracle nor, meaningfully, the best standalone. A trained SVM choosing between BM25 and SPLADE captured 0.15 of a 3.70-point oracle gap. "QPP-driven selective query processing offers only marginal gains" ([arXiv 2504.01101](https://arxiv.org/abs/2504.01101)). Independently, on financial documents, fusion itself bought ~28% Hit@10 while an oracle over the interpolation-weight grid showed 21.8% headroom that **none of three lightweight adaptive routers reliably captured** ([arXiv 2608.00183](https://arxiv.org/abs/2608.00183)).

**Your case is different in one way that matters: you have a hard signal, not a subtle confidence estimate.** Script mismatch is not a probabilistic guess about query intent; it is a proof that the lexical arm's term intersection is empty. Deterministic gates are exactly where the literature's negative results do not apply.

**But the script gate is blind to Hinglish.** Romanised Hindi is Latin script; a gate asking "is this script absent from the corpus?" sees Latin, sees Latin in the English corpus, and never opens. The fix is language identification, not script identification. `lid.176.ftz` is 917 kB and sub-millisecond ([fastText](https://fasttext.cc/docs/en/language-identification.html)), and for romanised Indic specifically, [IndicLID](https://arxiv.org/abs/2305.15814) is "the first LID for romanized text in Indian languages"; synthetic training data with realistic spelling variation raises romanized-LID F1 on 20 Indic languages from 74.7% to **85.4%** (synthetic only) and **88.2%** (plus harvested text) ([arXiv 2504.21540](https://arxiv.org/abs/2504.21540)). Word-level code-mixed LID reaches 94.52% on SAIL ICON 2017 with a single-layer LSTM over sub-word representations ([arXiv 2011.11263](https://arxiv.org/abs/2011.11263)). An 85–88% F1 classifier is enough to gate on, and being wrong is cheap both ways.

**A pre-retrieval alternative that is script-agnostic by construction**: "the rarest query n-gram has zero frequency in this project's corpus." [LLM-independent adaptive retrieval](https://arxiv.org/html/2505.04253v1) found the best external feature matched or beat LLM-uncertainty methods at ~1.0 LM calls vs 1.7–2.0 (2WikiMultiHopQA: knowledgability 38.4 @1.0 vs HybridUE 37.4 @2.0). Sober baseline: "Always RAG" scores 49.6 / 31.2 / 37.4 / 41.0 on NQ/SQuAD/2Wiki/HotpotQA and the adaptive gate essentially ties it — **it buys efficiency, not accuracy**. Two Postgres caveats: `ts_stat` returns df per *lexeme* only, so word-n-gram frequency is not derivable from a tsvector without materialising your own table; and `ts_stat` takes a literal SQL string, so per-project scoping means interpolating the project id into it.

> **Watch the sign.** IDF = log(N/df) is **maximal** for a term with df=0. A pre-retrieval IDFmax router will score an untranslated Devanagari query as the *most* specific variant and pick it over the English translation. Read raw df / coverage (fraction of query lexemes with `ndoc > 0`), not smoothed IDF, and handle df=0 explicitly.

**Calibrate rather than guess the floor.** [Calibrated retrieval-budget allocation](https://arxiv.org/abs/2606.29959) reports Expected Calibration Error dropping from 0.275→0.062 (TriviaQA), 0.643→0.009 (NQ), 0.711→0.031 (MS MARCO) for sequence log-probability (out-of-fold diagnostics). The signals are LLM-side, not retrieval-side, but the technique transfers directly: label your 28 non-English plus a matched English set with "did the search find the right chunk," fit one logistic regression per language group mapping (max, σ-50%, lexical row count) to P(success), and gate on the calibrated probability. It also reports that graded retrieval is not automatically cheaper: latency +27% on Qwen3-8B, −8% on Qwen3-32B.

**Adaptive-k for the cutoff.** Sort scores descending, take first differences, cut at the largest gap, add a 5-doc buffer, restrict the search to the top 90% ([arXiv 2506.08479](https://arxiv.org/abs/2506.08479)). HotpotQA (GPT-4o, BGE): 63% accuracy / 70.83% context recall / **99.24% token reduction** vs fixed-25k at 74% / 92.50% / 82.19%; NQ 61% (vs 64); TriviaQA 96% (vs 93). It **loses accuracy on two of three factoid sets** — the selling point is the token reduction. The cut *location* is invariant under affine rescaling and therefore language-portable; deciding a gap is "not significant" is not, because gap magnitudes shrink with the compressed score range of a cross-lingual query.

---

## 4. Why the lexical arm dies cross-lingually — and the four ways to bring it back

### The mechanism, stated exactly

An inverted index is a map from *post-analysis tokens* to posting lists. `content_tsv` maps English stemmed lexemes. A Devanagari query token and an English lexeme are different byte strings. Scoring — whether BM25's `Σ_{t ∈ q∩d} idf(t)·tf-sat(t)` or `ts_rank_cd`'s cover density over query lexemes — is a sum over the intersection. The intersection is empty. The score is not low; it is a sum over zero terms, and the document never enters the candidate set. **28/28 zero rows is the correct behaviour of the wrong tool.**

This is not fixable by: a different stemmer, a different `regconfig`, `unaccent`, `pg_trgm`, `simple`, PGroonga, BM25F, a bigger GIN, `rum`, or real BM25 via ParadeDB. Every one of those changes *how terms are normalised or scored*; none changes *which terms exist*. The only four levers that change which terms exist are below.

### Way 1 — Translated BM25 (put corpus-language terms in the query)

**Mechanism:** translate the question into the corpus language and feed the translation to `websearch_to_tsquery(project_regconfig, translated)` in addition to the embedder.

**Evidence:** on CLIRudit, query translation moves BM25 from 0.196 to 0.417 nDCG@10 and R@100 from 0.416 to 0.706 ([CLIRudit](https://arxiv.org/abs/2504.16264)). On the Sinhala/Tamil e-government set, a monolingual English pipeline scores R@15 of 8.2%/4.2% and Google-Translate query translation recovers to **92.4%/93.0%** (R@1 60.0%/59.4%), degrading with MT quality — NLLB 87.0/89.0, mBART50 82.8/85.2 ([arXiv 2608.12820](https://arxiv.org/abs/2608.12820); 500 QA pairs over 1,699 contexts, one gold passage per query, so "Recall@15" is success@15 on a small index).

**Cost:** zero marginal when the existing gate has already fired — you are reusing a translation you already paid for. On ungated queries, one LLM call (~200–400 tokens, ~300–800 ms).

**Postgres:** fully feasible today, no schema change. Route the same translated string into the tsquery builder, not just the embedder.

**Limit:** it is the weakest of the translation repairs, and worst exactly where scripts diverge — 0.1830 vs 0.3705 nDCG@20 on NeuCLIR Chinese ([Lin et al.](https://arxiv.org/abs/2304.01019)). Expect modest help, not transformation.

### Way 2 — PSQ / structured queries (don't collapse to one translation)

**Mechanism:** replace each query term with its top-k translation alternatives, weighted by alignment probability, combined with a synonym/weighted-OR operator. `P(w_T|D_S) = Σ P_B(w_T|w_S)·P(w_S|D_S)`; scoring `Σ log[(1−α)P(w_T|D_S)/(α·P(w_T|G_T)) + 1]`, or the HMM form with α=0.1 background smoothing against a corpus unigram model ([Nair & Oard, TREC 2022](https://trec.nist.gov/pubs/trec31/papers/umcp.N.pdf): umcp_hmm zh 0.3029/0.1471/0.3429/0.6323, fa 0.2716/0.1206/0.4172/0.6498, ru 0.3192/0.1809/0.3482/0.5966 for nDCG@20/MAP/R@100/R@1k).

**Evidence:** PSQ-HMM averages R@100 **0.585** / MAP **0.332** vs QT-BM25's 0.477/0.267 and DT-BM25's 0.546/0.302, significantly better than both over 456 topics. At TREC 2024 NeuCLIR the `fast_psqtd` baseline scored nDCG@20 0.444 (zh) / 0.487 (fa) / 0.359 (ru), beating `patapscoBM25dtRM3td` (0.468/0.455/0.399) in Persian, with zero neural inference; the best neural fusion + GPT-4 rerank runs reach 0.664/0.690/0.593 ([TREC 33 NeuCLIR overview](https://trec.nist.gov/pubs/trec33/papers/Overview_neuclir.pdf)). And the ancestor result: unweighted synonym-set OR recovers **84–92%** of the fully weighted model's average precision using only a dictionary ([Xu & Weischedel](https://aclanthology.org/W00-1312/)).

**Cost:** query time only, plus a translation table. Hindi-English is **not** a low-resource pair: [Samanantar](https://huggingface.co/datasets/ai4bharat/samanantar) has 49.7M English-Indic pairs of which **10.1M are Hindi** (CC-BY-NC-4.0 — non-commercial, check before shipping); [OPUS](https://opus.nlpl.eu) aggregates 1,214 corpora / 1,038 languages / 102,878,590,853 sentence pairs; [MUSE](https://github.com/facebookresearch/MUSE) ships 110 bilingual dictionaries including hi-en (5k train / 1.5k test source words, extended sets to 100k). Published PSQ tables are 33.8–184 MB gzipped per language, but **cover only de/es/fa/fr/it/ru/zh — there is no Hindi table off the shelf.**

Aligner choice, if you build one: [eflomal](https://github.com/robertostling/eflomal) gives AER 0.081 in 337 s on 1.13M en-fr sentences vs fast_align's 0.153 in 241 s — 40% slower, roughly half the error. On the small low-resource benchmark (ro-en, 48,681 sentences) it is 0.298 vs 0.325 at 2× the time, a much thinner win. Independent AER (lower better, de/fr/ro/ja/zh-en) from [awesome-align](https://aclanthology.org/2021.eacl-main.181/): fast_align 27.0/10.5/32.1/51.1/38.1, eflomal 22.6/8.2/25.1/47.5/28.7, GIZA++ 20.6/5.9/26.4/48.0/35.1, SimAlign 18.8/7.6/27.2/46.6/21.6, awesome-align 15.3/4.4/22.6/37.9/13.6. GIZA++ is the slowest by far (IBM Model 4: 2.7 CPU-hours for 17.6M tokens, 63.2 hours for 368M, one direction) and only worth it to reproduce a published number. There is also a corpus-free route: learn a linear map between monolingual embedding spaces from a seed dictionary — on FIRE 2008/2012 Hindi→English this beat a dictionary baseline by 70%, the hybrid by 77%, and exceeded the English monolingual baseline by 15% combined with Google Translate ([arXiv 1608.01561](https://arxiv.org/abs/1608.01561); relative gains over a weak baseline, not absolute MAP).

**Postgres:** the *retrieval* half works — build `to_tsquery('english', 'a | b | c')` in application code. The *weighting* half does not. `tsquery`'s `:A`/`:B` labels are match **filters**, and `ts_rank`/`ts_rank_cd`'s `weights float4[]` is `{D,C,B,A}` applied to lexemes labelled by `setweight()` on the **document** vector, defaulting `{0.1,0.2,0.4,1.0}`. There is no per-query-term numeric weight in core Postgres. Three workable shapes:

1. **Rank-only.** Issue the flat weighted-OR tsquery, take `ts_rank_cd` ordering, let RRF absorb it. Probabilities affect recall; RRF handles ordering. *Recommended first step* — RRF is already rank-only, so the missing calibration is invisible by construction.
2. **Tiered RRF.** Issue 2–3 tsqueries (tier 1 = best translation, tier 2 = alternatives 2..k) and fuse the tiers as extra weighted RRF arms.
3. **Exact rescore.** Retrieve with the flat OR, then compute `Σ pᵢ · ts_rank_cd(content_tsv, to_tsquery(termᵢ))` over the ~500–1000 candidate rows. This two-stage shape is forced, not chosen: translation-model scoring "cannot be implemented directly with existing query evaluation techniques on inverted indexes" ([IRST replication](https://cs.uwaterloo.ca/~jimmylin/publications/Liu_etal_SIGIR2022.pdf)).

**Gotchas:** `to_tsquery` raises a syntax error on unsanitised dictionary tokens and cannot take multi-word entries — build each translation with `plainto_tsquery`/`phraseto_tsquery` under the project's regconfig and combine with `||`. The tsquery node limit is 32,768 (15 terms × 10 translations = 150, ample). **Do not use a Postgres synonym or thesaurus dictionary for this**: a multi-lexeme replacement is emitted as a boolean AND (`'sn' & 'supernova' & 'star'`), the opposite of what translation alternatives need. And a Devanagari-keyed dictionary misses romanised Hinglish entirely — that path needs transliteration or LID before lookup.

### Way 3 — Learned sparse (make the vocabulary itself cross-lingual)

**Mechanism:** train an encoder to emit weights over a *shared* vocabulary regardless of input language. MILCO's connector maps everything into English lexical space; SPLADE-X masks mBERT's output vocabulary to 33k English sub-words; BLADE prunes vocabulary and adds cross-language intermediate pretraining.

**Evidence:** MILCO reaches MKQA R@100 **76.6** vs BGE-M3's sparse arm at 45.3 — a 69% relative gain — and edges M3-Dense's 75.1, with MIRACL avg 72.3 (Hindi 64.4) ([MILCO](https://arxiv.org/abs/2510.00671)). It is the only published model that makes the *lexical* half of a hybrid contribute across scripts while staying interpretable — which would let a "match %" UI stay honest cross-lingually.

**Cost:** a 560M encoder at ingest **and** in the query hot path. Your current embedder is a hosted API; this adds a GPU service and query-time latency you do not have. SPLADE-X and BLADE are worse operationally: "SPLADE-X and BLADE target cross-lingual retrieval only and rely on training separate models for each language pair, limiting their applications" — a non-starter when the corpus language is a project setting and the question language is whatever the user types.

**Postgres:** storable. A 300-nnz MILCO vector is 2,416 B and fits under the 1,000-nnz HNSW ceiling. But there is no impact-ordered/WAND path in pgvector, IVFFlat does not support `sparsevec`, and no benchmark of HNSW-over-`sparsevec` at LSR scale was found.

**Verdict:** watch, don't adopt. Gate on public weights under a usable licence and somewhere to run a 560M encoder. Until then, index-time document translation is the same pivot idea with no new model.

### Way 4 — Character n-grams and transliteration (change the unit of matching)

**Mechanism:** stop matching words. Index overlapping character n-grams (n∈{2,3,4}) so matching needs no stemmer, no stopword list, and no correct word segmentation. Or transliterate romanised input into a script the index shares.

**Evidence:** on Khmer, char-n-gram BM25 beat multilingual-E5-small by ~0.35 nDCG (0.876 vs 0.523) precisely because of "ambiguous word boundaries," "weak support in multilingual embedding models," and "frequent mixed Khmer-English usage" ([KSE-Web](https://arxiv.org/abs/2608.21365)) — the same code-mixing profile as Hinglish. `pg_trgm` is mechanically script-agnostic: `trgm_op.c` takes a single-byte fast path only when `pg_encoding_max_length()==1`, otherwise walking with `pg_mblen_unbounded()` and hashing multibyte trigrams to three bytes via legacy CRC32 ("Reduce a trigram (three possibly multi-byte characters) to a trgm, which is always exactly three bytes… otherwise we form a hash value").

**But be precise about what this buys.** N-grams and trigrams help **within** a script: typos, morphology, transliteration drift ('Bengaluru'/'Bangalore', 'kaise'/'kaisay'). Devanagari trigrams and Latin trigrams still never overlap. **This is the most over-recommended "fix" for cross-script retrieval on the internet and it does not address it.** Its legitimate roles here are (a) as the lexical config for languages Postgres cannot stem or segment (Bengali, Telugu, Urdu, CJK, Thai — via PGroonga, the only such extension available on Supabase), and (b) as a narrowly scoped third arm for Hinglish/romanised traffic over titles or entity spans, not full chunk bodies.

**Transliteration direction matters.** Hinglish→Devanagari only helps if the corpus is Hindi. Against an English corpus you need Hinglish→English, i.e. translation. Fold transliteration into the translation prompt rather than chaining a ~60%-word-accuracy transliterator into an MT step.

### Which one, in what order

| | Effort | Expected gain on Hindi→English lexical | Schema change |
|---|---|---|---|
| **1. Translated tsquery** | Hours | Converts 0 rows into real rows; modest ranking gain | None |
| **2a. Dictionary OR (MUSE hi-en)** | 1 day | ~84–92% of full PSQ, per Xu & Weischedel | None |
| **2b. Probability-weighted PSQ** | 1–2 weeks (aligner + table) | +8–16% relative AP over 2a, mostly invisible under rank-only RRF | None (table is a side lookup) |
| **4. Multilingual doc2query** | Ingest pipeline + LLM cost | Unmeasured; the only way an English index carries Devanagari lexemes | Append to `content`, or one DDL rewrite |
| **3. Learned sparse (MILCO)** | GPU serving | Best published, +31 R@100 over M3-Sparse on MKQA | New column type + serving |

---

## 5. Decision tree

**Inputs:** query language Q, corpus language composition C, budget, latency.

```
START
│
├─ Is C a SINGLE language and Q == C?
│  └─ YES → You have no cross-lingual problem.
│           Spend effort on in-language lexical quality instead:
│           • ts_rank normalization flag 1 or 2 (NOT 32 — it is monotonic
│             and cannot reorder; under rank-only RRF it is a literal no-op)
│           • setweight(title,'A') || setweight(body,'D') in the generated column
│           • unaccent for Latin-script European configs
│           • hnsw.ef_search = 100–200; hnsw.iterative_scan = relaxed_order (pgvector ≥0.8.0)
│           STOP.
│
├─ Is C MIXED-language (one project, several document languages)?
│  ├─ Documents are in Postgres-stemmable languages (the 28)?
│  │  └─ Per-row regconfig: a `regconfig`-typed column + expression GIN index,
│  │     or tsvector_update_trigger_column. Default the column to
│  │     pg_catalog.simple; upgrade only on confident LID.
│  │     Add GlotLID/OpenLID at ingest. Ship a custom Hindi stopword list
│  │     (there is no hindi.stop) if you enable the hindi config.
│  ├─ Documents include Bengali/Telugu/Urdu/CJK/Thai?
│  │  └─ Postgres FTS cannot serve these. PGroonga is the only option
│  │     available on Supabase. It gives tokenization, NOT IDF/BM25 ranking.
│  └─ EITHER WAY: also translate the corpus into ONE pivot at ingest and add
│     an 'english' tsvector alongside the native one. CLIRudit: +0.162 nDCG@10
│     on the sparse side. This is the strongest document-side move that exists.
│
└─ Is Q ≠ C with C SINGLE-language (THE MOTIVATING CASE: Hindi → English)?
   │
   ├─ FIRST, unconditionally, before anything else:
   │  1. Measure dense Recall@50 and Recall@100 on the 28 questions with known-good
   │     chunks. This is the reranker's and the fusion's hard ceiling.
   │     • Recall@50 > 80% and the answers are just ranked badly → a reranker fixes it.
   │     • Recall@50 near or below the published 69.5% for text-embedding-3-large
   │       on cross-lingual MKQA → reranking buys a fraction of the remaining 30%;
   │       the fix is upstream (embedder or translation).
   │  2. Confirm the vector column can even be HNSW-indexed. pgvector caps
   │     `vector` at 2,000 dims for HNSW and `halfvec` at 4,000.
   │     text-embedding-3-large is 3072 → it must already be halfvec, binary-quantized,
   │     or Matryoshka-reduced. If not, you are doing exact scans.
   │  3. Log which fusion branch fires per query. You currently have no visibility
   │     into how often the lexical arm contributes noise vs nothing.
   │
   ├─ Is Q Latin-script but not English (HINGLISH)?
   │  └─ Your Unicode script gate CANNOT fire. This is a correctness bug, not an
   │     optimisation. Add romanized LID (IndicLID, 85–88% F1) alongside the
   │     script check. False positive costs one translation call; false negative
   │     is the current behaviour. Then treat it as the Q ≠ C path below.
   │     No published retrieval evaluation of Hinglish→English exists — measure
   │     in-house before building a feature for it.
   │
   ├─ BUDGET: hours, no new infra
   │  ├─ Route the EXISTING translated question into the LEXICAL arm, not just
   │  │  the embedder. (Way 1.)
   │  ├─ Gate the fusion: if the lexical arm returns 0 rows, return dense-only
   │  │  EXPLICITLY. If the question's script is absent from the project regconfig,
   │  │  don't run the lexical arm at all. If it returns < ~3 rows for a multi-term
   │  │  query, drop it rather than let 1–2 junk rows tie your best semantic hit.
   │  └─ Change the translation prompt to emit 3–8 English alternatives per content
   │     word and OR them, instead of one fluent sentence. (Way 2a, PSQ's one idea,
   │     for the price of a longer prompt.)
   │
   ├─ BUDGET: days, no new infra
   │  ├─ MUSE hi-en dictionary → OR'd tsquery under the project regconfig,
   │  │  fed into the existing RRF as an additional ranked list. (Way 2a.)
   │  ├─ Exp4Fuse shape: run lexical(original) + lexical(translated) +
   │  │  semantic(original) + semantic(translated), fuse all four at k=60.
   │  │  You get translation's recall without betting the result on the
   │  │  translation being right.
   │  ├─ Replace the bare max-similarity floor with σ-50% (dispersion over docs
   │  │  scoring ≥50% of the top score) — same inputs, same cost, best Pearson in
   │  │  the cheap family, and scale-free so the threshold ports across languages.
   │  └─ Add a translate-then-rerank step: hosted multilingual cross-encoder over
   │     k=25–50, scored on the TRANSLATED query. +10–34% relative on CIRAL.
   │
   ├─ BUDGET: weeks, willing to change the embedder
   │  ├─ Build the eval set first: the 28 questions with PARALLEL chunks (same
   │  │  content in both languages) so you can separate "found the right meaning"
   │  │  from "found the right language". Without that split you cannot diagnose.
   │  ├─ Bake off text-embedding-3-large vs Gemini Embedding vs BGE-M3 vs
   │  │  voyage on YOUR data, using the LAReQA mixed-pool framing, not MTEB average.
   │  ├─ Emit 1024 or 1536 dims (MRL) rather than 3072 in the same migration —
   │  │  native HNSW, 2–3× less storage, ~0.6 nDCG cost.
   │  └─ Cheap alternative worth testing FIRST: fit a LIR/SHIFT language-offset
   │     projection from a few hundred parallel pairs. One day of work, fully
   │     reversible, no API spend. Gains are strongly model-dependent (huge on
   │     mE5-large, ~0.3% on bge-m3, unknown on text-embedding-3-large).
   │
   └─ BUDGET: ingest pipeline changes acceptable
      ├─ Multilingual doc2query: generate 3–8 pseudo-queries per chunk in
      │  English + Devanagari Hindi + romanised Hinglish, filter them with a
      │  relevance model (doc2query--: +16% effectiveness, −23% query time,
      │  −33% index size), and index them. This is the ONLY way an English
      │  corpus produces non-zero lexical rows for a Devanagari question
      │  without leaving Postgres. Unmeasured cross-lingually.
      └─ HyPE: precompute hypothetical questions per chunk in each expected
         query language, embed them, point them at the chunk. Zero query
         latency, high ingest cost, and the lexical half hits the regconfig
         constraint. Sequence this after translation-into-FTS is measured.

LATENCY BUDGET OVERLAY
  < 300 ms added  → gated query translation only; RRF weight changes; σ-50% gate
  < 1 s added     → + hosted cross-encoder rerank at k=25–50
  < 3 s added     → + cross-lingual generative query expansion (2 LLM calls)
  no ceiling      → listwise LLM reranking (11–32 s/query) — offline evaluation only
```

---

## 6. What NOT to do, with the evidence

**Do not partition or filter by language.** Filtering to the query's language guarantees the Hindi question never sees the English chunks. It is the exact opposite of the goal. And pgvector's own warning applies to *any* selective filter: "filtering is applied after the index is scanned. If a condition matches 10% of rows, with HNSW and the default `hnsw.ef_search` of 40, only 4 rows will match on average" ([pgvector README](https://github.com/pgvector/pgvector)). Your real filter is `project_id`, and that is where iterative scans matter. Partitioning also forces every PK/unique constraint to absorb the partition key ("the constraint's columns must include all of the partition key columns") and fans vector queries across N HNSW graphs.

**Do not reach for `pg_trgm` as the cross-lingual fix.** It is the most common suggestion and it cannot cross scripts — Devanagari and Latin trigrams never overlap. Worse, adding a noisy third list to a rank-only RRF is actively risky: its rank-1 junk ties your best semantic hit at 1/61.

**Do not use empirical min-max / relative score fusion here.** It forces every arm's best hit to exactly 1.0 regardless of quality, so a lexical arm that returned five irrelevant chunks contributes at full strength. That is strictly worse than theoretical min-max, which at least anchors the floor. And with `n=1` in an arm the denominator is zero — which is precisely the cross-lingual edge case.

**Do not use z-score without a NULL guard.** `float8_stddev_samp` returns NULL when `N <= 1`, so `NULLIF(σ, 0)` never fires on the single-row case; the expression evaluates to NULL, and PostgreSQL documents that "null values sort as if larger than any non-null value; that is, NULLS FIRST is the default for DESC order." A confused lexical arm's rows sort to the **top**. Wrap in `COALESCE(..., 0)` or specify NULLS LAST.

**Do not use CombMNZ, Condorcet, or Borda with two arms.** CombMNZ's multiplier takes only the values 1 and 2, so it is a blunt 2× bonus for cross-arm agreement — and agreement is exactly what cannot happen when one arm is dead. Cormack: CombMNZ "results have higher variance, ranging from insubstantially better than RRF to substantially worse than Condorcet," and it beat RRF on only 1 of 4 TREC collections. Condorcet needs a pairwise majority vote, which with two voters ties on every disagreement, and lost to RRF 7/7 (p≤0.008). Borda's points scale with list length, so a 3-row arm and a 200-row arm are incomparable — and unequal length is the cross-lingual case.

**Do not add raw `ts_rank_cd` to raw cosine.** Braschler states the principle that justifies your current architecture: the retrieval status value "is only used for sorting the list, and is only valid in the context of the query, weighting and collection used" ([IR Journal 2004](https://link.springer.com/content/pdf/10.1023/B:INRT.0000009445.19495.46.pdf)). Bruch et al. measured the consequence: unnormalised lexical scores added to a fine-tuned semantic ranking cause "a severe degradation of ranking quality."

**Do not rely on ts_rank normalization flag 32 to fix length bias.** It is documented as "divides the rank by itself + 1", i.e. `r/(r+1)` — a strictly monotonic transform. It cannot reorder anything. The flags that change ordering by length are **1** (divide by 1+log(length)) and **2** (divide by length). And under rank-only RRF, *any* monotonic rescale of `ts_rank_cd` is invisible end-to-end by construction.

**Do not encode learned impacts as repeated lexemes.** PostgreSQL's [text search limitations](https://www.postgresql.org/docs/current/textsearch-limitations.html): "Position values in tsvector must be greater than 0 and no more than 16,383" and "No more than 256 positions per lexeme." Repeating 100–200 lexemes up to 255 times needs 25,500–51,000 positions; beyond 16,383 they saturate and, because a lexeme's positions are a distinct sorted set, saturated repeats **collapse** — term frequency silently truncates after roughly the 64th term. `ts_rank` also de-duplicates query operands via `SortAndUniqItems()`, making repetition a no-op there. And you still cannot express learned *query*-side weights: four A/B/C/D classes, full stop.

**Do not expect learned sparse to fix cross-lingual retrieval.** BGE-M3's sparse arm adds **+0.2** R@100 over dense alone on cross-lingual MKQA. SPLADE-v3 is English WordPiece and CC-BY-NC-SA (non-commercial). SPARTA (0.340) and DeepCT (0.307) lose to plain BM25 (0.429) on BEIR zero-shot; DeepImpact scores 0.415, also below BM25 ([SPRINT, SIGIR'23](https://arxiv.org/abs/2307.10488)). "Learned" does not imply "better out of domain," and it certainly does not imply "crosses languages."

**Do not naively multilingualise a sparse model.** Zero-shot SPLADE-X loses ~34% to a statistical-translation baseline in German. "None of the SPLADE-X variants consistently outperform the PSQ baseline." Do not go looking for a magic multilingual sparse checkpoint; the win in that paper came from *fusing* a translation run with a learned run.

**Do not adopt a "language-aware" or "language-coherent" reranker.** [LAMAR](https://arxiv.org/abs/2607.22042) is trained to rank same-language documents higher. Against a Hindi question over an English-only corpus, that objective penalises every document you have. Test explicitly that any candidate reranker does not down-rank a correct English chunk for a Hindi query.

**Do not scale rerank depth to "catch the cross-lingual miss."** Rerankers produced Recall@10 *worse* than retrieval alone 53.3%/44.4% of the time when K was scaled, and "Helps & Never Hurts" held in only ~23% of experiments — with `text-embedding-3-large` as one of the first stages ([Drowning in Documents](https://arxiv.org/abs/2411.11767)). If the answer chunk is not in your dense top-50, no reranker setting fixes it.

**Do not use step-back prompting for this.** Its published gains (MMLU Physics +7%, Chemistry +11%, TimeQA +27%, MuSiQue +7%, all on **PaLM-2L**) are reasoning-benchmark gains, not retrieval metrics — no nDCG or Recall is reported ([arXiv 2310.06117](https://arxiv.org/abs/2310.06117)). It addresses "question too specific," not "query and index share no script."

**Do not interpolate query embeddings on an English index.** Mean Δ = −0.04 nDCG@10, λ\*=0 optimal in 8/13 cases ([arXiv 2606.13537](https://arxiv.org/abs/2606.13537)). Use the pure translated embedding, and if you want both signals, fuse two runs instead.

**Do not build a learned per-query router.** Three lightweight adaptive routers failed to reliably beat a fixed blend against 21.8% oracle headroom; QPP-driven pipeline selection captured ~4% of its oracle gap; Adaptive-RAG's complexity classifier is 54.52% accurate overall. Use the deterministic signal you already have (script/language mismatch) instead.

**Do not port an English-tuned threshold to Hindi.** NQC's correlation swings from .354 to −.010 between two English collections. Cross-language transfer is strictly less likely. Calibrate per language group.

**Do not use Clarity as the cross-lingual gate.** It is a KL divergence between the top-k document language model and the collection language model — a lexical statistic. It has the *same* structural failure as `content_tsv`, which makes it useless as a detector of that failure.

**Do not plan around `pg_search`/ParadeDB, VectorChord-bm25, or `pg_bigm` on Supabase.** None appears in [supabase/postgres `nix/ext`](https://github.com/supabase/postgres/tree/develop/nix/ext). ParadeDB is also AGPL-3.0. What *is* available and under-used: **pgroonga** (script-agnostic tokenization, no regconfig) and **rum** (in-index ranking with stored positions).

**Do not put an LLM call inside a generated column.** "The generation expression can only use immutable functions and cannot use subqueries or reference anything other than the current row in any way" ([ddl-generated-columns](https://www.postgresql.org/docs/current/ddl-generated-columns.html)). The correct shape is a plain `text` column written by the ingest pipeline plus a generated tsvector over it. And changing an existing generated column's expression is DDL: `ALTER TABLE ... ALTER COLUMN ... SET EXPRESSION AS` (PG 17+) rewrites the whole table under ACCESS EXCLUSIVE; before 17 it is DROP + ADD.

**Do not concatenate configs into one tsvector if you rank with `ts_rank_cd`.** `tsvector || tsvector` is legal in a generated column, but the docs note "the second input's positions are adjusted accordingly" — positions are offset. `ts_rank_cd` is cover density and "requires lexeme positional information to perform its calculation," so words adjacent in the source text end up hundreds of positions apart when they matched in different sub-vectors. Separate columns fused as separate RRF lists preserve both correctness and diagnosability ("the Hindi column matched, the English one did not").

**Do not `strip()` a tsvector anywhere in the ingest path.** `ts_rank_cd` "ignores any 'stripped' lexemes… If there are no unstripped lexemes in the input, the result will be zero." Under rank-only RRF, an all-zero `ts_rank_cd` means the lexical arm's ordering is an arbitrary tie-break on **every** query, English included. Cheap to audit.

**Do not treat the 28/28 result as a lexical-arm defect to fix in the lexical arm.** It is the correct behaviour of an inverted index. Fixing it means putting corpus-language terms in the query (Ways 1–2), query-language terms in the index (Way 4 / doc2query), or building a shared vocabulary (Way 3). Everything else is in-language relevance tuning wearing a cross-lingual label.

---

## 7. Verification checklist (all cheap, all in-house)

| Check | Command / method | Why it decides something |
|---|---|---|
| Is the vector column HNSW-indexable? | `SELECT extversion FROM pg_extension WHERE extname='vector';` + inspect the index definition | 3072 dims exceeds pgvector's 2,000-dim `vector` HNSW cap; you may be doing exact scans unknowingly |
| Is Devanagari reachable at all? | `SHOW lc_ctype;` and `SELECT to_tsvector('english','भारत की राजधानी');` | Distinguishes "wrong stemmer" from "unreachable"; unreachable only under `C` ctype |
| Is per-row regconfig legal here? | `CREATE TABLE t(c text, lang regconfig, tsv tsvector GENERATED ALWAYS AS (to_tsvector(lang,c)) STORED);` | If it works, the "hard constraint" is a schema choice, not a Postgres limit |
| Dense Recall@50/@100 on the 28 | Replay with `LIMIT 100`, check for the gold chunk id | The ceiling on every reranker and fusion change |
| ef_search deficit | Replay at `hnsw.ef_search` 40 / 100 / 200 vs the exact-scan fallback | If exact scan answers questions HNSW misses, that gap is the deficit |
| Arm overlap rate | Per query, `\|lexical ∩ semantic\|` grouped by detected script | Zero overlap ⇒ your RRF is round-robin (64% of optimum in CLEF) |
| Junk-arm rate | Count queries where the lexical arm returns 1–2 rows on a multi-term non-English query | Distinguishes the benign empty case from the dangerous noisy one |
| Is `strip()` anywhere in ingest? | grep the ingest path | All-zero `ts_rank_cd` degrades fusion on every query |
| Language-vs-content diagnosis | Build the eval set with PARALLEL chunks (same content, both languages) | Separates "found the right meaning" from "found the right language" — a single nDCG cannot |
| sparsevec viability | Load 10k real chunks as `sparsevec`, build HNSW on `<#>`, measure recall vs exact scan and build time | Opens or closes the entire learned-sparse branch |

---

## Appendix: claims marked UNVERIFIED

| Claim | Status |
|---|---|
| BLADE effectiveness numbers | Paywalled (ACM DL 403); only its abstract and MILCO's characterisation are available. Report no numbers. |
| Top-P masking beats Top-K in CLIR | Single collection (NeuCLIR Mandarin), first 75,000 of 3,179,209 documents, mAP-vs-throughput figure only, no tables. Authors: "results… based on a partial subset… formal statistical significance testing has not been performed." |
| MILCO index size in GB and retrieval latency in ms | **Fabricated.** The string "GB" does not occur in the paper; there is no latency table. Only the abstract's relative 3× / 10× claims are supportable. |
| MILCO MKQA per-language range (52.76 Khmer – 78.3 Dutch) | Could not isolate MILCO's column from the table layout. |
| Cohere embed-v3/v4 and Voyage rerank cross-lingual quality | Vendors publish language *lists* (Cohere includes Hindi; Voyage enumerates none) but zero cross-lingual retrieval numbers. |
| Gemini Embedding 2 MTEB multilingual 69.9 | Not found on any Google page. |
| OpenAI's own MIRACL figure for text-embedding-3-large | The embeddings guide lists MTEB 64.6% and no MIRACL. The launch blog returns 403 to automated fetch. All cross-lingual numbers for the incumbent here are third-party. |
| Any retrieval evaluation of Hinglish / romanised-Hindi queries | **Does not exist.** Romanised-Hindi work is LID, transliteration, sentiment and hate-speech classification. CS-MTEB covers 9 languages mixed with English, none Indic. You would be operating without a map. |
| Any published "untranslated BM25 cross-script" baseline | **Does not exist**, and its absence is the finding — every CLIR BM25 baseline already embeds a translation step. Your 0/28 *is* the missing baseline. |
| HNSW-over-`sparsevec` recall/latency/build-time at LSR scale | None found. |
| Per-language embedding-per-chunk indexing | No published method stores one embedding per language per chunk. MVR (per query view) and Doc2Query++ (per generated query) are adjacent, not the same. |
| Cross-lingual doc2query | No published evaluation. Strong monolingual backing; the cross-lingual application is extrapolation. |
| RRF applied to merging per-language indexes, or to fusing an original-query run with a translated-query run | Unstudied intersection. RRF literature is monolingual; CLEF merging literature predates RRF (2009). |
| Cross-lingual QPP calibration | No published calibration of NQC/WIG/σ-max/Clarity for query-language ≠ document-language. Thresholds must be fitted in-house. |
| Martínez-Santiago round-robin "65.0% of optimum" cell | 0.219/0.333 = 65.8%, not 65.0%. Eleven of twelve other cells reconcile exactly, so one of the two round-robin figures is likely misreported — and the round-robin row carries the whole "RRF-becomes-round-robin" argument. |
| vstash "50,425 relevance-judged queries" | Standard BEIR test splits for those five datasets total ~3,700 queries. Almost certainly counts query–document pairs. |
| Cost-aware query routing (26% fewer tokens, 34% lower latency) | 28-query benchmark, single author, no peer review. Existence proof, not a measurement. |
| Adaptive-RAG efficiency ranges (1.03–2.17 steps, 1.46–3.60 s) | Could not reproduce from the paper's tables. |
| Khmer char-n-gram result | 300 queries, **silver relevance labels**, partial human verification, 3,000-document corpus, and monolingual. Not comparable to MIRACL/NeuCLIR. |
| ParadeDB tokenizer availability on managed hosts | Moot — `pg_search` is absent from Supabase's build entirely. |
