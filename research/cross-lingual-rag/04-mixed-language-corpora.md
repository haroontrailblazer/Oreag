# 04 — Mixed-Language Corpora

**The problem:** one knowledge base holds documents in several languages at once. A question in
one of those languages must reach the *whole* corpus, not just its own language's slice.

This is Oreag's known open limit: a project containing English + Hindi files satisfies the script
gate for both languages, so the Hindi question is never translated and reaches only the Hindi half.

**It is not an open research problem.** It has a name (MLIR), a 24-year-old evaluation literature,
a live TREC task, at least six independent published fixes, and one 2025 paper that states Oreag's
exact setup and proposes the exact two repairs listed as "unbuilt". This file is the map.

---

## 1. The task has a name and it is not CLIR

The field splits two things Oreag currently conflates:

| Task | Definition | Where it applies to Oreag |
|---|---|---|
| **CLIR** | one query language against **one** foreign document language | single-language corpus, foreign question |
| **MLIR** | produce "a single ranked list of documents across **many** languages" | the mixed English+Hindi project |

The definition and the distinction are stated explicitly in
[Neural Approaches to Multilingual Information Retrieval](https://arxiv.org/abs/2209.01335)
(ECIR 2023). Everything below is MLIR, and none of it is the same problem as the cross-lingual path
Oreag already ships.

TREC has run MLIR as a scored task since 2022. The
[TREC 2024 NeuCLIR overview](https://arxiv.org/abs/2509.14355) describes an MLIR task producing one
unified ranked list over ~2M Persian + ~3M Chinese + ~5M Russian documents, 51 topics, ~1,999
judgments per topic. **Best nDCG@20 = 0.545, versus 0.664 / 0.698 / 0.593 for the same systems on
the single-language CLIR tasks over the same collections.** That gap — roughly 15–20% relative — is
the cost of mixing, measured under pooled TREC judgments.

[TREC 2025 RAGTIME](https://arxiv.org/abs/2602.10024) repeats it verbatim: "This task expects
systems to search all four document collections and produce a single unified ranked list", over four
separate per-language collections of ~1,000,095 CommonCrawl News documents each (Arabic, Chinese,
English, Russian; Aug 2021 – Jul 2024), with 13 teams submitting 125 runs. Note the architectural
signal: **TREC models a mixed-language corpus as N per-language collections fused into one list**,
not as one blended index.

The consolidated test collection is
[NeuCLIRBench](https://arxiv.org/abs/2511.14758): 250,128 judgments, ~150 monolingual/cross-language
queries and 100 multilingual queries over Chinese/Persian/Russian documents plus English MT. It
ships **a fusion baseline of strong neural retrieval systems** so reranker work does not have to
start from BM25 — i.e. the community's own reference first stage for the mixed case is a fusion, not
a single index.

---

## 2. Classical IR: centralized vs distributed, and the merging problem

The architectural choice Oreag is facing was framed at CLEF 2002 as the **collection fusion
problem**, in [Merging Mechanisms in Multilingual Information
Retrieval](https://ceur-ws.org/Vol-1168/CLEF2002wn-adhoc-LinEt2002.pdf):

- **Centralized** — all languages in one index. "Avoids the merging problem", but distorts idf.
- **Distributed** — one index per language, retrieve separately, then merge.

Their measured result is a warning in both directions. The centralized index **won**:

| Run | MAP | Relevant retrieved (of 8068) |
|---|---|---|
| centralized (one mixed index) | 0.0398 | 1413 |
| distributed + raw-score merging | 0.0381 | 1180 |
| distributed + round-robin merging | 0.0224 | 1165 |

…but the authors attribute the win to an **artifact**, and state the mechanism exactly: pooling
collections raises *N* in idf without raising term occurrences, so "it makes retrieval result
preferring documents in small document collection". N grew 8.6x for French and 3.33x for German;
the inflated small sub-collections happened to be the ones whose CLIR runs were good. They warn
that "if we use the German or Spanish queries as source queries, the performance of centralized
architecture may be not so good."

**Read that as a direct prediction about Oreag's tenants.** A project with 3 Hindi files and 3,000
English files is exactly the pathological small-sub-collection case, and the direction of the bias
depends on which language the query is in.

### The merging strategies, measured

[Selection and Merging Strategies for Multilingual Information
Retrieval](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf) (CLEF 2004, EN/FR/FI/RU,
50 queries) is the head-to-head. Round-robin baseline = 0.2386 / 0.2430 / 0.2358 MAP under three
engine conditions:

| Merge strategy | Different engines per language | Same engine everywhere |
|---|---|---|
| round-robin (baseline) | 0.2386 | 0.2358 |
| raw-score | **0.0642 (−73.1%)** | 0.3067 (+30.1%) |
| biased round-robin (2 docs from each large collection, 1 from the small) | +10.6% | +10.8% |
| logistic regression on ln(rank) + RSV | **0.3090 (+29.5%)** | **0.3393 (+43.9%)** |

Three takeaways that survive to the neural era:

1. **Raw-score merging is catastrophic when the per-language runs are not homogeneous** (−73%) and
   excellent when they share one engine (+30%). Merge correctness is a function of run homogeneity,
   which per-language shards routinely break (different analyzers, different embedders, different
   shard sizes).
2. **Rank-only merging (round-robin) is the floor**, beaten by every score-aware method.
3. **Unequal quotas beat equal quotas** — biased round-robin buys ~+10% for free.

[Merging Multilingual IR Results Based on Prediction of Retrieval
Effectiveness](http://research.nii.ac.jp/ntcir/workshop/OnlineProceedings4/CLIR/NTCIR4-CLIR-LinWC.pdf)
(NTCIR-4, ZH/EN/JA) adds the diagnostic that matters most here: **raw-score merging systematically
under-ranks the collection in the query's own language, because its similarity scores are
numerically smaller.** Their fix scores `S_hat = (S / mean-of-top-k) * W`, where W combines a
translation penalty (average number of translation equivalents per query term, plus unknown-word
count) with a collection weight. On Topic 005 this scored 0.0952 vs raw-score's 0.0489, purely by
lifting the Chinese documents back up.

[UTA at CLEF 2003](https://ceur-ws.org/Vol-1169/CLEF2003wn-adhoc-AirioEt2003.pdf) supplies the
sobering counterweight: across 8 languages, four merging strategies (raw score, round robin,
dataset-size-based, score-difference-per-topic) all landed between **18.2% and 18.6% average
precision** — a spread under half a point, with the ranking flipping by index type. Meanwhile
swapping the word-normalization tool moved English→Finnish bilingual MAP by **−44.1%** (34.0 → 19.0)
and English→Swedish by −29.9%. **Tuning the merger is low-leverage compared to fixing the
per-language retrieval it merges.**

The journal treatment is [An effective and efficient results merging strategy for multilingual
information retrieval in federated search environments](https://doi.org/10.1007/s10791-007-9036-6)
(Information Retrieval, 2008). Its position: normalizing source-specific scores is "not effective".
Instead, download a **small subset** of documents from each per-language ranked list, apply query-
and document-based translation to that subset only, fit transformation models mapping each source's
local scores into a comparable common score, then extrapolate to all retrieved documents. That is
the cheap, still-current recipe for making per-shard scores comparable without translating
everything.

Adjacent classical machinery worth knowing, because it never commits to a single query translation:
[Probabilistic structured queries](https://doi.org/10.1145/860435.860497) (SIGIR 2003) weights both
term-frequency and document-frequency estimates by translation probability (TREC 2002 Arabic CLIR:
one-best 0.16 MAP → WTF/DF 0.20, and stable across pruning thresholds 0.4–1.0 where every other
variant collapses to 0.01–0.07). It still holds up:
[Efficiency-Effectiveness Tradeoff of PSQ](https://arxiv.org/abs/2404.18797) reports, over 456
topics across CLEF 2003 / NTCIR-8 / NeuCLIR 2022, MAP of QT-BM25 0.267, DT-BM25 0.302,
**PSQ-HMM 0.332**; R@100 0.477 / 0.546 / **0.585** — and moves the whole thing to *indexing* time.

---

## 3. Why a single mixed neural index fails: language identity is a direction in the embedding space

The modern diagnosis is precise and consistent across a dozen papers.

**The dominant principal components of a weakly-aligned multilingual encoder encode *which language
the text is in*, not what it means.** [A Simple and Effective Method To Eliminate the Self Language
Bias in Multilingual Representations](https://aclanthology.org/2021.emnlp-main.470/) (EMNLP 2021)
shows this and removes it with a post-hoc linear operation (matrix factorization + orthogonal
projection), reporting "almost 100% relative improvement in MAP" on LAReQA for weak-alignment
models.

The benchmark that isolates it is [LAReQA: Language-Agnostic Answer Retrieval from a Multilingual
Pool](https://aclanthology.org/2020.emnlp-main.477/) (EMNLP 2020) — answer retrieval from a
**mixed-language candidate pool**, which is Oreag's exact configuration. It introduces the
**weak vs strong alignment** distinction: weak = the nearest neighbour in another language is the
right one; **strong = semantically related cross-language pairs must be closer than unrelated
same-language pairs**. That second property is what a mixed index requires and what off-the-shelf
encoders do not have. Its mAP table (XQuAD-R 11 languages / MLQA-R 7 languages, all pooled):

| Training regime | XQuAD-R mAP | MLQA-R mAP |
|---|---|---|
| En-En | 0.29 | 0.36 |
| X-X (translated data, monolingual positive pairs) | **0.23** | 0.26 |
| X-X-mono | 0.52 | 0.49 |
| X-Y (question and answer translated into *different* languages) | **0.66** | 0.49 |
| Translate-Test | 0.72 | 0.58 |

Note X-X (0.23) is **worse than English-only training** (0.29): training on translated data with
same-language positives actively damages mixed-pool retrieval. Only X-Y — which forces the model to
accept a foreign-language answer as correct — fixes it.

The end-to-end RAG version of this is
[The Cross-Lingual Cost: Retrieval Biases in RAG over Arabic-English
Corpora](https://arxiv.org/abs/2507.07543). Its §3 is Oreag's setup, verbatim: *"Given a query in
either language, its goal is to generate an answer in the same language. The corpus includes
documents in both languages, and each query is associated with a ground-truth answer found in one
language only."* A **language-oracle ablation isolates the cause as document–document language
mismatch** — the retriever ranks fine *within* one language and fails when a single mixed index
forces it to compare Arabic and English passages against one query. Measured: M-E5 Hit@20 drops 42%
(Legal) and 33% (Travel), end-to-end accuracy down 40%/37%; BGE-M3 drops 33%/13% but only in the
English-query → Arabic-document direction. Corpora are real corporate Legal and Travel datasets,
deliberately not Wikipedia, to avoid parametric-memory leakage.

Its two mitigations are exactly the repairs Oreag listed as unbuilt:

- **(a) balanced retrieval** — take an equal number of passages from each language subset;
- **(b) dual search** — search the joint corpus **twice**, once with the original query and once
  with its translation, then merge the two ranked lists by embedding inner-product score, take
  top-20.

Both cost nothing in same-language cases ("no statistically significant loss relative to the direct
retriever") while adding ~4–6% overall for BGE-M3 and ~20% for M-E5.

### Corroborating measurements of the same bias

| Finding | Source |
|---|---|
| Debiased analysis shows the effect is **not** English dominance but query↔document **language match**: "the strongest signal consistently moves to the diagonal (Lq=Ld)" | [DELTA / DeLP](https://arxiv.org/abs/2601.02956) |
| Retriever language-preference scores: English 47.70 vs zh 35.90, ko 35.47, fr 37.94; MLRS metric = how much a document's rank improves when translated into the query language | [Investigating Language Preference of Multilingual RAG](https://arxiv.org/abs/2502.11175) |
| Multilingual rerankers put a **non-English document first 72.8% of the time for English queries** when semantically equivalent documents exist across languages | [LAMAR](https://arxiv.org/abs/2607.22042) |
| With the widely used BGE reranker, **>70% of top-5 documents come from English + the query language alone** (13 languages); ~15 points of Recall@3-gram left on the table vs an oracle (48.9 vs 63.6), worst on non-Latin scripts: ko 25.5/41.0, th 26.4/44.1, ja 29.2/47.9 — and the oracle evidence is already in the top-50 pool, just downweighted | [All Languages Matter / LAURA](https://arxiv.org/abs/2604.20199) |
| **Same-language bias (SLB)** named and measured; BM25-Original has the highest SLB of all methods — without filtering it out, BM25 would have appeared to beat MPNet (S@10 51.9 vs 38.5) | [MultiClaim](https://aclanthology.org/2023.emnlp-main.1027/) |
| Semantic retrieval quality and query-language preference are near-orthogonal and often **anti-correlated** (Pearson −0.28 to −0.38 across 31 retrievers): mE5-large 96.15 nDCG / 99.92 LPR; Qwen3-Embedding-8B 68.64 nDCG / **53.00** LPR; BM25 27.92 / 93.68 | [MLAIRE](https://arxiv.org/abs/2605.07249) |
| Language-preference bias exists in dense retrievers *by construction*: multilingual encoders inherit language bias from pretraining and fine-tuning only ever ranks within one language space, so "the ranking score generated by mDPR [is] inconsistent across languages" | [KD-SPD / Soft Prompt Decoding](https://arxiv.org/abs/2305.09025) |
| Language distribution of retrieved passages is arbitrary, not query-driven: baseline mDPR retrieves **>90% Thai passages for Amharic queries**; after language-alignment fine-tuning the Amharic-Arabic model returns 98% Arabic | [Limits of cross-lingual DPR for low-resource languages](https://arxiv.org/abs/2408.11942) |
| The retrieved evidence set is a function of query *language*, not just query meaning — the same question in different languages surfaces different passages on TyDi/XOR-TyDi | [Investigating Information Inconsistency in Multilingual ODQA](https://arxiv.org/abs/2205.12456) |

**Consequence for the 80/80 number.** MLAIRE exists because standard retrieval metrics conflate
cross-lingual semantic skill with query-language preference. On a **single-script** corpus the two
are indistinguishable by construction — which is precisely the condition under which 80/80 was
measured, and precisely why it did not predict the mixed-corpus failure. Track **Language
Preference Rate alongside nDCG** from here on.

---

## 4. Modern neural treatments

Four distinct families. They are not alternatives to each other in the way routing-vs-fusion is;
several compose.

### 4a. Train the retriever so scores are comparable across document languages

This is the direct attack on the diagnosis in §3.

- [Neural Approaches to MLIR](https://arxiv.org/abs/2209.01335): fine-tune XLM-R with
  **mixed-language batches** built from neural translations of MS MARCO. Result:
  **indexing documents in their original languages reaches 98% of the document-translation MAP with
  an 84% reduction in indexing time**, and the 2% gap is not statistically significant.
- [Distillation for MLIR (MTD)](https://arxiv.org/abs/2405.00977): extends Translate-Distill
  because "Translate-Distill only supports a single document language", explicitly to satisfy the
  requirement that "the model must assign comparable relevance scores to documents in different
  languages". MTD-trained ColBERT-X beats Multilingual Translate-Train by **5–25% nDCG@20 and
  15–45% MAP** (CLEF03 nDCG@20 0.643→0.675, MAP 0.451→0.520; ~26%/~47% on NeuCLIR 2022). Crucially,
  it is **robust to how languages are mixed** (Mix Passages / Mix Entries / Round Robin Entries are
  statistically equivalent) **as long as multiple languages appear in every training mini-batch**.
- [HLTCOE at TREC 2023 NeuCLIR](https://arxiv.org/abs/2404.08118): best MLIR run nDCG@20 = 0.362
  with multilingual translate-train; the operational rule is one sentence — *"A key to making MTT
  successful is to include documents from every target language in each batch."*
- [Translate-Distill](https://arxiv.org/abs/2401.04810) is the base method (cross-encoder teacher in
  its best configuration, dual-encoder student trained for the cross-language case); trained models
  are on HuggingFace.
- [MIMO](https://arxiv.org/abs/2605.31171): explicitly targets "queries and relevant documents may
  appear in different languages within a mixed-language corpus", and argues *against* splitting into
  monolingual sub-searches. Distilling from a Qwen3-Embedding-8B English teacher then jointly
  optimising distillation + cross-lingual contrastive loss at λ=0.2 gives xlm-roberta-large
  **60.69 avg nDCG@20** on MLIR vs 53.18 (XLCO), 52.95 (LaKDA), 31.41 (plain InfoNCE). The λ sweep
  is the actionable part: λ=0 gives best alignment but wrecks uniformity, λ=1 the reverse.
- [KD-SPD](https://arxiv.org/abs/2305.09025) beats mDPR by 20.2% MAP over CLEF/mTREC/LAReQA
  (15 languages) — and, uniquely, benchmarks **both** architectures at issue: the per-language
  pipeline (mDPR + Round Robin, mDPR + Score merging) *and* a single end-to-end multilingual index,
  finding "end-to-end mDPR does not show a consistent advantage over the pipeline mDPR."
- Fairness-flavoured variant: [LaKDA](https://aclanthology.org/2024.mrl-1.23/) (KL-divergence loss
  aligning score distributions across parallel queries) on MultiEuP-v2 (24 European languages) lifts
  XLM-R MRR@100 46.5 → 61.0 and fairness MRC@5 11.7 → 15.9, where the obvious MSE-alignment baseline
  *collapses* mBERT accuracy (35.6 → 24.0).

**Cost:** a training pipeline. **Not** available to a team that only calls an embedding API.

### 4b. Remove the language direction from embeddings, post-hoc, at index time

Cheapest family. No retraining, no routing, no per-query cost.

- [SHIFT](https://arxiv.org/abs/2606.18801): estimate a **relative language vector** as the plain
  mean embedding difference over parallel pairs, `V_target = (1/N) Σ (z_i^target − z_i^source)`
  (533k mMARCO pairs), then **subtract it from document embeddings at index time only** — query
  embeddings untouched, zero query-time overhead. On multilingual-e5-large: nDCG@20 0.633 → 0.737
  average over four MLIR benchmarks (Belebele 0.816 → 0.910; MLQA 0.494 → 0.649); Target-Languages
  Recall@20 0.540 → 0.694. Its opening premise is Oreag's bug: "recent multilingual dense retrieval
  models often exhibit a strong preference for documents in the same language as the query."
- [LangSAE Editing](https://arxiv.org/abs/2601.04768): opens with *"Dense retrieval in multilingual
  settings often searches over mixed-language collections, yet multilingual embeddings encode
  language identity alongside semantics."* Sparse autoencoder over pooled mE5-large embeddings
  (262,144-unit dictionary, expansion 256, top-k 4,096); suppress language-associated latents at
  inference and **reconstruct to the original dimensionality so existing vector DBs still work**.
  Belebele macro-avg nDCG@20 0.5359 → 0.6534 (+21.9%), R@20 0.4958 → 0.6280 (+26.6%); XQuAD nDCG@20
  0.7141 → 0.8613. Script-distinct languages benefit most — **Chinese 0.3397 → 0.6947 (+104.3%)**.
- [Disentangled Contrastive Learning](https://arxiv.org/abs/2608.02189) does the same split as an
  explicit training objective (semantic vs linguistic subspaces): +1.5 MRR@10 on mMARCO (27.8 vs
  26.3), +2.7 nDCG@10 on MIRACL (55.0 vs 52.3), with the larger share of gain on languages with no
  parallel training data.

**Caveat both share:** they need parallel data *per language pair* to estimate the offset. That is a
global, one-off precomputation from mMARCO — not something a tenant corpus must supply. But the
survey [Understanding Cross-lingual Alignment](https://arxiv.org/abs/2404.06228) warns that
perfectly language-neutral embeddings are not the goal: "an effective trade-off between
language-neutral and language-specific information is key."

### 4c. Fix it at the reranker

Over-retrieve from the mixed index, then control the language composition of the top-k.

- [LAMAR](https://arxiv.org/abs/2607.22042): open cross-encoder, initialised from bge-m3-retromae;
  stage 1 = English-anchored relevance distillation on 6.7M instances (MMARCO 14 langs / MIRACL 51
  langs / RLHN), stage 2 = 8.6K preference pairs for language coherence. nDCG@1 for language
  coherence 96.89 (XQuAD, 12 langs) / 94.66 (BELEBELE, 14 langs), while staying competitive on
  MIRACL (69.5 vs 69.7 best) and MTEB (86.84 vs 87.34). It also shows documents **in the query's
  language yield higher downstream QA F1** — so language composition is not a fairness nicety, it
  moves answer quality.
- [LAURA](https://arxiv.org/abs/2604.20199): partition retrieved candidates **by language**, rank
  independently within each language group to guarantee balanced exposure, then apply absolute
  utility thresholds keyed to *downstream generation quality* rather than semantic relevance
  (utility averaged over four generator models, threshold 0.8). Significant in 10 of 13 languages
  (overall p = 8.62e-74); PEER language-fairness +~7 points for BGE. Pipeline: BGE-M3 retrieves
  top-50 over a unified 13-language corpus, reranker picks top-5.

This is per-language sub-search *implemented at the rerank stage* — it gets the balanced-exposure
property without a second index or a second retrieval call.

### 4d. Normalize the language of the corpus or the context

- **At index time:** translate documents into one pivot language and index that.
  [Anveshana](https://arxiv.org/abs/2505.19494) (English queries, Sanskrit documents) is the extreme
  case: DT+BM25 reaches 62.46 nDCG@10 / 74.03 R@10 while direct shared-embedding retrieval
  (multilingual-e5-base) gets **10.74** nDCG@10 and XLM-R DOT only 4.26 — a ~6x gap for an
  unfamiliar script. The index-architecture rule is stated outright in the
  [CLIR book](https://arxiv.org/abs/2111.05988) §2.1: *"Query translation has advantages for
  applications in which there are many possible query languages, but only one document language…
  Symmetrically, document translation has advantages when all the queries are in one language, but
  there are many document languages to be searched. In such cases, space efficiency argues for
  indexing in the one query language."* Oreag is the first case for single-language tenants and the
  **second case for mixed tenants** — which is the cleanest argument for handling those tenants
  differently at ingest.
  Counterweight: [What Drives Cross-lingual Ranking?](https://arxiv.org/abs/2511.19324) reports
  dense retrieval is "largely unaffected by document translation and can even degrade slightly
  because of translation-induced noise", and
  [Evaluating LLMs for Cross-Lingual Retrieval](https://arxiv.org/abs/2509.14749) shows the value of
  document translation shrinking as the reranker strengthens (+0.026 MAP for RankZephyr, +0.011 for
  RankGPT3.5, **+0.003 for RankGPT4.1**). Document translation helps *lexical* retrieval, not strong
  dense pipelines.
- **At generation time:** [CrossRAG](https://arxiv.org/abs/2504.03616) /
  [published version](https://aclanthology.org/2026.findings-eacl.35/) translates the **retrieved
  documents** into a common language before generating. GPT-4o flexible-EM on MKQA:
  no-RAG ~43 → tRAG 46.5 → monoRAG 51.5 → **MultiRAG 53.1** → **CrossRAG 60.4**. Averaged over all
  languages, gains over monolingual RAG are tRAG +8.9%, MultiRAG +14.3%, CrossRAG +17.8%; on
  low-resource languages MultiRAG gains 6.6–8.4% over monoRAG and CrossRAG adds a further 3.7–5.0%.
  Critically for step 4 of Oreag's target: measured with OpenLID, **CrossRAG produces the correct
  answer language more consistently than MultiRAG** — i.e. leaving mixed-language passages in the
  prompt itself induces wrong-language answers. Cost: one translation call per retrieved document,
  on the critical path.
- **Metadata instead of rewriting:** [QTT-RAG](https://arxiv.org/abs/2510.23070) passes
  query-language documents through untouched, translates foreign ones, scores each translation on
  semantic equivalence / grammatical accuracy / naturalness (0.0–5.0), and attaches the scores as
  **metadata rather than rewriting content**, to avoid translation-induced distortion. Gains are
  modest and language-dependent (Korean XOR-TyDi 43.8% vs 42.0% CrossRAG; near-flat on Chinese,
  because only 5% of Chinese retrievals were cross-lingual vs 22.7% for Korean). The ablation's
  hard-filter variant thresholds at 3.5 on all three axes.

---

## 5. Language-aware routing

### What ships today, and why the default is wrong

| System | What it provides | Verdict |
|---|---|---|
| [Haystack](https://haystack.deepset.ai/tutorials/32_classifying_documents_and_queries_by_language) | `DocumentLanguageClassifier` tags each document with an ISO code in metadata; `MetadataRouter` sends it to a per-language store; `TextLanguageRouter` routes the query to a named output (or `unmatched`) | **Routes the wrong way.** Its own tutorial: *"The language of a question is detected, and only documents in that language are used to generate the answer."* That is Oreag's bug shipped as the documented default. |
| [Elastic](https://www.elastic.co/blog/multilingual-search-using-language-identification-in-elasticsearch) | LID model `lang_ident_model_1` in an ingest pipeline; two documented strategies — **language-per-field** (one index, per-language analyzed fields, queried with `multi_match`/`best_fields` across all of them at once) and **language-per-index** (queried via `lang-per-index_*`) | The `best_fields` pattern *is* per-language sub-search + fusion, in production, today. Elastic explicitly advises **against** detecting the query's language: "search queries tend to be short" and LID "work[s] best with more than 50 characters" — get it from user locale instead. |
| [Azure AI Search](https://docs.azure.cn/en-us/search/search-language-support) | "Create a blended index with language-specific versions of each field", per-field analyzers, constrain with `searchFields`; on unknown query language, "the query can be issued against all fields simultaneously" plus scoring profiles | Fully manual. The doc admits it has no mechanism for determining the query's language. |
| [Vespa](https://docs.vespa.ai/en/linguistics.html) | Multiple languages in one schema | Disclaims the capability in writing: *"Vespa supports having documents in multiple languages in the same schema, but does not out-of-the-box support cross-lingual retrieval."* Also: "Vespa does not know the language of a document", and with the 0.02 confidence cutoff "queries with 3 terms or fewer will default to English." |
| [RAGFlow](https://ragflow.io/docs/glossary) | "Cross-language search" since v0.19.0 — the chat model translates the query into user-selected target languages before matching, "such as in Chinese-English datasets" | Query translation, always-on, user-selected targets. No gate, no automatic per-language routing. |

### Published routing systems

- [DS@GT Language-Routed RAG (FinMMEval)](https://arxiv.org/abs/2607.22841) — **closest published
  match to the fix Oreag proposed, and it includes Hindi.** LangGraph pipeline: detect query
  language, retrieve from a 30,209-entry multilingual KB with BGE-M3 + FAISS, and when a language
  has fewer than **τ = 20** native exemplars in the index, **fuse the cross-lingual/global index
  with the native-language shard via weighted RRF with `w_global = 1.0`, `w_lang = 2.0`, damping
  `k = 60`** — the native shard trusted 2x. Hindi ran a three-way RRF over global + English +
  Arabic-proxy indices before earning a dedicated shard. Final accuracy: Hindi 73.5%, Arabic 76.0%,
  English 69.5%, Chinese 64.5%. Generator model is also language-routed.
- [Effects of Cross-lingual Evidence in Multilingual Medical QA](https://arxiv.org/abs/2604.20531) —
  fixed **50/50 quota**: 10 documents per question, "half of the documents in English and the other
  half in the target language". Beats English-only retrieval for low-resource languages: Basque
  76.0% vs 68.18%, Kazakh 75.73% vs 66.93%, reaching accuracy comparable to high-resource languages.
- [CroSearch-R1](https://arxiv.org/abs/2604.25182) — multi-turn retrieval policy that **prioritises
  the query-language ("local") collection on turn one, then expands to other-language ("global")
  collections on later turns**. mE5 embedder + NLLB-200-distilled-600M to translate retrieved docs
  into a unified space, Qwen2.5-3B/7B generator, GRPO. MKQA fEM with Qwen2.5-7B: en 72.07 vs 69.43,
  fr 59.67 vs 57.91, th 27.83 vs 25.29, ar 24.12 vs 18.65 (avg 45.92 vs 42.82) against Search-R1.
- [CORAL](https://arxiv.org/abs/2604.25676) — maintains **separate per-language Wikipedia indexes**
  and does query-conditioned corpus *selection*: a planner picks a small set of linguistically /
  culturally adjacent corpora per query (e.g. Indonesian alongside Sundanese) rather than pooling.
  Loop: select corpora → retrieve → critique evidence → check sufficiency → on failure reselect and
  rewrite. Beats monoRAG, tRAG, multiRAG and crossRAG: 61.83% vs 57.83% on BLEnD low-resource
  (+3.58pp), 58.88% vs 53.75% on CLIcK.
- [IndicIRSuite](https://arxiv.org/abs/2312.09508) is the multi-monolingual extreme: **11 separate
  ColBERT models**, one per Indian language, +47.47% MRR@10 over INDIC-MARCO baselines. It is an
  existence proof that per-language Indic retrieval infrastructure is trained and available — but it
  pays 11 models to serve and never evaluates any query/document language mismatch.

### The counter-evidence: routing to the query's language is often the *wrong* policy

Before building a router, note that three separate studies find **retrieving across languages beats
restricting to the query's language, even when in-language documents exist**:

- [BordIRLines](https://arxiv.org/abs/2410.01171) (720 queries, 251 disputed territories, 49
  languages, 19,916 query-document pairs): retrieving **multilingual** documents beats purely
  in-language retrieval on both response consistency (Command-R 64.2 → 78.7) and geopolitical bias
  (28.7 → 5.9). Also: OpenAI text-embedding-3-large retrieved **1.72x more English documents** than
  M3-Embedding on the same queries — your embedder silently sets the language mix.
- [Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/) explicitly ablate the corpus
  configuration — English-only vs user-language-only vs **concatenated** multilingual Wikipedia
  across all 13 languages — and find retrieval from the **concatenated** corpus beneficial in most
  cases with a single multilingual dense retriever (BGE-m3). One shared index, not per-language
  routing.
- [Multi-FAct](https://arxiv.org/abs/2402.18045): "ensembling multiple non-English Wikipedias works
  better than single language Wikipedia".
- [MultiRAG vs monoRAG](https://arxiv.org/abs/2504.03616): MultiRAG (single mixed index) beats
  monoRAG (query-language corpus only) by +14.3% vs +8.9% over the no-RAG baseline with GPT-4o, and
  by 6.6–8.4% on low-resource languages specifically.

And one genuine counter-counter-example, so this is not one-sided:
[Cross-Lingual ODQA with Answer Sentence Generation](https://aclanthology.org/2022.aacl-main.27/)
finds a cross-lingual generative system beats answer-sentence-selection baselines in **all 5**
languages but beats the **monolingual** generative pipeline in only **3 of 5** — mixing evidence
languages is not unconditionally a win at the generation stage.

**Read together: the fix for the mixed corpus is not "route the Hindi question to the Hindi shard".
It is "make the Hindi question able to reach both halves". Same-language routing is the bug.**

---

## 6. Chunk-level language tagging

Every architecture in §5 and options C/D in the design menu need a per-chunk language label.
Getting it is the unglamorous prerequisite.

**Where the label comes from.** Elastic ships `lang_ident_model_1` as an inference processor in an
ingest pipeline
([docs](https://www.elastic.co/blog/multilingual-search-using-language-identification-in-elasticsearch));
Haystack ships `DocumentLanguageClassifier`, which "classifies the language of documents and adds
the detected language to their metadata" as ISO codes
([tutorial](https://haystack.deepset.ai/tutorials/32_classifying_documents_and_queries_by_language)) —
note its default is `en` only, with everything else tagged `unmatched`. For broad coverage,
[GlotLID](https://github.com/cisnlp/GlotLID) is a fastText LID supporting 2,000+ language labels;
`lingua` is what [XRAG](https://arxiv.org/abs/2505.10089) uses for response-language correctness and
OpenLID is what [Ranaldi et al.](https://arxiv.org/abs/2504.03616) use.

**Four failure modes to design around:**

1. **Short text.** Elastic's own guidance is that LID "work[s] best with more than 50 characters";
   Vespa documents that with its 0.02 confidence cutoff "queries with 3 terms or fewer will default
   to English". Chunks are usually long enough; **queries are not**. Get the query language from
   user context (locale, tenant setting) where you can.
2. **Romanized text.** A Unicode script check cannot distinguish Hinglish from English.
   [IndicLID / Bhasha-Abhijnaanam](https://aclanthology.org/2023.acl-short.71/) covers all 22
   scheduled Indian languages in native *and* romanized form, and quantifies the asymmetry:
   **98.55% accuracy / 98.31 F1 on native script vs 80.40% / 74.72 F1 on romanized** (the romanized
   number is an ensemble of a fastText classifier at 71.49% and an IndicBERT classifier at 80.04%).
   Native-script LID is essentially solved (NLLB 98.78%, CLD3 98.03%); romanized is not.
3. **Code-switched chunks.** A single label is a lie for a chunk that mixes languages — and a
   whole-response LID will happily pass a code-switched answer. See §7.
4. **The label may not be knowable at all.** Vespa states plainly that "Vespa does not know the
   language of a document" — language is a per-field indexing parameter, not something the engine
   infers. If you use a store with that model, tagging is entirely your job at ingest.

**Related use of the same idea:** [QTT-RAG](https://arxiv.org/abs/2510.23070) attaches *translation
quality* scores as chunk metadata rather than rewriting content, and lets the generator weigh
evidence by translation reliability. Metadata tagging generalises beyond the language label itself.

**Honest gap:** across this sweep, no paper was found that uses chunk-level language tagging as an
explicit *retrieval routing signal* — it appears as an ingest/plumbing practice in Elastic and
Haystack, and as an analysis variable in research, but not as a named, evaluated method.

---

## 7. Code-switched corpora

A corpus can mix languages **within** a chunk, and a query can mix languages within a sentence.
This is a distinct, worse problem from a corpus that mixes monolingual documents.

- [Code-Switching Information Retrieval](https://arxiv.org/abs/2604.17632) (CSR-L + CS-MTEB, 11
  tasks): code-switching degrades even robust multilingual retrievers by **up to 27%**, and the
  diagnosed cause is "substantial divergence in the embedding space between pure and code-switched
  text". Worst case: e5-large-v2 on CS-MTEB reranking with Japanese code-switching falls from a
  60.17 baseline to **25.75**. Lexicon-based vocabulary expansion only partially recovers
  (Chinese CSR-L 35.32 → 43.50) — it is "insufficient". Evaluated across statistical, dense and
  late-interaction paradigms.
- [MiLQ](https://arxiv.org/abs/2505.16631) has the opposite, useful result: for retrieving **English
  documents**, mixed-language queries are dramatically *better* than native-script ones. BM25
  MAP@100 — native queries 12.35 (low-resource: Swahili, Somali) and 8.56 (high-resource: Finnish,
  German, French) vs **mixed-language queries 38.35 and 34.92** (monolingual ceiling 48.71). NMT
  applied to *mixed* queries beats NMT applied to native queries (48.10/47.08 for BM25) — the
  English fragments help the translator too. Mixed-Distill (trained on artificial code-switched
  text) is the most balanced across query types. **So a Hinglish query may already be reaching the
  English half; do not "fix" it before measuring.**
- [Lost in Transliteration](https://arxiv.org/abs/2505.08411): BGE-M3 loses **97% of MRR@10 on
  Latinized Chinese queries** (0.2342 → 0.0078) and 49% on Latinized Russian (0.2444 → 0.1244) on
  mMARCO. Fine-tuning on a **50/50 mixture of native + Latinized** queries is the only config that
  repairs the transliterated side without wrecking the native side (Chinese-T 0.0078 → 0.1382,
  Russian-T 0.1244 → 0.2633 vs 0.2770 native). Qualitative analysis: top-10 overlap between native
  and transliterated versions of the same query was ≤3 documents for most sampled queries.
- **Training-side remedy:** [Boosting Zero-shot Cross-lingual Retrieval by Training on Artificially
  Code-Switched Data](https://arxiv.org/abs/2305.05295) — artificial code-switching from bilingual
  lexicons gives **+5.1 MRR@10 in CLIR and +3.9 MRR@10 in MLIR** on mMARCO across 36 language pairs,
  with monolingual IR flat and gains up to 2x absolute for distant language pairs.
- **Monolingual KB, code-switched queries:** [Multilingual Information Retrieval with a Monolingual
  Knowledge Base](https://arxiv.org/abs/2506.02527) fine-tunes multilingual-e5-base with
  weighted-sampling contrastive learning so an English-only KB is searchable by non-English and
  **Hinglish** queries (MRR 0.6653 / R@3 0.7410 vs 0.6520 / 0.7271 for random negative mining).
  Explicitly "applicable for both multilingual and code switching use cases".
- **Historical precedent for mixed-script collections:** the FIRE **Mixed Script Information
  Retrieval** shared task ran 2014–2016 over collections where queries *and* documents appear in
  either Devanagari or Roman transliterated script
  ([overview](https://link.springer.com/chapter/10.1007/978-3-319-73606-8_3)) — the closest
  historical analogue to a mixed-script single corpus, though pre-neural and with no generation
  stage.
- **Generation side:** code-switched *output* persists even when retrieval is fixed. Chirkova et al.
  report frequent code-switching in non-Latin-script languages, and that named-entity code-switching
  survives even after Correct Language Rate is pushed >95%
  ([source](https://aclanthology.org/2024.knowllm-1.15/)). A whole-response LID scores such an
  answer as a pass — score at sentence level.
- Related but not retrieval: [CroCoSum](https://arxiv.org/abs/2303.04092) (24k English articles,
  18k Chinese summaries, >92% containing code-switched phrases) carries the negative result that
  "leveraging existing CLS resources as a pretraining step does not improve performance" — i.e.
  translation-derived cross-lingual corpora do not transfer to naturally occurring code-switched
  output.

---

## 8. Where RRF across language-specific lists misbehaves

Reciprocal Rank Fusion is the default reflex for "I have N ranked lists". For **hybrid** fusion
(dense + sparse over the *same* corpus) it is well-supported: MIRACL's hybrid BM25+mDPR reaches
nDCG@10 0.578 / R@100 0.889 vs BM25's 0.393/0.787 and mDPR's 0.415/0.788 — ~47% relative gain
([MIRACL](https://aclanthology.org/2023.tacl-1.63/)); [Agri-Query](https://arxiv.org/abs/2508.18093)
fuses BM25 + gte-Qwen2-7B with RRF and beats a 128K long-context prompt on the same model (0.880 vs
0.694). Nothing here argues against that use.

**Fusing across *language-specific* lists is a different operation, and the classical evidence says
rank-only equal-weight fusion is the weakest member of its own family.**

1. **RRF is rank-only, and rank-only merging is the measured floor.** Round-robin — the
   equal-quota, score-blind ancestor of unweighted RRF — is the worst merger in
   [CLEF 2002](https://ceur-ws.org/Vol-1168/CLEF2002wn-adhoc-LinEt2002.pdf) (0.0224 MAP vs 0.0381
   raw-score and 0.0398 centralized) and the baseline that logistic regression on ln(rank)+RSV beats
   by **+28% to +44%** in [CLEF 2004](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf).
   RRF discards score magnitude, so it structurally **cannot express that one language's list is
   uniformly better for this query** — the exact information you need when one shard holds the
   answer and the other holds nothing relevant.
2. **Equal weights assume equal trust; the two published multilingual RRF deployments both refuse
   that assumption.** DS@GT uses `w_lang = 2.0` vs `w_global = 1.0`
   ([source](https://arxiv.org/abs/2607.22841)); the medical QA system uses a hard 50/50 quota
   ([source](https://arxiv.org/abs/2604.20531)). CLEF 2004's *biased* round-robin (2 documents from
   each large collection, 1 from the small) beats plain round-robin by ~+10.6% precisely by breaking
   equal quotas. **Plain unweighted RRF over per-language lists is not a published configuration.**
3. **Rank-k does not mean the same thing in a 3-document shard and a 3,000-document shard.** RRF
   dodges the score-scale problem and replaces it with a rank-scale assumption that is false for
   asymmetric shards. The classical statement of the same pathology, from the other direction:
   pooling collections raises N in idf without raising term occurrences, so retrieval ends up
   "preferring documents in small document collection"
   ([CLEF 2002](https://ceur-ws.org/Vol-1168/CLEF2002wn-adhoc-LinEt2002.pdf)). Either architecture
   has a shard-size bias; RRF just relocates it.
4. **Fusion correctness depends on run homogeneity, which per-language shards break.** Raw-score
   merging collapses **−73.1% MAP** when the per-language runs use different engines but gains
   **+30.1%** when they share one
   ([CLEF 2004](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf)). Per-language shards
   invite exactly that heterogeneity (per-language analyzers, per-language encoders — cf.
   [IndicIRSuite's 11 separate models](https://arxiv.org/abs/2312.09508)). If you go
   score-comparable-by-construction (§4a), raw-score merging becomes the *better* option than RRF;
   if you cannot, RRF is the safe-but-blunt fallback.
5. **Merging is low-leverage compared to the retrieval it merges.** Four merging strategies spanned
   **<0.5 percentage points** of average precision across 8 languages, while changing the
   word-normalization tool moved bilingual MAP by −44%
   ([CLEF 2003](https://ceur-ws.org/Vol-1169/CLEF2003wn-adhoc-AirioEt2003.pdf)). Do not spend a
   sprint tuning `k`.
6. **RRF's documented mechanism is variance smoothing, not peak precision.** The multilingual RAG
   system that uses it says so: multi-query RRF "smooths performance variance across query
   formulations", i.e. it protects against a single bad query embedding
   ([source](https://arxiv.org/abs/2512.12694)). When one language's list is right and the other is
   noise, that smoothing **drags the correct list down**.
7. **Retrieval-side fusion can be undone at generation.** Even with balanced evidence in the
   context, [Linguistic Nepotism](https://arxiv.org/abs/2509.13930) shows models given one
   **relevant** target-language document and one **irrelevant** English document cite the irrelevant
   English one; citation accuracy for non-English documents drops with resource level (Swahili
   −23.9%, Bengali −18.0% vs Spanish −8.08%, French −8.82%), and the gap is widest for mid-context
   documents. [Not All Languages are Equal](https://arxiv.org/abs/2410.21970) finds English wins
   multilingual knowledge *selection* through selection bias, and that simply **repositioning the
   English documents** in the context mitigates it. And leaving mixed-language passages in the
   prompt measurably degrades answer-language correctness
   ([CrossRAG vs MultiRAG, OpenLID](https://arxiv.org/abs/2504.03616)).

**What to use instead of, or alongside, plain RRF:**

| Option | Prior art |
|---|---|
| Weighted RRF with per-shard trust weights | [DS@GT](https://arxiv.org/abs/2607.22841) (`w_lang=2.0`, `w_global=1.0`, `k=60`) |
| Hard per-language quota (fixed k documents per language) | [Cross-Lingual Cost](https://arxiv.org/abs/2507.07543) balanced retrieval; [Medical QA](https://arxiv.org/abs/2604.20531) 50/50 |
| Biased round-robin by shard size | [CLEF 2004](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf) (+~10%) |
| Logistic regression on (ln rank, score) | [CLEF 2004](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf) (+28–44%) |
| Normalize by mean-of-top-k, weighted by predicted run effectiveness / translation penalty | [NTCIR-4](http://research.nii.ac.jp/ntcir/workshop/OnlineProceedings4/CLIR/NTCIR4-CLIR-LinWC.pdf) |
| Fit score-transformation models from a downloaded subset of each list | [Si & Callan 2008](https://doi.org/10.1007/s10791-007-9036-6) |
| Merge two lists over the **same** index (original + translated query) by inner-product score | [Cross-Lingual Cost](https://arxiv.org/abs/2507.07543) |
| Skip fusion; rank within language groups at the reranker | [LAURA](https://arxiv.org/abs/2604.20199), [LAMAR](https://arxiv.org/abs/2607.22042) |

**Open item worth knowing:** no modern ablation of RRF against Z-score or logistic-regression
merging on a *dense* per-language pipeline surfaced in this sweep. The classical results above are
sparse-retrieval results. If you build option D, that ablation is both your validation and a
publishable contribution.

---

## 9. The zero-architecture first move

Before any of the menu below: Oreag already has a query-translation path. The
[Cross-Lingual Cost](https://arxiv.org/abs/2507.07543) mitigation (b) reuses it with **no new index
and no routing at all**:

> search the joint corpus **twice** — once with the original query, once with its translation —
> then merge the two ranked lists by embedding inner-product score and take the top 20.

Both lists come from the **same** index and the **same** encoder, so scores are natively comparable
and none of §8's fusion pathologies apply. Measured cost: +4–6% for BGE-M3, ~20% for M-E5, with **no
statistically significant loss in same-language cases** — meaning the weak-similarity gate is no
longer load-bearing for correctness, only for spend. The related embedding-level variant is
[query embedding interpolation](https://arxiv.org/abs/2606.13537): mixing the query embedding with
its translation's embedding beats the best monolingual endpoint in **88 of 105 cases**, with the
critical asymmetry that mixing is uniformly beneficial for **non-English** indices while "indices
containing English are best served by pure English queries."

This is the cheapest possible experiment and it directly tests whether the mixed-corpus bug needs
architecture at all.

---

## 10. Design menu

Five candidate architectures for the mixed-corpus case. They are ordered by increasing structural
commitment, not by expected quality. A and C compose; B and E are mutually exclusive with each
other; D is the heaviest.

---

### A — One mixed index, language direction removed from the embeddings

**Shape.** Keep the single index. At ingest, subtract a precomputed per-language offset from each
document embedding (or suppress language-identity latents), so "which language is this" stops being
a retrievable direction. Queries untouched.

**Prior art.** [SHIFT](https://arxiv.org/abs/2606.18801) (mean embedding difference over 533k
mMARCO parallel pairs, subtracted at index time; mE5-large nDCG@20 0.633 → 0.737 avg over four MLIR
benchmarks, Target-Languages Recall@20 0.540 → 0.694).
[LangSAE Editing](https://arxiv.org/abs/2601.04768) (SAE latent suppression, reconstructs to
original dimensionality so existing vector DBs still work; Belebele nDCG@20 +21.9%, **Chinese
+104.3%** — script-distinct languages benefit most). The 2021 linear ancestor:
[LIR](https://aclanthology.org/2021.emnlp-main.470/), ~100% relative MAP gain on LAReQA.

**Cost.** One offline computation per language pair from public parallel data; one vector transform
per chunk at ingest. **Zero query-time cost, no retraining, no second index, no routing, no extra
model calls.** Re-embedding is not required if you keep the transform in the ingest path.

**Known failure mode.** It over-corrects. The alignment survey's operative conclusion is that
"an effective trade-off between language-neutral and language-specific information is key"
([source](https://arxiv.org/abs/2404.06228)), and LAMAR's finding that documents in the query's
language yield **higher downstream QA F1** ([source](https://arxiv.org/abs/2607.22042)) means fully
erasing language signal removes a genuinely useful ranking feature. Also: quality depends on the
offset estimate, which is per-language-pair — a language with no parallel data gets no correction.

---

### B — One mixed index, retriever trained for cross-language score comparability

**Shape.** Replace the encoder with one explicitly trained so relevance scores are comparable across
document languages, so a single ranked list over the mixed corpus is meaningful by construction.

**Prior art.** [Multilingual Translate-Distill / ColBERT-X](https://arxiv.org/abs/2405.00977)
(+5–25% nDCG@20, +15–45% MAP over Multilingual Translate-Train; robust to *how* languages are mixed
in batches as long as every batch contains multiple languages).
[Mixed-language batches with XLM-R](https://arxiv.org/abs/2209.01335) — native-language indexing
reaches 98% of document-translation MAP with 84% less indexing time.
[HLTCOE TREC 2023](https://arxiv.org/abs/2404.08118): "include documents from every target language
in each batch." [MIMO](https://arxiv.org/abs/2605.31171) (60.69 vs 53.18 best baseline nDCG@20).
[KD-SPD](https://arxiv.org/abs/2305.09025) (+20.2% MAP over mDPR).
[LaKDA](https://aclanthology.org/2024.mrl-1.23/) for the fairness-shaped variant.

**Cost.** A training pipeline, GPUs, a re-embed of every tenant corpus on every model change, and
ownership of a model artifact. Off the table for an API-only stack — though ColBERT-X/PLAID-X and
Translate-Distill checkpoints are publicly released, so "adopt a trained model" is cheaper than
"train one".

**Known failure mode.** Low-resource languages stay broken.
[The Multilingual Curse at the Retrieval Layer](https://arxiv.org/abs/2605.24556) reports the best
zero-shot multilingual retriever trailing the best **monolingual** Amharic retriever by 23% relative
MRR@10 (0.653 vs 0.803), with fine-tuning closing but never erasing the gap (best fine-tuned 0.760),
across dense, late-interaction, sparse and cross-encoder architectures — attributed to non-Latin
script, rich morphology, and multilingual tokenizers over-segmenting. Corroborated by
[ALEE](https://arxiv.org/abs/2607.00171): subword fertility predicts embedding quality nearly
linearly (Spearman ρ = −0.786 on alee-F200).

---

### C — One mixed index, over-retrieve, then control language composition at rerank

**Shape.** Retrieve top-50 from the single mixed index, then either (i) rerank with a
language-coherence-aware cross-encoder, or (ii) partition candidates by language, rank within each
group, and take a quota from each before generating.

**Prior art.** [LAURA](https://arxiv.org/abs/2604.20199) — partition by language, rank
independently within each group for balanced exposure, apply utility thresholds tied to downstream
generation quality; significant in 10 of 13 languages. Its motivating measurement is Oreag's bug:
>70% of BGE-reranker top-5 documents come from English + query language alone, with ~15 points of
Recall@3-gram left on the table and the oracle evidence already sitting in the top-50 pool.
[LAMAR](https://arxiv.org/abs/2607.22042) — open reranker, nDCG@1 96.89 / 94.66 for language
coherence while staying competitive on MIRACL and MTEB.
[Balanced retrieval](https://arxiv.org/abs/2507.07543) is the quota-only version, costing 4–6%.

**Cost.** One reranker pass (already common), a larger candidate pool, plus a per-chunk language
label (§6). No index changes, no routing, no retraining if you adopt LAMAR.

**Known failure mode.** It cannot recover what the first stage never retrieved. LAURA's own framing
is that the answer-critical documents are already in the top-50 and merely downweighted — that holds
when the first-stage retriever is decent. When the first stage collapses entirely onto one language
(mDPR returning **>90% Thai passages for Amharic queries**,
[source](https://arxiv.org/abs/2408.11942)), reranking a single-language candidate pool changes
nothing. Also inherits the generation-side biases in §8 item 7.

---

### D — Per-language shards, sub-search, and fusion

**Shape.** Split the tenant corpus into per-language sub-indexes at ingest. On each query, search
several shards (query language + English + any others), then merge into one list. Requires an
explicit policy for *which* shards and *how* to merge.

**Prior art.** [DS@GT](https://arxiv.org/abs/2607.22841) — the closest published match, with Hindi:
weighted RRF, `w_lang=2.0`, `w_global=1.0`, `k=60`, triggered when a language has <20 native
exemplars; Hindi 73.5% final accuracy.
[TREC RAGTIME](https://arxiv.org/abs/2602.10024) — the shared-task version, four collections into
one unified ranked list, 13 teams / 125 runs.
[CORAL](https://arxiv.org/abs/2604.25676) — separate per-language indexes with query-conditioned
corpus *selection* (+3.58pp on BLEnD low-resource).
[CroSearch-R1](https://arxiv.org/abs/2604.25182) — local shard first, global shards on later turns.
[Medical QA](https://arxiv.org/abs/2604.20531) — fixed 50/50 quota, beating English-only for Basque
and Kazakh. Classical merging machinery in §2; the RRF caveats in §8.
Elastic's `language-per-index` and `multi_match`/`best_fields` are the shipped primitives
([source](https://www.elastic.co/blog/multilingual-search-using-language-identification-in-elasticsearch)).

**Cost.** Highest. N indexes per tenant, N retrieval calls per query, a routing policy, a merge
policy with tunable weights, plus chunk-level language tagging as a hard prerequisite. Latency is
N parallel searches plus merge. [DELTA](https://arxiv.org/abs/2601.02956) explicitly **rejected**
this design on cost grounds and folded all languages into a single enriched query instead, at
1.13 s/query vs 3.80 s for the passage-translating DKM-RAG.

**Known failure mode.** Everything in §8: rank-scale incomparability across shards of wildly
different size, equal-weight RRF assuming equal trust, and merge quality collapsing when the
per-shard runs are heterogeneous (−73.1% MAP,
[CLEF 2004](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf)). Plus the pathology
specific to SaaS: a 3-document Hindi shard has no stable score distribution to normalize against,
and CLEF 2002 showed small sub-collections getting systematically over-preferred by the pooled
alternative. And the strongest empirical objection: **[KD-SPD](https://arxiv.org/abs/2305.09025)
benchmarked pipeline-with-merging against a single end-to-end mixed index and found the single index
had no consistent advantage — meaning the reverse is also true, and this expensive architecture may
buy nothing over A or C.**

---

### E — Normalize the corpus language at ingest (single-pivot index)

**Shape.** For tenants whose corpus mixes languages, machine-translate every non-pivot chunk into
one pivot language at ingest and index only the pivot text (keeping the original for display and
citation). The mixed corpus becomes a monolingual corpus, and Oreag's existing single-language
cross-lingual path handles every query language unchanged.

**Prior art.** The architectural rule is stated in the [CLIR book](https://arxiv.org/abs/2111.05988)
§2.1: document translation wins "when all the queries are in one language, but there are many
document languages to be searched", and "space efficiency argues for indexing in the one query
language". [Anveshana](https://arxiv.org/abs/2505.19494): DT+BM25 62.46 nDCG@10 vs 10.74 for direct
shared-embedding retrieval — a ~6x gap on an unfamiliar-script corpus. Index-time PSQ does the
probabilistic version and still beats both QT and DT BM25 in 2024
([source](https://arxiv.org/abs/2404.18797)). The runtime cousin is
[CrossRAG](https://aclanthology.org/2026.findings-eacl.35/), which does the same normalization on
retrieved documents at query time and is the strongest of the four benchmarked strategies (MKQA
GPT-4o 58.0 vs MultiRAG 55.7 vs tRAG 50.2), including on answer-language correctness. Open
translation backbones: [IndicTrans2](https://github.com/AI4Bharat/IndicTrans2) for the 22 scheduled
Indian languages, NLLB-200-distilled-600M generally.

**Cost.** One translation pass per non-pivot chunk **at ingest, off the critical path** — the
opposite trade from CrossRAG, which pays per retrieved document per query. Storage roughly doubles.
Re-translation on corpus update.

**Known failure mode.** Translation noise is now baked into the index and cannot be undone per
query. [What Drives Cross-lingual Ranking?](https://arxiv.org/abs/2511.19324) reports dense
retrieval is "largely unaffected by document translation and can even degrade slightly because of
translation-induced noise"; [Evaluating LLMs for Cross-Lingual
Retrieval](https://arxiv.org/abs/2509.14749) shows the benefit shrinking to +0.003 MAP with a strong
reranker. Document translation is a **lexical**-retrieval win, not a dense-retrieval win. Second
failure: citations and quoted evidence now point at machine-translated text, which is an
attribution and trust problem — and cross-lingual attribution is already weak
([up to ~47% of exactly-correct cross-lingual answers are not attributable to any retrieved
passage](https://arxiv.org/abs/2305.14332)). Third: quality varies by language pair, which is why
QTT-RAG scores translations rather than trusting them
([source](https://arxiv.org/abs/2510.23070)).

---

### Summary

| | Query-time cost | Build cost | Needs chunk language tags | Biggest risk |
|---|---|---|---|---|
| **§9 dual-query merge** | 1 extra search + 1 translation | ~none | no | translation quality; no help when both lists are bad |
| **A** de-bias index | none | offline offsets + ingest transform | no | over-correction; no offset for unseen languages |
| **B** score-comparable retriever | none | training pipeline / model adoption | no | low-resource languages still fail (−23% vs monolingual) |
| **C** over-retrieve + language-aware rerank | 1 rerank pass, larger pool | adopt LAMAR or group-by-language | yes | cannot recover what stage 1 never retrieved |
| **D** shards + fusion | N searches + merge | N indexes, routing + merge policy | yes | RRF pathologies (§8); may beat nothing (KD-SPD) |
| **E** pivot-translated index | none | 1 translation per chunk at ingest | yes | translation noise baked in; citations point at MT |

**Recommended order to test:** §9 → A → C → (B or E) → D. Every step before D is strictly cheaper
than D and at least one published measurement suggests D may not beat them.

---

## 11. How to measure any of this

Do not re-run an 80-query in-house probe. The mixed-corpus case has purpose-built instruments.

| Instrument | What it measures | Why it matters here |
|---|---|---|
| [LAReQA](https://aclanthology.org/2020.emnlp-main.477/) | retrieval from a **mixed-language candidate pool**; weak vs strong alignment | the canonical test of exactly this failure, since 2020 |
| [MLAIRE](https://arxiv.org/abs/2605.07249) | separates cross-lingual semantic relevance from query-language preference; **Language Preference Rate**, Lang-nDCG, 4-way failure decomposition | the only way to tell whether a regression is a semantic failure or a language-preference failure |
| [PEER](https://arxiv.org/abs/2405.00978) | Kruskal-Wallis-based fair-ranking metric for whether documents from different languages get equal expected rank in **one** list; no protected group; ir-measures compatible ([code](https://github.com/hltcoe/peer_measure)) | the fairness view of the same number |
| [MRC@k](https://arxiv.org/abs/2509.06195) | rank-correlation between the lists returned for semantically identical queries in different languages over the **same** collection; vanilla DPR scores 13.1 (mBERT) / 11.7 (XLM-R) on MultiEuP-v2 | direct measurement of "does the Hindi question reach the same documents as the English one" |
| [NeuCLIRBench](https://arxiv.org/abs/2511.14758) / [NeuCLIR MLIR](https://arxiv.org/abs/2509.14355) | TREC-grade pooled judgments for the unified-ranked-list task | comparable, citable MLIR numbers |
| [XRAG](https://github.com/amazon-science/XRAG) | ships a **mixed English + question-language document** condition, plus response-language correctness as a first-class metric | end-to-end harness for the whole target behaviour |
| [MultiClaim](https://aclanthology.org/2023.emnlp-main.1027/) | genuinely mixed-language corpus (28k posts / 27 languages vs 206k fact-checks / 39 languages, 31k links) with same-language-bias measurement | closest public stand-in for a mixed tenant corpus |
| [MMTEB](https://arxiv.org/abs/2502.13595) | per-language embedding quality across 500+ tasks / 250+ languages | check whether a language's failure is inherent or model-specific before building architecture |

Two orthogonal checks worth running at the same time, because both are invisible to rank@1:

- **Attribution across the language boundary.**
  [XOR-AttriQA](https://arxiv.org/abs/2305.14332) found up to ~47% of exactly-matching cross-lingual
  answers are not attributable to any retrieved passage (Japanese 53.1% attributable, Telugu 93.1%),
  and that a model fine-tuned on ~100 attribution examples detects attribution at 92–96% accuracy —
  a cheap guardrail. [DoGMaTiQ](https://arxiv.org/abs/2605.04458) automates QA-shaped nuggets that
  "decouple the information need from the potentially diverse content that satisfies it", which is
  the only grading form that survives an answer string that can never lexically match its
  foreign-language source.
- **Ingestion quality masquerading as retrieval quality.**
  [Retrieval or Representation?](https://arxiv.org/abs/2603.04238) shows that on VisR-Bench,
  changing only the transcription/preprocessing while holding retrieval fixed moves BM25 Top-5
  accuracy from 20.73% → 47.20% (Arabic) and 39.35% → 85.47% (Japanese) — the latter essentially
  closing the gap to multimodal ColQwen2 (89.98%) and beating dense BGE-M3 (84.33%). **A
  "retrieval" deficit on non-Latin-script documents is very often an OCR/ingestion deficit.** Check
  this before believing any mixed-corpus retrieval number.

---

## 12. Mixed-corpus problems that appear *after* retrieval

Fixing the ranking does not finish the job. Three failures are specific to having several languages
in one context window:

1. **Evidence conflict across languages.**
   [X-MADAM-RAG](https://arxiv.org/abs/2606.12903) targets retrieved Chinese and English evidence
   supporting mutually incompatible answers. On a controlled 300-example benchmark it reaches
   0.9667 strict accuracy with Qwen2.5-7B-Instruct — but on a 100-sample **naturalized** stress test
   the rule-only extractor collapses to **0.0000** and X-MADAM-RAG itself falls to **0.3000**,
   *below* both the naive and evidence-normalized baselines, while a privileged oracle stays
   perfect. Bottleneck isolated as per-document candidate extraction. Their decomposition is worth
   copying: per-document candidate extraction → visible-evidence repair → deterministic candidate
   grouping → conflict-aware aggregation.
2. **Position and language selection bias in the context.**
   [Not All Languages are Equal](https://arxiv.org/abs/2410.21970): English wins multilingual
   knowledge *selection* through selection bias, and **repositioning the English documents** in the
   context measurably mitigates it. [Linguistic Nepotism](https://arxiv.org/abs/2509.13930): models
   given one relevant target-language document and one irrelevant English document cite the
   irrelevant English one, with the gap widest for mid-context documents.
3. **A reasoning penalty from the language mix itself, independent of retrieval.**
   [Crosslingual Capabilities and Knowledge Barriers](https://arxiv.org/abs/2406.16135): on
   mixup-translated MMLU (question and options split across languages), GPT-4 falls 81.82 → 68.61
   (−13.2 points), Mistral-7B −12.35, Llama3-8B −11.92. Fine-tuning on out-of-domain mixed-language
   text recovers only a few points. Expect a ~10–13 point reasoning penalty from mixed-language
   context alone — which is an argument for keeping the *original* question in the generation prompt
   rather than a translated one, and for normalizing the context language (option E / CrossRAG)
   rather than shipping a bilingual context to the generator.

And the answer-language consequence of all of it, measured:
[CrossRAG generates in the correct language consistently more often than
MultiRAG](https://arxiv.org/abs/2504.03616) — mixed-language passages in the prompt are themselves a
cause of wrong-language answers, so a mixed-corpus fix that lands mixed evidence in the context
without normalizing it will trade a retrieval bug for a language-policy bug.

---

## 13. What is genuinely unclaimed here

Stated plainly, so nothing above reads as a novelty claim it is not:

- Chunk-level language tagging as an **explicit retrieval routing signal** has no named, evaluated
  method in this sweep — it exists as plumbing (Elastic, Haystack) and as an analysis variable.
- No modern ablation of **RRF vs Z-score vs logistic-regression merging on a dense per-language
  pipeline** was found. Classical merging results are sparse-retrieval results.
- No work found on **per-tenant, dynamically-composed** mixed-language corpora — every mixed-corpus
  method above assumes a static collection with a known language inventory and available parallel
  data. Note that SHIFT's offsets are per **language pair**, not per corpus, so they precompute once
  globally and dissolve most of that objection; the residue is choosing fusion weights when one
  shard has 3 documents and the other has 3,000.
- No benchmark evaluates a **small mixed-script project corpus** (a handful of English + Hindi
  files) with queries in each language and a required answer-language match. RAGTIME pins output to
  English; NeuCLIRBench uses English queries only; XRAG uses news rather than a user-owned KB.

Everything else in this file is prior art.
