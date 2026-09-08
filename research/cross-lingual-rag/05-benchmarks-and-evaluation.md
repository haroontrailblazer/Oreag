# 05 — Benchmarks and Evaluation for Cross-Lingual RAG

How to measure a system where the corpus is in language A, the question is in language B, and the
answer must come back in language B. Everything below is drawn from published, citable resources.
Where a record does not state Hindi coverage, this file says so rather than guessing.

**The one thing to internalise before reading further:** retrieval rank alone cannot validate this
system. Three independent instruments say so.

- [MLAIRE](https://arxiv.org/abs/2605.07249) shows semantic retrieval quality and query-language
  preference are near-orthogonal and often anti-correlated across 31 retrievers (nDCG↔LPR Pearson
  −0.28 MLQA, −0.38 XQuAD, −0.29 Belebele). On a single-script corpus the two are indistinguishable
  by construction — which is exactly the condition an 80/80 rank-1 result is measured under.
- [XOR-AttriQA](https://arxiv.org/abs/2305.14332) finds up to ~47% of cross-lingual answers that
  **exactly match the gold reference** are not attributable to any retrieved passage (Japanese;
  attribution ranges 53.1% JA to 93.1% TE). Correct answer + correct rank ≠ grounded.
- [On the Consistency of Multilingual Context Utilization in RAG](https://arxiv.org/abs/2504.00597)
  finds 24.85% of Arabic queries answered **correctly but in the wrong language**, despite an
  explicit "Please respond in Arabic" instruction. Answer-language correctness is a separate axis
  that retrieval metrics cannot see.

For calibration: published cross-lingual end-to-end numbers on the same task shape sit at
18.7 F1 ([XOR QA MT baseline](https://aclanthology.org/2021.naacl-main.46/)),
34.7 F1 ([CORA](https://arxiv.org/abs/2107.11976)),
42.4 F1 ([CLASS](https://aclanthology.org/2024.emnlp-main.770/)),
~23% F1 on African languages ([AfriQA](https://arxiv.org/abs/2305.06897)), and
37.4 Token-F1 for PaLM-2-L across 28 Indic languages
([IndicGenBench](https://arxiv.org/abs/2404.16816)). Nothing near-perfect. A near-perfect in-house
number is a signal about the probe set, not about the system.

---

## 1. Benchmark inventory

`XL?` = does the benchmark actually put the question in a different language from the evidence?
`Hindi?` = **U** means the source record does not state it; confirm from the release before relying on it.

### 1.1 Cross-lingual open-retrieval QA — the target task

| Benchmark | Measures | Languages | XL? | Hindi? | Get it |
|---|---|---|---|---|---|
| [XOR QA / XOR-TyDi](https://aclanthology.org/2021.naacl-main.46/) | The whole target behaviour. 3 sub-tasks: XOR-Retrieve (rank English passages for a non-English question), XOR-EnglishSpan, XOR-Full (answer **in the question's language**) | 7 (Ar, Bn, Fi, Ja, Ko, Ru, Te), ~40k questions | Yes, by construction — built from TyDi QA questions with **no same-language answer** | No | [github.com/AkariAsai/XORQA](https://github.com/AkariAsai/XORQA), [nlp.cs.washington.edu/xorqa](https://nlp.cs.washington.edu/xorqa) |
| [MKQA](https://aclanthology.org/2021.tacl-1.82/) | 10k questions aligned across 26 languages (260k pairs). Answers are a **language-independent** entity/canonical representation | 26 typologically diverse | Usable as XL (one shared English corpus) | U | [github.com/apple/ml-mkqa](https://github.com/apple/ml-mkqa), CC BY-SA 3.0 |
| [MIA 2022 Shared Task](https://aclanthology.org/2022.mia-1.11/) | Same task as a 16-language leaderboard; adds Tagalog + Tamil annotation | 16 | Yes | U | [github.com/mia-workshop/MIA-Shared-Task-2022](https://github.com/mia-workshop/MIA-Shared-Task-2022) |
| [AfriQA](https://arxiv.org/abs/2305.06897) | XOR QA where cross-lingual content is the *only* high-coverage source | 10 African langs, 12,239 questions / 8,892 answerable | Yes; pivots EN (8) and FR (2) | No | [github.com/masakhane-io/afriqa](https://github.com/masakhane-io/afriqa) |
| [GenTyDiQA](https://aclanthology.org/2022.aacl-main.27/) | Full-sentence generated answers from multi-language passages | 5 (Ar, Bn, En, Ja, Ru) | Yes | No | via the AACL 2022 paper |

**Key numbers to beat.** XOR-Retrieve DPR: R@5kt 72.1 with *human*-translated queries, 67.2 with
Google MT, 50.0 with an in-house MT system (R@2kt 65.1 / 64.3 / 43.5) —
[XOR QA](https://aclanthology.org/2021.naacl-main.46/). That spread is the single best published
evidence that translation quality, not retrieval, dominates a translate-the-query pipeline.
[CORA](https://arxiv.org/abs/2107.11976) reaches R@2kt 69.3 / R@5kt 76.5 with **no translation at
all**; [CLASS](https://aclanthology.org/2024.emnlp-main.770/) reaches 71.6 / 78.2.
[AfriQA](https://arxiv.org/abs/2305.06897) is the hard end: pure mDPR 19.0% R@10, Google-Translate
query translation 62.4%, human question translation 67.6%, hybrid sparse+dense with human
translation 73.4%.

**MKQA caveat that matters.** Its answers are deliberately decoupled from any language-specific
passage, so MKQA **cannot score whether the answer came back in the user's language**. Use it for
retrieval and answer *correctness*, never for language policy.

### 1.2 Monolingual retrieval — the control condition, not evidence of cross-lingual skill

| Benchmark | Measures | Languages | XL? | Hindi? | Get it |
|---|---|---|---|---|---|
| [MIRACL](https://aclanthology.org/2023.tacl-1.63/) | Ad hoc retrieval, ~77k queries, 726k native-speaker judgments over Wikipedia | 18 | **No** — the paper states "our focus is monolingual retrieval … as opposed to cross-lingual retrieval" | Yes (MIRACL Hindi baselines cited by [IndicIRSuite](https://arxiv.org/abs/2312.09508)) | [github.com/project-miracl/miracl](https://github.com/project-miracl/miracl) |
| [Mr. TyDi](https://aclanthology.org/2021.mrl-1.12/) | First multilingual dense-retrieval benchmark; origin of "mDPR loses to BM25 outside English" | 11 | No | U | via the MRL 2021 paper |
| [Hindi-BEIR](https://arxiv.org/abs/2408.09437) | 15 datasets, 8 tasks, Hindi retrieval | Hindi only | No | Yes | via paper; model [NLLB-E5](https://arxiv.org/abs/2409.05401) |
| [IndicRAGSuite / IndicMSMarco](https://arxiv.org/abs/2506.01615) | 1000 manually translated MS MARCO-dev queries per language | 13 (retrieval), 19 (training) | **No** — explicitly "IndicMSMARCO supports monolingual retrieval" | Yes | [HF collection](https://huggingface.co/collections/ai4bharat/indicragsuite-683e7273cb2337208c8c0fcb) |
| [MMTEB / MTEB(Indic)](https://arxiv.org/abs/2502.13595) | 500+ tasks, 250+ languages; MTEB(Indic) is a 23-task Indic split | 250+ | Mostly no (same-language query/corpus) | Yes | [github.com/embeddings-benchmark/mteb](https://github.com/embeddings-benchmark/mteb) |

Reference points: MIRACL 18-language dev set — BM25 nDCG@10 0.393 / R@100 0.787, mDPR 0.415 / 0.788,
**hybrid BM25+mDPR 0.578 / 0.889** ([MIRACL](https://aclanthology.org/2023.tacl-1.63/)). Dense alone
barely beats lexical in multilingual settings; fusion is where the win is.
[BGE-M3](https://aclanthology.org/2024.findings-acl.137/) scores MIRACL avg nDCG@10 71.5 fused
(dense 69.2 / sparse 53.9 / multi-vec 70.5) and MKQA R@100 75.5 against one shared English
Wikipedia, vs mE5-large 70.9. On MTEB(Indic),
[multilingual-e5-large-instruct](https://arxiv.org/abs/2502.13595) (560M) ranks first at Borda 209 /
avg 70.2. IndicMSMarco MRR tops out at 0.52 Hindi (mE5-large), 0.50 Telugu, 0.49 Malayalam/Tamil
([IndicRAGSuite](https://arxiv.org/abs/2506.01615)) — that is the realistic ceiling for Indic
retrieval today, monolingual.

### 1.3 Mixed-language corpus (MLIR) — the open limit, already instrumented

| Benchmark | Measures | Languages | Hindi? | Get it |
|---|---|---|---|---|
| [LAReQA](https://aclanthology.org/2020.emnlp-main.477/) | Answer retrieval from a **single mixed-language candidate pool**; introduces weak vs **strong** cross-lingual alignment | XQuAD-R 11, MLQA-R 7 | U | Google Research release, via paper |
| [MLAIRE](https://arxiv.org/abs/2605.07249) | Protocol that **disentangles cross-lingual semantics from query-language preference**; LPR + Lang-nDCG + 4-way failure decomposition | Belebele 122, XQuAD 12, MLQA 7 | Likely via Belebele (U) | via paper |
| [TREC NeuCLIR](https://arxiv.org/abs/2509.14355) | MLIR task: one unified ranked list over ~2M fa + ~3M zh + ~5M ru docs, 51 topics, ~1,999 judgments/topic. Plus a RAG report-generation task | zh, fa, ru | No | [neuclir.github.io](https://neuclir.github.io/) |
| [NeuCLIRBench](https://arxiv.org/abs/2511.14758) | Consolidated 2022–24 collection: 250,128 judgments, ~150 mono/cross queries, 100 multilingual; ships a **neural fusion first-stage baseline** | zh, fa, ru (+MT English) | No | via paper |
| [TREC 2025 RAGTIME](https://arxiv.org/abs/2602.10024) | "search all four document collections and produce a single unified ranked list"; ~1,000,095 CommonCrawl News docs **per language**; 13 teams / 125 runs | ar, zh, en, ru | No | via paper / TREC |
| [CLIRMatrix](https://aclanthology.org/2020.emnlp-main.340/) | BI-139 (19,182 language pairs), MULTI-8 (genuine mixed pool), 49M queries | 139 | Likely (U) | via paper |
| [MultiClaim](https://aclanthology.org/2023.emnlp-main.1027/) | 28k posts in 27 langs against 206k fact-checks in 39 langs, 31k links — a real mismatched mixed corpus. Defines **Same-Language Bias (SLB)** | 27 / 39 | U | via paper |

**The result that names the bug.** [LAReQA](https://aclanthology.org/2020.emnlp-main.477/) mAP on
XQuAD-R / MLQA-R with all languages pooled into one index: En-En 0.29/0.36, X-X 0.23/0.26,
X-X-mono 0.52/0.49, **X-Y 0.66/0.49**, Translate-Test 0.72/0.58. Training on translated data with
*monolingual* positive pairs (X-X, 0.23) is **worse than English-only training** (0.29). Only X-Y —
where question and answer are in *different* languages, forcing the model to accept a foreign
passage as correct — repairs mixed-pool retrieval.

**The magnitude, in production terms.**
[The Cross-Lingual Cost](https://arxiv.org/abs/2507.07543) builds a balanced Arabic-English corporate
corpus (Legal, Travel — deliberately not Wikipedia, to block parametric leakage) and reports M-E5
Hit@20 dropping 42% (Legal) / 33% (Travel) cross-lingually, with end-to-end accuracy down 40% / 37%;
BGE-M3 drops 33% / 13%. A language-oracle ablation isolates the cause as **document–document**
language mismatch inside one index.
[All Languages Matter](https://arxiv.org/abs/2604.20199) quantifies the headroom: >70% of BGE
reranker top-5 documents come from English + the query language alone, and Recall@3-gram averages
48.9 vs a 63.6 oracle — worst exactly on non-Latin scripts (ko 25.5/41.0, th 26.4/44.1, ja 29.2/47.9).
[TREC NeuCLIR 2024](https://arxiv.org/abs/2509.14355) puts a number on the architectural penalty:
best MLIR nDCG@20 **0.545**, against 0.664 / 0.698 / 0.593 for the same collections searched
one language at a time.

### 1.4 Cross-lingual RAG generation suites, 2025–2026

| Suite | Measures | Languages | Hindi? | Get it |
|---|---|---|---|---|
| [XRAG](https://arxiv.org/abs/2505.10089) | The closest public match to the target config. Two conditions: non-English question over **English-only** docs, and over a **mixed** English+question-language set. Scores **Response Language Correctness** as a first-class metric | 5 (en, de, es, zh, ar), ~1,000 verified QA pairs per language pair, News Crawl Jun–Nov 2024 | No | [github.com/amazon-science/XRAG](https://github.com/amazon-science/XRAG), HF `AmazonScience/XRAG` |
| [MIRAGE-Bench](https://arxiv.org/abs/2410.13716) | Arena-style multilingual RAG **generation**; 11,195 eval / 39,763 training pairs; surrogate judge over 7 heuristic features incl. **language detection** and a separate **English detection** feature | 18 (MIRACL set) | **Yes** | [github.com/vectara/mirage-bench](https://github.com/vectara/mirage-bench) |
| [MEMERAG](https://arxiv.org/abs/2502.17163) | Meta-evaluation: validates that your LLM judge is trustworthy **per language**. 250 questions × 5 langs, 2,322 expert-annotated sentences, faithfulness (3 coarse + 10 fine-grained error types) and relevance | en, de, es, fr, **hi** | **Yes** | [github.com/amazon-science/MEMERAG](https://github.com/amazon-science/MEMERAG) |
| [NoMIRACL](https://arxiv.org/abs/2312.11361) | Abstention: relevant subset → error rate; non-relevant subset → **hallucination rate**. 31 native-speaker annotators | 18 (MIRACL set) | Yes | [github.com/project-miracl/nomiracl](https://github.com/project-miracl/nomiracl) |
| [Futurepedia](https://arxiv.org/abs/2410.21970) | 3 tasks: monolingual extraction, **cross-lingual transfer**, **multilingual knowledge selection** (which language's evidence the model actually uses) | 8, parallel | U | via paper |
| [BordIRLines](https://arxiv.org/abs/2410.01171) | 720 queries, 251 disputed territories, 19,916 query-doc pairs over 7,436 passages; 5 retrieval modes incl. `en_only` | 49 | Likely (U) | via paper |
| [M4-RAG](https://arxiv.org/abs/2512.05959) | 80k+ image-question pairs, 42 languages, 56 dialects, 189 countries, over millions of curated multilingual docs | 42 | Likely (U) | via paper |
| [Double-Bench](https://arxiv.org/abs/2508.03644) | Document-shaped RAG: 3,276 docs / 72,880 pages, 5,168 single- and multi-hop queries, **component-level** scoring | 6 | U | via paper |
| [X-MADAM-RAG](https://arxiv.org/abs/2606.12903) | Mixed-corpus **evidence conflict**: retrieved zh and en evidence supporting incompatible answers | zh, en | No | via paper |
| [MMed-Bench-IR](https://arxiv.org/abs/2606.24200) | Medical retrieval against "predominantly English evidence corpora"; separates cross-lingual alignment / concept discrimination / evidence retrieval | 6, 6,127 queries | U | via paper |
| [Agri-Query](https://arxiv.org/abs/2508.18093) | 108 questions **balanced 54 answerable / 54 unanswerable** over a 165-page manual — hallucination is scored, not just recall | en, de, fr | No | via paper |

**XRAG is the one to run first for language policy.** It reports the wrong-language failure rate
directly in the English-only-retrieval setting: ~5% for GPT-4o and Command-R+, ~15% for Claude 3.5
Sonnet, ~35% for Mistral-large ([XRAG](https://arxiv.org/abs/2505.10089)). Its questions genuinely
require the corpus — GPT-4o scores 6.3% without retrieval against 85% human accuracy.

**BordIRLines and RAGTIME both pin output to English.** BordIRLines instructs "your answers should
always be primarily in English" ([paper](https://arxiv.org/abs/2410.01171)); RAGTIME requires English
reports from Arabic/Chinese/Russian sources with **no metric penalising wrong-language output**
([paper](https://arxiv.org/abs/2602.10024)). Use them for retrieval and grounding, never for step 4.

### 1.5 Answer-language and language-confusion benchmarks

| Benchmark | Measures | Languages | Hindi? | Get it |
|---|---|---|---|---|
| [Language Confusion Benchmark (LCB)](https://aclanthology.org/2024.emnlp-main.380/) | Whether the model answers in the requested language. **Monolingual** setting = match the query; **cross-lingual** setting = obey an explicit language instruction. Metrics: LPR (line-level), WPR (word-level), LCPR (harmonic mean) | 15 typologically diverse | Reported yes — confirm from the repo | [github.com/for-ai/language-confusion](https://github.com/for-ai/language-confusion) |
| [Language Confusion Entropy](https://arxiv.org/abs/2410.13237) | Graded *degree* of confusion from the output language distribution, weighted by typology and lexical similarity — not binary pass/fail | validated against LCB | U | via paper |
| [MTM-Bench](https://arxiv.org/abs/2605.27649) | Fully crossed (instruction-lang, **content-lang**, response-lang) triplets — 27 combinations, 2,430 instances/model, 20 LLMs. Decomposes into semantic correctness, target-language adherence, constraint satisfaction, contamination ratio, joint success | 27 combos | U | via paper |

**The LCB numbers that decide your generator.** Cross-lingual line-level pass rate: Llama 3 70B-Instruct
**30.3%**, Llama 2 70B-Instruct 38.4%, GPT-4o 92.4%, Command R+ Refresh 95.4%. Even in the easier
monolingual setting the Llama models sit at 46.0–48.3% LPR while GPT-4 Turbo hits 99.3%
([LCB](https://aclanthology.org/2024.emnlp-main.380/)). **Model choice alone moves wrong-language
output by ~60 points.** Few-shot is the cheapest lever: Command R Base cross-lingual LPR goes
1.1 (0-shot) → 20.9 (1-shot) → 90.7 (5-shot). Confusion also worsens with longer prompts and higher
temperature (WPR down to 72.0% at high T), and **beam search consistently hurts** cross-lingual LPR.

### 1.6 Indic-specific resources

| Resource | Measures | Languages | Retrieval? | Get it |
|---|---|---|---|---|
| [IndicGenBench — XorQA-In-Xx](https://arxiv.org/abs/2404.16816) | **Exactly the target task shape**: (Indic question, English passage, Indic answer). XorQA-In-En is the same with English answers | 28 Indic, 32k examples, splits 2.8k/14k/15.1k | **No** — gold English passages are supplied, so no index is exercised | [github.com/google-research-datasets/indic-gen-bench](https://github.com/google-research-datasets/indic-gen-bench) |
| [INDIC QA BENCHMARK](https://arxiv.org/abs/2407.13522) | Context-grounded extractive + abstractive QA; compares direct multilingual vs **translate-test** | 11 Indian | Context supplied | via paper |
| [HEALTH-PARIKSHA](https://arxiv.org/abs/2410.13671) | Real patient queries against an **English-only** KB (12 doctor-curated PDFs, 1000-token chunks, ada-002, top-3), with an explicit answer-language instruction | Indian English, hi, ta, te, kn | Yes, real RAG | via paper |
| [PI-Indic-Align](https://github.com/aryashah2k/PI-Indic-Align) | One of the very few Indic sets with an explicit **cross-lingual retrieval split** | 12 Indic | Yes | GitHub |
| [Anveshana](https://arxiv.org/abs/2505.19494) | English queries → Sanskrit documents; head-to-head QT vs DT vs Direct Retrieval | en→sa, 3,400 pairs / 334 docs | Yes | [HF dataset](https://huggingface.co/datasets/manojbalaji1/anveshana) |
| [MILU](https://arxiv.org/abs/2411.02538) | 8 domains, 41 subjects, culturally grounded | 11 Indic | No | via paper |
| [IndicParam](https://arxiv.org/abs/2512.00333) | 13,000+ human-curated MCQs, low/extremely-low-resource + a Sanskrit-English code-mixed set | 11 | No | via paper |
| [IndicSQuAD](https://arxiv.org/abs/2505.03688) | SQuAD translated with **answer-span alignment preserved** — a recipe for manufacturing aligned QA data | 9 Indic | No | via paper |
| [IndicNLG](https://arxiv.org/abs/2203.05437) | ~8M examples, 5 NLG tasks; the **question-generation** split generates in-language queries for a given passage | 11 Indic | No | via paper |
| [SqCLIR @ FIRE 2024/2025](https://dl.acm.org/doi/full/10.1145/3734947.3735669) | Spoken-query **cross-lingual** retrieval, query language ≠ document language | hi, bn, gu, kn, en | Yes (speech input) | ACM DL |
| [FIRE MSIR 2014–16](https://link.springer.com/chapter/10.1007/978-3-319-73606-8_3) | Single collection with the same language in **two scripts** (Devanagari + Roman), queried in either | Hindi + code-mixed | Yes, pre-neural | Springer |

**The Hindi headline number.** XorQA-In-Xx is the hardest task in IndicGenBench: the best model,
PaLM-2-L, reaches only **37.4 Token-F1** one-shot averaged over 28 Indic languages, and every model
trails its own English performance by 20+ points ([IndicGenBench](https://arxiv.org/abs/2404.16816)).
The same paper isolates the direction asymmetry — generating *into* a low-resource language degrades
far more than understanding it (FLORES en→xx 56.9→41.9 high-to-low resource; xx→en only 68.2→62.6) —
which is precisely the risk in step 4.

**The number that justifies gating at all.**
[INDIC QA BENCHMARK](https://arxiv.org/abs/2407.13522) Llama-3 extractive F1: Assamese **33.01
translate-test vs 21.29 direct** (translation nearly doubles it), but Hindi **46.76 direct vs 26.22
translate-test** (translation nearly halves it). Corroborated by
[How and Where to Translate](https://arxiv.org/abs/2507.22923): on Hindi with Llama-3.1-8B *every*
translation strategy made accuracy worse, by up to 10.9 points, while French on BLOOMZ-7b1 gained
13.4. Unconditional translation is measurably harmful on Hindi specifically.

**HEALTH-PARIKSHA scale caveat before reusing the data:** of 749 question/GT-answer pairs, 666 are
English and only 19 Hindi, 27 Tamil, 14 Telugu, 23 Kannada
([paper](https://arxiv.org/abs/2410.13671)).

### 1.7 Script, romanisation and code-switching — the second hole in a Unicode gate

| Resource | Finding | Get it |
|---|---|---|
| [Bhasha-Abhijnaanam / IndicLID](https://aclanthology.org/2023.acl-short.71/) | LID for all 22 scheduled Indian languages in native **and** romanized script: 98.55% accuracy native, **80.40% romanized** | [ai4bharat.iitm.ac.in/indiclid](https://ai4bharat.iitm.ac.in/indiclid) |
| [Lost in Transliteration](https://arxiv.org/abs/2505.08411) | BGE-M3 loses **97% of MRR@10** on Latinized Chinese (0.2342→0.0078) and 49% on Latinized Russian; only a 50/50 native+Latinized fine-tune repairs it without wrecking the native side | via paper |
| [Script Gap](https://arxiv.org/abs/2512.10780) | Romanized input degrades LLM performance by up to **24 points** vs native script across 5 Indian languages + Nepali | via paper |
| [CS-MTEB / CSR-L](https://arxiv.org/abs/2604.17632) | Code-switching costs robust multilingual retrievers up to **27%** across 11 tasks; e5-large-v2 Japanese reranking 60.17 → 25.75; vocabulary expansion is insufficient | via paper |
| [MiLQ](https://arxiv.org/abs/2505.16631) | Counterpoint worth testing: **mixed-language queries retrieve English documents far better than native-script ones** — BM25 MAP@100 38.35 vs 12.35 (low-resource), 34.92 vs 8.56 (high-resource); monolingual ceiling 48.71 | via paper |

A Unicode script check cannot see Hinglish. On an Indian user base that is not an edge case. MiLQ
also suggests Hinglish input may already be *helping* reach the English half — measure before fixing.

---

## 2. Metrics

### 2.1 Cross-lingual retrieval quality

| Metric | Definition / where used | Notes |
|---|---|---|
| **R@2kt / R@5kt** | Fraction of questions where a gold answer string appears in the top 2k / 5k **tokens** of retrieved English text — [XOR-Retrieve](https://aclanthology.org/2021.naacl-main.46/) | The canonical cross-lingual retrieval metric. Token-budget-based, so it is comparable across chunkings |
| **nDCG@10 / @20** | [MIRACL](https://aclanthology.org/2023.tacl-1.63/), [NeuCLIR](https://arxiv.org/abs/2509.14355), MLIR generally | Requires graded judgments |
| **Recall@k / Hit@k** | [AfriQA](https://arxiv.org/abs/2305.06897) R@10, [The Cross-Lingual Cost](https://arxiv.org/abs/2507.07543) Hit@20 | Hit@20 is the standard mixed-corpus regression metric |
| **MRR@10 / MRR@100** | [Mr. TyDi](https://aclanthology.org/2021.mrl-1.12/), [IndicMSMarco](https://arxiv.org/abs/2506.01615), [LaKDA](https://aclanthology.org/2024.mrl-1.23/) | |
| **MAP** | [LAReQA](https://aclanthology.org/2020.emnlp-main.477/) mixed pool, CLEF-lineage MLIR | |
| **char 3-gram recall** | Answer-overlap metric that survives translation and morphology — [DKM-RAG](https://arxiv.org/abs/2502.11175), [DELTA](https://arxiv.org/abs/2601.02956), [LAURA](https://arxiv.org/abs/2604.20199), [TR-RAG](https://arxiv.org/abs/2607.02966) | **Use this, not EM**, when the answer is in a different language from the evidence |
| **flexible EM (fEM)** | [Ranaldi et al.](https://arxiv.org/abs/2504.03616), [LcRL](https://arxiv.org/abs/2601.14896), [CroSearch-R1](https://arxiv.org/abs/2604.25182) | The comparator for MKQA/XOR-TyDi end-to-end numbers |

### 2.2 Language-preference metrics — the ones that separate semantics from language match

These are the instruments a mixed-corpus system lives or dies by. Report at least one alongside every
retrieval number.

| Metric | What it isolates | Source |
|---|---|---|
| **LPR (Language Preference Rate) + Lang-nDCG** | How much of a retrieval score is query-language match rather than meaning. Comes with a 4-way failure decomposition | [MLAIRE](https://arxiv.org/abs/2605.07249) |
| **MLRS (MultiLingualRankShift)** | How much a document's rank **improves when translated into the query language** — a direct diagnostic for the mixed-corpus bug. Measured English preference 47.70 vs 35–38 for every other language | [Investigating Language Preference of mRAG](https://arxiv.org/abs/2502.11175) |
| **DeLP** | Language preference **calibrated** against exposure bias, gold-availability prior and cultural/topic locality. After debiasing, the effect moves to the diagonal (Lq=Ld): retrievers favour query↔document language *match*, not English per se | [DELTA](https://arxiv.org/abs/2601.02956) |
| **PEER (Probability of Equal Expected Rank)** | Kruskal-Wallis test of whether documents in different languages are ranked fairly in one list, with **no protected language** designated. Drop-in `ir-measures` compatible | [Language Fairness in MLIR](https://arxiv.org/abs/2405.00978), [github.com/hltcoe/peer_measure](https://github.com/hltcoe/peer_measure) |
| **MRC@k (Mean Rank Correlation)** | Do semantically identical queries in different languages return equivalent ranked lists over the same collection? Vanilla DPR scores MRC@5 of 13.1 (mBERT) / 11.7 (XLM-R) on MultiEuP-v2 — top-5 lists are largely **not** shared across query languages | [LaKDA](https://aclanthology.org/2024.mrl-1.23/) |
| **SLB (Same-Language Bias)** | Systematic over-ranking of candidates in the query's own language; BM25-Original has the highest SLB of all methods tested, and without filtering it would have *appeared* to beat MPNet (S@10 51.9 vs 38.5) | [MultiClaim](https://aclanthology.org/2023.emnlp-main.1027/) |

The anti-correlation is the whole point: on MLQA, multilingual-e5-large scores 96.15% nDCG at 99.92%
LPR while Qwen3-Embedding-8B scores 68.64% nDCG at only 53.00% LPR, and BM25 27.92% nDCG at 93.68%
LPR ([MLAIRE](https://arxiv.org/abs/2605.07249)). A retriever can be semantically excellent and
language-blind, or semantically weak and language-obedient. One number cannot tell you which you have.

### 2.3 Answer-language accuracy and consistency

| Metric | Definition | Source |
|---|---|---|
| **LPR / WPR / LCPR** | Line-level pass rate (% responses with no wrong-language line), word-level pass rate, harmonic mean | [LCB](https://aclanthology.org/2024.emnlp-main.380/) |
| **Correct Language Rate (CLR)** | % of answers returned in the query's language. [LcRL](https://arxiv.org/abs/2601.14896) reports 99.1% vs 95.6% for mSearch-R1 on MKQA | [Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/), [LcRL](https://arxiv.org/abs/2601.14896) |
| **Response Language Correctness** | Same idea, scored as a first-class benchmark dimension | [XRAG](https://arxiv.org/abs/2505.10089) |
| **Language Consistency** | Share of answers actually written in the target language, measured with the evidence language varied | [Language Drift / SCD](https://arxiv.org/abs/2511.09984) |
| **Language Confusion Entropy** | Graded degree rather than binary pass/fail, weighted by typological relatedness | [paper](https://arxiv.org/abs/2410.13237) |

**Measurement tooling.** [XRAG](https://arxiv.org/abs/2505.10089) uses `lingua`;
[Ranaldi et al.](https://arxiv.org/abs/2504.03616) use OpenLID;
[GlotLID](https://github.com/cisnlp/GlotLID) supports 2,000+ language labels, which matters for a
40-language range. For Indic specifically, [IndicLID](https://aclanthology.org/2023.acl-short.71/)
is the only LID that handles romanized text — and it drops to 80.40% accuracy there, so treat
romanized-query language labels as noisy.

**Score at sentence level, not response level.** A whole-response LID scores a code-switched
Hindi/English answer as a pass. [Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/)
document persistent named-entity code-switching in non-Latin scripts even at >95% CLR, and
[Language Confusion Gate](https://arxiv.org/abs/2510.17555) explicitly distinguishes harmful mixing
from legitimate code-switching. LCB's line-level LPR plus word-level WPR is the right shape.

**Baselines to compare against.** Context language alone moves consistency enormously: on HotpotQA,
swapping retrieved context from Chinese to English drops Chinese language consistency from **92.0%
to 68.4%** with the target-language instruction still in the prompt
([Language Drift](https://arxiv.org/abs/2511.09984)). Prompt-side fixes get you far but not all the
way: translating the prompt into the user language plus an explicit "generate the response in the
user language" instruction lifts Command-R-35B from answering in English for ~50% of non-English
queries to >95% CLR ([Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/)). And prompting
is provably not sufficient — 24.85% of Arabic queries answered correctly but in the wrong language
*despite* an explicit instruction, with a two-step answer-then-translate prompt and larger models
(Gemma3-27B-IT, GPT-5-nano) both failing to fix it: "an inherent decoding limitation"
([Consistency of Multilingual Context Utilization](https://arxiv.org/abs/2504.00597)).

### 2.4 Faithfulness and attribution to foreign-language evidence

The core difficulty: a Hindi answer will never lexically match its English source, so string overlap
against the passage is meaningless.

| Instrument | What it gives you |
|---|---|
| [XOR-AttriQA](https://arxiv.org/abs/2305.14332) | ~10,000 human-annotated (query, passage, answer) attribution tuples in bn, fi, ja, ru, te, generated by CORA. The cheap guardrail: PaLM 2 fine-tuned on only ~100 attribution examples reaches **92–96% accuracy / 95–98% ROC AUC** at detecting attribution |
| [ARGUE](https://arxiv.org/abs/2602.10024) (TREC RAGTIME) | Sentence support (precision) + nugget coverage (recall) + F1, with three-way human support judgments per sentence-document pair. Top NeuCLIR report-generation systems reached only ~0.3 citation precision and <0.5 nugget recall |
| [DoGMaTiQ](https://arxiv.org/abs/2605.04458) | Automates the nuggets. **QA-shaped** nuggets "decouple the information need (the question) from the potentially diverse content that satisfies it (its answers)" — the only grading form that survives an answer string that can never match its English source. Validated on NeuCLIR and RAGTIME |
| [MEMERAG](https://arxiv.org/abs/2502.17163) | Validates that your LLM judge is trustworthy **in Hindi**. Sentence-level human annotation is reliable given guidelines: faithfulness Gwet's AC1 0.84–0.93 / Fleiss κ 0.70–0.88, relevance AC1 0.95–1.0, vs 0.34–0.42 κ in prior work. The best judge **differs by language** — GPT-4o mini best in English, Qwen 2.5 32B strongest elsewhere; guidelines + CoT consistently beat zero-shot |
| [MIRAGE-Bench](https://arxiv.org/abs/2410.13716) | A ready-made 7-feature scorecard (language detection, English detection, citation Recall@10/MAP@10, multilingual-NLI support, reranker score, overlap, fluency) whose surrogate judge reproduces GPT-4o preferences at **Kendall τ = 0.909** — rank generation quality without paying for an LLM judge every run |

**Known tooling gap:** [RAGAS](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/)
documents faithfulness, context precision/recall, noise sensitivity and factual correctness — but no
language-consistency or answer-language metric. The most-used RAG eval library cannot score step 4
out of the box. [BERGEN](https://github.com/naver/bergen) supports the query-language-vs-datastore-
language axis but its documented metrics (Match, EM, LLMEval) include no language check either.

### 2.5 Hallucination and abstention in low-resource languages

| Instrument | What it measures |
|---|---|
| [NoMIRACL](https://arxiv.org/abs/2312.11361) | Two-sided: **hallucination rate** on the non-relevant subset (does the model admit no passage is relevant?) and **error rate** on the relevant subset (does it recognise a good passage?). LLaMA-2 and Orca-2 exceed **88% hallucination**; the low-hallucination models (Mistral, LLaMA-3) swing to **74.9% error rate**. Across 18 languages, no open model balances the two. This is the instrument for a weak-similarity gate |
| [Agri-Query](https://arxiv.org/abs/2508.18093) | 54 answerable / 54 unanswerable, so abstention is scored by construction. Hybrid RAG (BM25 + dense, RRF) beats 128K long-context prompting on the same model: Gemini 2.5 Flash 0.880 vs 0.694 on English |
| [Multi-FAct](https://arxiv.org/abs/2402.18045) | FActScore by language: GPT-4 spans 0.487 (zh, ko) to 0.633 (es), English 0.615. The sharper gap is **volume** — low-resource languages emit far fewer correct facts at comparable score. Also: estimation error scales linearly with Wikipedia article length, and **ensembling multiple non-English Wikipedias beats any single one** |
| [Better To Ask in English? / IndicQuest](https://arxiv.org/abs/2504.20022) | 200 QA per language, 4,000 pairs, English + 19 Indic, scored 1–5. Generator size dominates: Gemma-2-2B 3.11 English vs a 1.02 floor; Llama-3.1-8B 3.35 vs 1.78; Gemma-2-9B 3.69 vs 3.16; **GPT-4o 4.24 English / 4.32 Hindi / 4.11 Marathi** — essentially no English advantage |
| [X-MADAM-RAG](https://arxiv.org/abs/2606.12903) | Mixed-corpus evidence conflict. The honest number is the negative one: on a 100-sample naturalized stress test the rule-only extractor scores **0.0000** and the proposed method 0.3000 strict accuracy, isolating per-document candidate extraction as the bottleneck |

### 2.6 Confounds you must control or your numbers are worthless

1. **Parametric leakage.** Wikipedia-derived corpora let the model answer from memory.
   [The Cross-Lingual Cost](https://arxiv.org/abs/2507.07543) uses real corporate Legal and Travel
   corpora "deliberately to avoid parametric-memory leakage"; [XRAG](https://arxiv.org/abs/2505.10089)
   uses post-cutoff news and verifies GPT-4o scores 6.3% without retrieval.
2. **Structural benchmark priors.** [DeLP](https://arxiv.org/abs/2601.02956) shows raw multilingual
   RAG measurements are distorted by exposure bias, gold-availability prior and cultural topic
   locality. This is the main methodological objection anyone will raise against an in-house number.
3. **Semantics/language-preference conflation.** [MLAIRE](https://arxiv.org/abs/2605.07249) — a
   single-script corpus cannot distinguish them.
4. **Retrieval bias is a function of query language, not just meaning.**
   [Investigating Information Inconsistency in Multilingual ODQA](https://arxiv.org/abs/2205.12456)
   shows the same question in different languages surfaces *different* passages on TyDi QA and
   XOR-TyDi, because same-topic documents in different languages carry different content.
5. **Ingestion is often mistaken for retrieval.**
   [Retrieval or Representation?](https://arxiv.org/abs/2603.04238) moves BM25 Top-5 on VisR-Bench
   from 20.73%→47.20% (Arabic) and 39.35%→85.47% (Japanese) by changing **only** the
   transcription/preprocessing, holding retrieval fixed. A "retrieval" deficit on non-Latin-script
   documents is very often an OCR/ingestion deficit.
6. **LID degrades on the exact inputs you care about** — short, noisy, code-switched, romanized
   ([IndicLID](https://aclanthology.org/2023.acl-short.71/): 98.55% native vs 80.40% romanized).
7. **Mixed-language reasoning carries a penalty independent of retrieval.**
   [Crosslingual Knowledge Barriers](https://arxiv.org/abs/2406.16135): GPT-4 falls 81.82→68.61 on
   mixup-translated MMLU (−13.2 pts), Mistral-7B −12.35, Llama3-8B −11.92. Budget ~10–13 points of
   degradation from the language mix alone before blaming the retriever. (This also *validates*
   keeping the original question in the generation prompt rather than the translated one.)

---

## 3. Proposed evaluation plan

Built only from the datasets named above. Ordered so that each phase can kill the next one.
Phases 0–3 are a week of work; 4–6 are the substance; 7 is the only genuinely unpublished
measurement in the list.

### Phase 0 — Replace the in-house probe set (blocking)

**Claim under test:** that any in-house rank-1 number means what it appears to mean.

Run the existing pipeline unchanged on
[XOR-Retrieve](https://github.com/AkariAsai/XORQA) (7 languages, English Wikipedia corpus) and report
**R@2kt and R@5kt**. Published comparators, same metric, same data:

| System | R@2kt | R@5kt |
|---|---|---|
| DPR + in-house MT queries | 43.5 | 50.0 |
| DPR + Google MT queries | 64.3 | 67.2 |
| DPR + **human**-translated queries | 65.1 | 72.1 |
| [CORA](https://arxiv.org/abs/2107.11976) (no translation) | 69.3 | 76.5 |
| [CLASS](https://aclanthology.org/2024.emnlp-main.770/) (no translation) | 71.6 | 78.2 |

Source for rows 1–3: [XOR QA](https://aclanthology.org/2021.naacl-main.46/).

**Pass bar:** land inside 64–72 R@2kt. **Failure signal:** anything near 100 means the probe set, not
the system, is being measured — expect near-unique gold passages in a small corpus, or queries that
are parallel translations of each other (which measures translation-invariance, not retrieval).

Add the ablation that decides whether the translation path earns its 36 model calls: run the identical
evaluation with the query **untranslated** through a shared multilingual encoder
([BGE-M3](https://aclanthology.org/2024.findings-acl.137/) or
[multilingual-e5-large-instruct](https://arxiv.org/abs/2502.13595)). Prior expectation from the
literature is that translation loses or ties — [CLIRudit](https://arxiv.org/abs/2504.16264) reports
NV-Embed-v2 at 0.580 MAP untranslated vs 0.600 with *gold human* translation, with query translation
actively degrading several dense models.

### Phase 1 — End-to-end answer quality, single-language corpus

**Datasets:** [XOR-Full](https://github.com/AkariAsai/XORQA) (answer required in the question's
language) and [MKQA](https://github.com/apple/ml-mkqa) over one shared English corpus.

**Metrics:** F1 / EM / BLEU on XOR-Full; flexible-EM and **char 3-gram recall** on MKQA (not EM —
the answer language differs from the evidence language).

**Comparators:** XOR-Full — MT-pipeline baseline 18.7 F1 / 12.1 EM / 16.8 BLEU
([XOR QA](https://aclanthology.org/2021.naacl-main.46/)), CORA 34.7 F1 / 25.8 EM, CLASS 42.4 F1 /
32.7 EM ([CLASS](https://aclanthology.org/2024.emnlp-main.770/)). MKQA GPT-4o flexible-EM —
no-RAG ~43%, tRAG 46.5%, monoRAG 51.5%, MultiRAG 53.1%, CrossRAG 60.4%
([Ranaldi et al.](https://arxiv.org/abs/2504.03616)). Note that "translate the question, retrieve,
generate" is **tRAG** in that taxonomy and is the weakest of the four — that comparison is the
honest framing of the current design, and running it is the cheapest way to find out whether it
holds on your data.

**Do not use MKQA for language policy** — its answers are language-independent by design
([MKQA](https://aclanthology.org/2021.tacl-1.82/)).

### Phase 2 — Answer-language accuracy and policy

**Datasets:** [LCB](https://github.com/for-ai/language-confusion) monolingual setting (= "match the
query") and cross-lingual setting (= "pin a language"). These two settings *are* the two policy
modes. Plus [XRAG](https://github.com/amazon-science/XRAG)'s English-only-retrieval condition for
the with-retrieval version.

**Metrics:** LPR, WPR, LCPR at **line and word level** (not whole-response LID);
Response Language Correctness on XRAG, measured with `lingua`, OpenLID or
[GlotLID](https://github.com/cisnlp/GlotLID).

**Comparators:** LCB cross-lingual line-level pass rate — GPT-4o 92.4%, Command R+ Refresh 95.4%,
Llama 3 70B-Instruct 30.3% ([LCB](https://aclanthology.org/2024.emnlp-main.380/)). XRAG
wrong-language rate under English-only retrieval — ~5% GPT-4o and Command-R+, ~15% Claude 3.5
Sonnet, ~35% Mistral-large ([XRAG](https://arxiv.org/abs/2505.10089)). Chirkova et al.'s prompt
recipe reaches >95% CLR ([paper](https://aclanthology.org/2024.knowllm-1.15/)).

**Two ablations that will matter more than the headline:** (a) hold the question fixed and swap the
retrieved context language — [Language Drift](https://arxiv.org/abs/2511.09984) measured a 92.0% →
68.4% collapse from that alone; (b) sweep temperature and turn on beam search — LCB reports WPR
falling to 72.0% at high temperature and beam search consistently hurting cross-lingual LPR.

### Phase 3 — Abstention (validating the weak-similarity gate)

**Dataset:** [NoMIRACL](https://github.com/project-miracl/nomiracl), 18 languages including Hindi.
Supplement with [Agri-Query](https://arxiv.org/abs/2508.18093)'s 54/54 answerable/unanswerable split
for a document-shaped analogue.

**Metrics:** hallucination rate (non-relevant subset) **and** error rate (relevant subset), reported
as a pair. Reporting one alone is meaningless — the published models trade one for the other
(>88% hallucination for LLaMA-2/Orca-2; 74.9% error rate for the low-hallucination models)
([NoMIRACL](https://arxiv.org/abs/2312.11361)).

This is the correct instrument for "the retrieval that already ran scored badly" — it measures
whether the system can recognise that retrieval failed, which is exactly the decision the gate makes.

### Phase 4 — Mixed-language corpus (the known open limit)

Three instruments, in increasing cost.

**4a — Diagnose, cheaply.** [LAReQA](https://aclanthology.org/2020.emnlp-main.477/): XQuAD-R (11
languages) and MLQA-R (7), *all candidates pooled into one mixed-language index*. Report mAP against
the published rows — X-X 0.23/0.26, X-X-mono 0.52/0.49, X-Y 0.66/0.49, Translate-Test 0.72/0.58.
This is the smallest experiment that reproduces the bug.

**4b — Separate the two failure modes.** Apply the
[MLAIRE](https://arxiv.org/abs/2605.07249) protocol — controlled parallel-passage pools — and report
**LPR and Lang-nDCG alongside nDCG**, plus MLAIRE's 4-way failure decomposition. Add
**MLRS** ([DKM-RAG](https://arxiv.org/abs/2502.11175)): how much a document's rank improves when it
is translated into the query language. A large MLRS is the direct fingerprint of the mixed-corpus
bug. Add **PEER** ([github.com/hltcoe/peer_measure](https://github.com/hltcoe/peer_measure)) for
per-language rank fairness, and **MRC@5** ([LaKDA](https://aclanthology.org/2024.mrl-1.23/)) for
whether semantically identical Hindi and English queries return the same list — vanilla DPR scores
MRC@5 of 11.7–13.1, so there is a lot of room to be bad here.

**4c — Score against a real MLIR collection.**
[NeuCLIRBench](https://arxiv.org/abs/2511.14758) (250,128 judgments, 100 multilingual queries, ships
a neural **fusion** first-stage baseline so you are not comparing against BM25) and the
[TREC 2025 RAGTIME MLIR task](https://arxiv.org/abs/2602.10024) ("search all four document
collections and produce a single unified ranked list", 4 × ~1M CommonCrawl News docs).
Target: NeuCLIR 2024 best MLIR nDCG@20 = **0.545**, against 0.664 / 0.698 / 0.593 for the same
collections searched one language at a time ([NeuCLIR](https://arxiv.org/abs/2509.14355)) — that gap
is the size of the prize.

**4d — End-to-end, mixed corpus.** [XRAG](https://github.com/amazon-science/XRAG)'s multilingual
retrieval condition (non-English question over a mixed English + question-language document set) is
a ready-made harness for this exact case, and it scores response-language correctness at the same
time. Add [X-MADAM-RAG](https://arxiv.org/abs/2606.12903) if the corpus can contain contradictory
evidence across languages.

**Compare fixes head to head on the same harness,** since all of them are published and none is
obviously dominant: balanced per-language retrieval and dual search-then-merge
([The Cross-Lingual Cost](https://arxiv.org/abs/2507.07543), reported as costing nothing in
same-language cases while adding ~4–6% for BGE-M3 and ~20% for M-E5); weighted RRF over per-language
shards ([DS@GT](https://arxiv.org/abs/2607.22841), w_lang=2.0 / w_global=1.0, k=60, Hindi 73.5%);
fixed 50/50 evidence fusion ([Effects of Cross-lingual Evidence](https://arxiv.org/abs/2604.20531),
Basque 76.0% vs 68.18% English-only); index-side language-vector subtraction with zero query-time
cost ([SHIFT](https://arxiv.org/abs/2606.18801), mE5-large nDCG@20 0.633→0.737) or SAE language-latent
suppression ([LangSAE](https://arxiv.org/abs/2601.04768), Belebele +21.9%, Chinese +104.3%);
language-aware reranking ([LAMAR](https://arxiv.org/abs/2607.22042),
[LAURA](https://arxiv.org/abs/2604.20199)).

**Heed the CLEF-era warning before building fusion.**
[Savoy et al. 2004](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf): raw-score merging
collapses **−73% MAP** when the per-language runs use different engines, but gains +30% when they
share one; logistic regression on ln(rank)+RSV wins in all conditions (+28% to +44%); biased
round-robin is a cheap +10%. And
[Lin & Chen 2002](https://ceur-ws.org/Vol-1168/CLEF2002wn-adhoc-LinEt2002.pdf) explains why a
3-file Hindi shard will misbehave in a pooled index: pooling raises N in idf without raising term
occurrences, so it "makes retrieval result preferring documents in small document collection."

### Phase 5 — Attribution and faithfulness across the language boundary

**Dataset:** [XOR-AttriQA](https://arxiv.org/abs/2305.14332) (bn, fi, ja, ru, te). Report the
**attribution rate** — the fraction of answers actually supported by a retrieved passage — separately
from answer accuracy. The published spread is 53.1% (JA) to 93.1% (TE), with up to ~47% of
exact-match answers unattributable.

**Build the guardrail while you are there:** the same paper shows ~100 attribution examples suffice
to fine-tune a detector to 92–96% accuracy / 95–98% ROC AUC.

**Automate coverage** with [DoGMaTiQ](https://arxiv.org/abs/2605.04458) QA-nuggets scored under
ARGUE-style sentence support + nugget coverage ([RAGTIME](https://arxiv.org/abs/2602.10024)) — the
QA-nugget form is what makes a Hindi answer gradeable against an English source at all. Calibrate
expectations: top NeuCLIR report-generation systems reached ~0.3 citation precision and <0.5 nugget
recall.

**Validate the judge before trusting it.** Run [MEMERAG](https://github.com/amazon-science/MEMERAG)
— it has a Hindi split, and it shows the best judge **differs by language** (GPT-4o mini best in
English, Qwen 2.5 32B strongest elsewhere) with guidelines + CoT beating zero-shot. Then adopt
[MIRAGE-Bench](https://github.com/vectara/mirage-bench)'s 7-feature surrogate judge (Kendall τ =
0.909 against GPT-4o) as the cheap per-commit scorecard, since it already bundles language detection,
English detection, citation quality and NLI support.

### Phase 6 — Hindi specifically, and the dataset that does not exist

**What exists and is directly usable:**

- [MEMERAG](https://github.com/amazon-science/MEMERAG) — Hindi faithfulness/relevance with expert
  sentence annotations and a validated judge.
- [MIRAGE-Bench](https://github.com/vectara/mirage-bench) — Hindi generation quality with an
  answer-language feature built in.
- [NoMIRACL](https://github.com/project-miracl/nomiracl) — Hindi abstention.
- [MTEB(Indic)](https://github.com/embeddings-benchmark/mteb) (23 tasks) and
  [Hindi-BEIR](https://arxiv.org/abs/2408.09437) / [IndicMSMarco](https://arxiv.org/abs/2506.01615)
  — monolingual Hindi retrieval floor (MRR ~0.52 for the best encoders).
- [IndicGenBench XorQA-In-Xx](https://github.com/google-research-datasets/indic-gen-bench) — the
  **reader** half of the target task at scale (28 Indic languages, 32k examples, gold English
  passage supplied). Run it retrieval-free to isolate generation quality from retrieval quality;
  target 37.4 Token-F1 (PaLM-2-L, one-shot).
- [HEALTH-PARIKSHA](https://arxiv.org/abs/2410.13671) — a real English-only-KB deployment with
  Hindi/Tamil/Telugu/Kannada queries, though only 19 Hindi pairs.
- [PI-Indic-Align](https://github.com/aryashah2k/PI-Indic-Align) — explicit Indic cross-lingual
  retrieval split; comparator E5-Large-Instruct 27.4% R@1 monolingual → **20.7% cross-lingual**.

**What does not exist:** a Hindi-question-over-English-corpus **retrieval** benchmark. XOR-TyDi has
no Hindi split (Bengali and Telugu are its only Indic entries). IndicGenBench supplies the gold
passage, so no index is exercised. IndicRAGSuite is explicitly monolingual. Hindi-BEIR, IndicIRSuite
and MIRACL-Hindi are monolingual Hindi.

**Build it from named resources — this is the cheapest defensible contribution available:**

1. Take the English passages from
   [XorQA-In-Xx](https://github.com/google-research-datasets/indic-gen-bench) and pool them into a
   single English index (plus distractors, so the gold passage is not near-unique).
2. Use its Hindi questions as queries and its Hindi answers as gold.
3. Score retrieval with R@2kt / R@5kt (the [XOR-Retrieve](https://aclanthology.org/2021.naacl-main.46/)
   protocol), answers with char 3-gram recall + Token-F1, language with line/word-level LPR, and
   grounding with [DoGMaTiQ](https://arxiv.org/abs/2605.04458) nuggets.
4. For a **mixed-corpus** variant, add the Hindi-language passages from
   [Hindi-BEIR](https://arxiv.org/abs/2408.09437) or [IndicMSMarco](https://arxiv.org/abs/2506.01615)
   to the same index and re-run — that reproduces the open limit on Hindi with real data, and
   MLAIRE's LPR will say how much of any regression is language preference rather than semantics.
5. Need more queries? [IndicNLG](https://arxiv.org/abs/2203.05437)'s question-generation split
   generates in-language questions for a given passage, and
   [IndicSQuAD](https://arxiv.org/abs/2505.03688)'s translate-and-realign method (answer-span
   alignment preserved) is the citable recipe for manufacturing aligned pairs. The
   [Hindi-BEIR](https://arxiv.org/abs/2408.09437) three-way construction pattern (translated English
   BEIR + existing Hindi sets + synthetic) is the standard way to justify such a set.

**Also test the romanized path**, since a Unicode script gate is blind to it. Use
[IndicLID / Bhasha-Abhijnaanam](https://ai4bharat.iitm.ac.in/indiclid) to label romanized queries
and to measure how often the gate fires incorrectly; expect ~80.40% LID accuracy on romanized text.
Quantify the retrieval cost with the [Lost in Transliteration](https://arxiv.org/abs/2505.08411)
protocol (native vs Latinized queries against the same index; BGE-M3 lost 97% of MRR@10 on Latinized
Chinese). And run [MiLQ](https://arxiv.org/abs/2505.16631)'s comparison before "fixing" anything —
mixed-language queries retrieved English documents far *better* than native-script ones there
(38.35 vs 12.35 MAP@100 for low-resource languages).

### Phase 7 — The gate: quality per model call

This is the only measurement in this plan with no published comparator, and therefore the only one
that could stand as an original result. Every published cross-lingual RAG system is unconditional in
its expensive step: tRAG always translates the query, CrossRAG always translates the retrieved
documents ([Ranaldi et al.](https://arxiv.org/abs/2504.03616)), DKM-RAG always translates reranked
passages ([paper](https://arxiv.org/abs/2502.11175)), QTT-RAG always translates and scores foreign
documents ([paper](https://arxiv.org/abs/2510.23070)), DELTA always builds its five-segment fused
query ([paper](https://arxiv.org/abs/2601.02956)). The two gated systems gate on something else and
report no cost: [Syfer](https://arxiv.org/abs/2608.13160) gates the English pathway on a single
cosine threshold (τ = 0.8) against decomposition drift; [CORAL](https://arxiv.org/abs/2604.25676)
gates on an LLM sufficiency critic.

**The experiment:** on [XOR-Retrieve](https://github.com/AkariAsai/XORQA) and
[XRAG](https://github.com/amazon-science/XRAG), sweep the weak-similarity threshold from
"never translate" to "always translate" and plot **R@5kt (and end-to-end fEM) against translation
calls per 100 queries.** Report the curve, the knee, and the per-language breakdown.

**Why the curve will not be flat:** translation is conditionally *harmful*, which is measured but
never exploited. [INDIC QA BENCHMARK](https://arxiv.org/abs/2407.13522) — Hindi 46.76 direct vs 26.22
translate-test, Assamese 21.29 direct vs 33.01 translate-test.
[How and Where to Translate](https://arxiv.org/abs/2507.22923) — no universally best strategy; the
winner flips by model and language. That is the empirical case for a gate, and nobody has quantified
the trade-off.

**Ablate the script gate honestly.** Two published results argue *against* gating the cross-lingual
path off when the query's script is present in the corpus:
[BordIRLines](https://arxiv.org/abs/2410.01171) found retrieving **multilingual** documents beat
purely in-language retrieval on both consistency (Command-R 64.2→78.7) and geopolitical bias
(28.7→5.9) across 49 languages; and [Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/)
ablated English-only vs user-language-only vs **concatenated** multilingual Wikipedia across 13
languages and found the concatenated corpus beneficial in most cases with a single BGE-m3 retriever.
Run the gate-on / gate-off comparison and report it either way.

### Reporting template

One row per (system variant × dataset). Never collapse these into a single score.

| Field | Metric | Source of the comparator |
|---|---|---|
| Cross-lingual retrieval | R@2kt, R@5kt, nDCG@20, Hit@20 | [XOR QA](https://aclanthology.org/2021.naacl-main.46/), [NeuCLIR](https://arxiv.org/abs/2509.14355) |
| Language preference | LPR, Lang-nDCG, MLRS, PEER, MRC@5 | [MLAIRE](https://arxiv.org/abs/2605.07249), [DKM-RAG](https://arxiv.org/abs/2502.11175), [PEER](https://arxiv.org/abs/2405.00978), [LaKDA](https://aclanthology.org/2024.mrl-1.23/) |
| Answer correctness | F1 / EM / flexible-EM / char 3-gram recall | [CLASS](https://aclanthology.org/2024.emnlp-main.770/), [Ranaldi et al.](https://arxiv.org/abs/2504.03616) |
| Answer language | line-level LPR, word-level WPR, LCPR, CLR | [LCB](https://aclanthology.org/2024.emnlp-main.380/), [XRAG](https://arxiv.org/abs/2505.10089) |
| Attribution | attribution rate; ARGUE sentence support + nugget coverage | [XOR-AttriQA](https://arxiv.org/abs/2305.14332), [RAGTIME](https://arxiv.org/abs/2602.10024) |
| Abstention | hallucination rate **and** error rate, paired | [NoMIRACL](https://arxiv.org/abs/2312.11361) |
| Cost | translation calls / 100 queries, p50 latency | Phase 7 (no published comparator) |
| Per-language | every row above, broken out — never averaged | [Hindi-BEIR](https://arxiv.org/abs/2408.09437): "a single average NDCG number will hide where a model actually fails" |

---

## 4. Verify before you rely on it

Items whose details were recorded from secondary sources or paywalled venues during the sweep, and
should be confirmed against the primary release before being cited in anything external:

- **Hindi coverage** of MKQA, LCB, CLIRMatrix, BordIRLines, M4-RAG and MLAIRE's Belebele split —
  marked `U` in the tables above.
- **XOR-AttriQA size.** The paper reports ~10,000 human-annotated tuples across 5 languages with
  per-language counts in Table 1; a widely repeated "500 val / 4,720 test" split could not be
  sourced ([paper](https://arxiv.org/abs/2305.14332)).
- **SqCLIRIL** ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0167865525003071))
  and the FIRE SqCLIR / MSIR overview papers — paywalled; verified by metadata and search
  description only, not read.
- **NLLB-E5 48.57 vs BGE-M3 46.18** on Hindi-BEIR ([paper](https://arxiv.org/abs/2409.05401)) —
  recorded from the paper record, worth re-checking Table 2 directly.
- **RAGAS** having no language metric was verified from the
  [available-metrics page](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/) at
  sweep time; re-check, since it is a fast-moving library and this is an argument for building your
  own metric.
