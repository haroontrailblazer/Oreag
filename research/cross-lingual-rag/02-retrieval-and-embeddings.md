# 02 — The Retrieval Layer: Multilingual Embeddings, Strategy Trade-offs, Hybrid, Rerankers

Scope: everything between "the question arrives" and "candidate passages are handed to the
generator." Answer-language control, language confusion and decoding-time enforcement are a
separate layer and are not covered here.

**Verdict for this layer:** retrieving a semantically correct English passage from a Hindi
question is a commodity capability, not an open problem. It has been demonstrated with no
translation step at all since 2021 — Contriever's abstract states verbatim that its unsupervised
models "can perform cross-lingual retrieval between different scripts, such as retrieving English
documents from Arabic queries, which would not be possible with term matching methods"
([arXiv:2112.09118](https://arxiv.org/abs/2112.09118)). What is genuinely hard, and where the
numbers are ugly, is (a) low-resource and non-Latin scripts, (b) romanized/code-mixed input,
(c) a single index containing more than one language, and (d) knowing which of the three
translation strategies to use, because the published evidence flips by corpus, by encoder and
by language.

---

## 1. Short version

| Question | What the literature says | Primary citation |
|---|---|---|
| Do I need to translate the query at all? | Usually no, if the encoder is strong. BGE-M3 with **no** translation beat every query-translation pipeline on Sinhala/Tamil→English (R@15 96.2% vs Google Translate 92.4%) | [arXiv:2608.12820](https://arxiv.org/abs/2608.12820) |
| Does query translation ever hurt? | Yes, measurably, on dense retrievers — NV-Embed-v2 0.580 MAP untranslated → 0.541 with query translation | [arXiv:2504.16264](https://arxiv.org/abs/2504.16264) |
| Is dense enough on its own? | No. On MIRACL, mDPR nDCG@10 0.415 vs BM25 0.393; the hybrid is 0.578 | [TACL 2023](https://aclanthology.org/2023.tacl-1.63/) |
| Where does dense collapse? | Low-resource non-Latin scripts, romanized text, code-mixing. Amharic: 23% relative MRR@10 below a monolingual retriever; Latinized Chinese: BGE-M3 loses 97% of MRR@10 | [arXiv:2605.24556](https://arxiv.org/abs/2605.24556), [arXiv:2505.08411](https://arxiv.org/abs/2505.08411) |
| Best single default encoder | multilingual-e5-large-instruct (560M) is MMTEB's best public model overall; BGE-M3 wins on cross-lingual and gives you sparse for free | [arXiv:2502.13595](https://arxiv.org/abs/2502.13595), [ACL Findings 2024](https://aclanthology.org/2024.findings-acl.137/) |
| Best cheap win after first-stage | A cross-encoder reranker. On cross-script pairs it moves nDCG from ~0 to 30–91 | [arXiv:2511.19324](https://arxiv.org/abs/2511.19324) |
| Best strategy overall for RAG | Retrieve multilingually, then translate the **retrieved documents**, not the query (CrossRAG) | [arXiv:2504.03616](https://arxiv.org/abs/2504.03616) |

---

## 2. Multilingual dense retrievers: the published comparative numbers

### 2.1 Cross-lingual and multilingual retrieval benchmarks

The one table worth memorising is M3-Embedding's, because it reports both the monolingual case
(MIRACL, 18 languages, query and corpus same language) and the cross-lingual case (MKQA, 25
query languages against **one shared English Wikipedia corpus** — precisely the Oreag setup).

| Model | MIRACL avg nDCG@10 | MKQA Recall@100 (25 langs → one English corpus) |
|---|---|---|
| M3 dense | 69.2 | — |
| M3 sparse | 53.9 | — |
| M3 multi-vector | 70.5 | — |
| M3 all three fused | **71.5** | **75.5** |
| multilingual-E5-large | 66.6 | 70.9 |
| E5-mistral-7b | 63.4 | 70.1 |
| OpenAI-3 | 54.9 | — |

Source: [M3-Embedding, ACL Findings 2024](https://aclanthology.org/2024.findings-acl.137/).
Trained on 1.2B pairs from 194 languages including 2,655 cross-lingual correspondences; 8,192-token
inputs. Note that the paper never calls it "BGE-M3" — that is the model-hub name
([BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3)).

Other anchors:

- **MMTEB** (500+ tasks, 250+ languages): "the best-performing publicly available model is
  multilingual-e5-large-instruct with only 560 million parameters," beating billion-parameter
  LLM-based embedders overall. MTEB(Indic) is a ready-made 23-task subset where the same model
  ranks first (Borda 209 / avg 70.2).
  [arXiv:2502.13595](https://arxiv.org/abs/2502.13595)
- **MTEB** established that no single embedding method dominates across task types (8 task types,
  58 datasets, 112 languages, 33 models) — a leaderboard rank does not transfer between STS,
  clustering and retrieval. [arXiv:2210.07316](https://arxiv.org/abs/2210.07316)
- **jina-embeddings-v3**: 570M params, 89 languages, 8,192-token context, and — the architectural
  detail worth stealing — **separate `retrieval.query` and `retrieval.passage` LoRA adapters** over
  one shared backbone (<3% of params at rank 4). Query-side and passage-side representations can be
  tuned independently without duplicating the index.
  [arXiv:2409.10173](https://arxiv.org/abs/2409.10173)
- **LaBSE**: 109 languages, raised average Tatoeba bitext retrieval over 112 languages to 83.7%
  from a prior SOTA of 65.5% — but it is optimised for *translation-pair mining*, not
  question→passage relevance. [arXiv:2007.01852](https://arxiv.org/abs/2007.01852)
- The CLIR survey inventories the current toolbox and its evaluation sets (dense: mDPR, LaBSE,
  mSBERT, mContriever, multilingual-E5-large; sparse: SPLADE/SPLADE-X, MultiSPLADE;
  late-interaction: ColBERT/v2; rerankers: XLM-R, mT5, Qwen3-Reranker; benchmarks: MIRACL,
  XOR-Retrieve, XOR-TyDi, CLIRMatrix, multilingual MS MARCO).
  [arXiv:2510.00908](https://arxiv.org/abs/2510.00908)

### 2.2 The benchmark blind spot you must not fall into

**MIRACL is monolingual by design.** Its authors state it: "our focus is monolingual retrieval
across diverse languages, where the queries and the corpora are in the same language ... as opposed
to cross-lingual retrieval" ([TACL 2023](https://aclanthology.org/2023.tacl-1.63/)). The same is
true of Mr. TyDi ([MRL 2021](https://aclanthology.org/2021.mrl-1.12/)), Hindi-BEIR
([arXiv:2408.09437](https://arxiv.org/abs/2408.09437)) and IndicRAGSuite — whose own paper states
"IndicMSMARCO supports monolingual retrieval," queries and passages translated into the *same*
language ([arXiv:2506.01615](https://arxiv.org/abs/2506.01615)). A strong MIRACL or MTEB(Indic)
score certifies nothing about query-in-B / passage-in-A behaviour.

The instrument that does separate the two is **MLAIRE**, which decomposes retrieval quality from
query-language preference over controlled parallel pools (31 retrievers; Belebele 122 languages,
XQuAD 12, MLQA 7). Its headline is that the two are near-orthogonal and mildly *anti*-correlated
(nDCG vs Language Preference Rate: Pearson/Spearman −0.28/−0.30 on MLQA, −0.38/−0.47 on XQuAD,
−0.29/−0.28 on Belebele), with a very wide spread across models on MLQA:

| Retriever | nDCG | Language Preference Rate |
|---|---|---|
| multilingual-e5-large | 96.15% | 99.92% |
| Qwen3-Embedding-8B | 68.64% | 53.00% |
| BM25 | 27.92% | 93.68% |

Source: [arXiv:2605.07249](https://arxiv.org/abs/2605.07249). Consequence for anyone measuring a
cross-lingual retriever on a single-script corpus: semantic skill and same-language preference are
*indistinguishable* in that setup, so a near-perfect rank@1 number there does not predict behaviour
on a mixed corpus.

The complementary benchmark is **LAReQA**, which introduced the distinction that explains most
mixed-pool failures: *weak* alignment (the nearest neighbour in another language is right) versus
*strong* alignment (a semantically related cross-language pair must be closer than an unrelated
same-language pair). Retrieval is scored from one pooled mixed-language candidate set. mAP on
XQuAD-R / MLQA-R: En-En 0.29/0.36, X-X 0.23/0.26, X-X-mono 0.52/0.49, X-Y 0.66/0.49,
Translate-Test 0.72/0.58 ([arXiv:2004.05484](https://arxiv.org/abs/2004.05484),
[EMNLP 2020](https://aclanthology.org/2020.emnlp-main.477/)). Note X-X (0.23) is *worse* than
English-only training (0.29): training on translated data with monolingual positive pairs actively
damages mixed-pool retrieval. Only X-Y — where question and answer are translated into *different*
languages, forcing the model to accept a foreign-language answer as correct — repairs it.

---

## 3. Why cross-lingual retrieval degrades: language identity is a direction in the vector space

This is the mechanism behind almost every symptom in this document, and it has been known since
2021.

**Diagnosis.** For weak-alignment multilingual encoders, the *principal components* of the
semantic space primarily encode **language identity**, not meaning. Language Information Removal
(LIR) — a post-hoc, training-free matrix factorisation plus orthogonal projection that strips the
language subspace — yields "almost 100% relative improvement in MAP" on LAReQA.
[EMNLP 2021](https://aclanthology.org/2021.emnlp-main.470/)

Two independent 2026 papers rediscover and industrialise this, and both are **training-free and
index-side**, which makes them the cheapest available fix:

| Method | Mechanism | Result |
|---|---|---|
| **SHIFT** | Relative language vector = mean embedding difference over parallel pairs (533k mMARCO pairs), **subtracted from document embeddings at index time only**; query embeddings untouched, zero query-time cost | multilingual-e5-large nDCG@20 0.633 → 0.737 avg over 4 MLIR benchmarks (Belebele 0.816→0.910, MLQA 0.494→0.649); Target-Languages Recall@20 0.540→0.694 ([arXiv:2606.18801](https://arxiv.org/abs/2606.18801)) |
| **LangSAE Editing** | Sparse autoencoder over pooled mE5-large embeddings (262,144-unit dictionary, expansion 256, top-k 4,096); suppress language-identity latents at inference, reconstruct to original dimensionality so existing vector DBs still work | Belebele macro-avg nDCG@20 0.5359 → 0.6534 (+21.9%), R@20 0.4958 → 0.6280 (+26.6%); XQuAD nDCG@20 0.7141 → 0.8613. **Chinese 0.3397 → 0.6947, +104.3%** — the effect is largest for script-distinct languages ([arXiv:2601.04768](https://arxiv.org/abs/2601.04768)) |

Training-time fixes exist too, and are stronger but need a pipeline:

- **MIMO** anchors on an English teacher (Qwen3-Embedding-8B), initialises alignment by
  distillation, then jointly optimises distillation + cross-lingual contrastive loss. The λ sweep
  is the actionable part: λ=0 (pure distillation) gives best alignment but wrecks uniformity; λ=1
  (pure contrastive) gives uniformity but degrades alignment; λ=0.2 holds both. xlm-roberta-large
  reaches 60.69 avg nDCG@20 on MLIR vs 53.18 (XLCO), 52.95 (LaKDA), 31.41 (plain InfoNCE).
  [arXiv:2605.31171](https://arxiv.org/abs/2605.31171)
- **Disentangled contrastive learning** splits the embedding into explicit semantic and linguistic
  subspaces: +1.5 MRR@10 on mMARCO (27.8 vs 26.3) and +2.7 nDCG@10 on MIRACL (55.0 vs 52.3), with
  the larger share of the gain on languages with **no** parallel training data (61.6 vs 58.6).
  [arXiv:2608.02189](https://arxiv.org/abs/2608.02189)
- **KD-SPD** (soft prompt decoding) implicitly translates document representations into a shared
  space with no multilingual training data: +20.2% MAP over mDPR, +9.6% over an SBERT-style
  multilingual distillation encoder, over CLEF/mTREC/LAReQA (15 languages). Its diagnosis is the
  same one: the multilingual encoder inherits language bias from pretraining and fine-tuning only
  ever ranks documents *within* one language space, so "the ranking score generated by mDPR [is]
  inconsistent across languages." [arXiv:2305.09025](https://arxiv.org/abs/2305.09025)
- **LaKDA**, a KL-divergence loss aligning score distributions across parallel queries, improves
  accuracy *and* fairness where naive MSE alignment damages accuracy. On MultiEuP-v2 (24 European
  languages) with XLM-R: MRR@100 46.5 (vanilla mDPR) → 48.2 (MSE) → **61.0** (LaKDA); with mBERT
  35.6 → 24.0 (MSE collapses it) → 40.0. [MRL 2024](https://aclanthology.org/2024.mrl-1.23/),
  [arXiv:2509.06195](https://arxiv.org/abs/2509.06195)

One caveat against over-purifying: the cross-lingual alignment survey argues "an effective
trade-off between language-neutral and language-specific information is key" — perfectly
language-neutral embeddings are not the goal, because collapsing language-specific signal hurts
downstream use ([arXiv:2404.06228](https://arxiv.org/abs/2404.06228)). DELTA's ablation makes the
same point from the query side: pivoting to English "degrades native surface-form anchors — titles,
aliases, and original scripts — that are critical for precise entity matching"
([arXiv:2601.02956](https://arxiv.org/abs/2601.02956)).

---

## 4. Documented degradation on low-resource and non-Latin scripts

### 4.1 The numbers

| Setting | Measurement | Source |
|---|---|---|
| Amharic (Ethiopic) | Best zero-shot multilingual retriever (snowflake-arctic-embed-l-v2.0) 0.653 MRR@10 vs best **monolingual** ColBERT-Base-Amharic 0.803 — 23.0% relative MRR@10 gap, 19.1% relative nDCG@10 gap, persisting across dense, late-interaction, sparse and cross-encoder architectures. Fine-tuning narrows but does not close it: EmbeddingGemma-300m 0.448→0.718, Harrier-oss-v1-270m 0.576→0.760, best fine-tuned still under 0.803 | [arXiv:2605.24556](https://arxiv.org/abs/2605.24556) |
| Medical, Japanese | "biomedical encoders that score 0.818 nDCG@10 in English drop to 0.056 in Japanese, a gap that English-only benchmarks cannot detect" — a ~14× collapse | [arXiv:2606.24200](https://arxiv.org/abs/2606.24200) |
| African languages | Purely cross-lingual dense retrieval (mDPR, no translation) averages **19.0% Recall@10**, vs 62.4% with Google-Translate query translation and 67.6% with human translation; hybrid sparse+dense with human translation 73.4%. 10 languages, 12,239 questions | [AfriQA, arXiv:2305.06897](https://arxiv.org/abs/2305.06897) |
| 12 Indic languages | Best frozen encoder (E5-Large-Instruct) 27.4% R@1 monolingual, falling to **20.7% R@1 cross-lingually** (~24% relative). BGE-M3 leads reverse retrieval at 32.1% R@1 | [arXiv:2601.10205](https://arxiv.org/abs/2601.10205) |
| Indic monolingual ceiling | MRR tops out around 0.49–0.52 across 13 Indian languages (BGE-M3 best in 8/13: 0.49 Malayalam/Tamil, 0.50 Telugu; multilingual-e5-large best in 4 incl. **Hindi 0.52**); Assamese and Odia lowest | [arXiv:2506.01615](https://arxiv.org/abs/2506.01615) |
| Hindi (monolingual) | NLLB-E5 avg NDCG@10 **48.57** on Hindi-BEIR vs BGE-M3 **46.18** | [arXiv:2409.05401](https://arxiv.org/abs/2409.05401) |
| Tamil (cross-lingual QA) | Winning MIA-2022 system reached 20.8 F1 on Tamil where most systems scored near zero — using entity-aware contextualized representations, i.e. lexical/entity signal, not better dense semantics | [MIA 2022](https://aclanthology.org/2022.mia-1.11/) |
| 275+ languages, embeddings | No model is near-perfect: best is multilingual-e5-instruct 0.905 (alee-F200), LaBSE 0.917 (alee-MT61) | [arXiv:2607.00171](https://arxiv.org/abs/2607.00171) |

### 4.2 What predicts the degradation

Two cheap, computable predictors, both better than "is the script non-Latin":

1. **Subword fertility.** ALEE reports Spearman ρ = **−0.786** (alee-F200), −0.708 (alee-BQ275) and
   −0.516 (alee-MT61) between subtoken count and accuracy (−0.986 within Romansh varieties). The
   Amharic paper attributes its gap to the same cause: multilingual tokenizers **over-segment** rich
   morphology in non-Latin scripts.
   [arXiv:2607.00171](https://arxiv.org/abs/2607.00171),
   [arXiv:2605.24556](https://arxiv.org/abs/2605.24556)
2. **Pretraining corpus share.** The Language Ranker metric — last-token hidden state at layers
   {5,10,15,20,25}, cosine-similarity against English, averaged — tracks pretraining share across 94
   OPUS-100 languages and 5 model families: German (0.17% of corpus) 0.723 vs Kannada (≤0.01%)
   0.236. [arXiv:2404.11553](https://arxiv.org/abs/2404.11553). For context on why Indic is thin:
   Indic languages are ~1% of Common Crawl while India is 18% of world population
   ([arXiv:2502.09642](https://arxiv.org/abs/2502.09642)).

ALEE adds one directly operational finding for chunking: accuracy drops **9.4%** from single- to
multi-sentence text and **15.4%** from single-sentence to paragraph
([arXiv:2607.00171](https://arxiv.org/abs/2607.00171)). Cross-lingual retrieval quality is a
function of chunk length, so a chunk-size ablation is not optional in a multilingual index.

### 4.3 Three input modes that break every embedder here, and that a Unicode script check cannot see

- **Romanized / transliterated queries.** BGE-M3 loses **97%** of MRR@10 on Latinized Chinese
  (0.2342 → 0.0078) and **49%** on Latinized Russian (0.2444 → 0.1244) on mMARCO. The only
  fine-tuning config that repairs the transliterated side without wrecking the native side is a
  **50/50 mixture of native + Latinized queries** (zh-T 0.0078→0.1382; ru-T 0.1244→0.2633 vs 0.2770
  native). Qualitatively, transliteration destroys query nuance — native/transliterated top-10
  overlap was ≤3 documents for most sampled queries.
  [arXiv:2505.08411](https://arxiv.org/abs/2505.08411)
- **Code-switched queries.** Across CS-MTEB's 11 tasks, code-switching degrades even robust
  multilingual retrievers by **up to 27%**, with the diagnosed cause being "substantial divergence
  in the embedding space between pure and code-switched text." Worst observed: e5-large-v2
  reranking with Japanese code-switching falls 60.17 → 25.75. Vocabulary expansion is insufficient
  (zh CSR-L 35.32 → 43.50, still far short of monolingual).
  [arXiv:2604.17632](https://arxiv.org/abs/2604.17632)
- **Detection itself is unreliable on short input.** IndicLID reaches 98.55% accuracy / 98.31 F1 on
  native script across the 22 scheduled Indian languages but only **80.40% / 74.72 F1 on romanized
  text** ([ACL 2023](https://aclanthology.org/2023.acl-short.71/)). A Unicode block check cannot
  distinguish romanized Hindi from English at all.

Counterweight worth testing before "fixing" code-mixed input: **MiLQ** finds mixed-language queries
are *dramatically better* at retrieving English documents than native-script ones — BM25 MAP@100
38.35 (low-resource: Swahili, Somali) and 34.92 (high-resource: Finnish, German, French) for mixed
queries vs 12.35 and 8.56 for native queries, against a monolingual ceiling of 48.71. NMT applied to
*mixed* queries even beats NMT applied to native queries (48.10/47.08).
[arXiv:2505.16631](https://arxiv.org/abs/2505.16631)

One more diagnostic that saves wasted retriever work: **on non-Latin-script documents, a "retrieval"
deficit is very often an ingestion/OCR deficit.** Holding the retrieval mechanism fixed and swapping
only transcription/preprocessing on VisR-Bench moves BM25 Top-5 accuracy from 20.73% → 47.20% on
Arabic and 39.35% → 85.47% on Japanese — the latter essentially closing the gap to multimodal
ColQwen2 (89.98%) and *beating* dense BGE-M3 (84.33%). On figure-heavy pages, adding semantic
descriptions is worth up to +31.1 Top-5 points.
[arXiv:2603.04238](https://arxiv.org/abs/2603.04238)

---

## 5. Translate-query vs multilingual-embed vs translate-document

### 5.1 Names, so you can search the literature

The 2025/2026 mRAG taxonomy names all four arms
([arXiv:2504.03616](https://arxiv.org/abs/2504.03616),
[Findings EACL 2026](https://aclanthology.org/2026.findings-eacl.35/)):

| Name | What it does |
|---|---|
| **monoRAG** | Retrieve in the query language from a same-language corpus |
| **tRAG** | Translate the **question** to English, retrieve from the English index |
| **MultiRAG** | Retrieve directly from a single mixed multilingual index with a multilingual encoder |
| **CrossRAG** | Retrieve multilingually, then translate the **retrieved documents** into a common language before generation |

Classical CLIR calls the first two *query translation* (QT) and the third-and-a-half
*document translation* (DT), and the survey states the index-architecture rule outright (§2.1,
"What to Translate?"): "Query translation has advantages for applications in which there are many
possible query languages, but only one document language... Symmetrically, document translation has
advantages when all the queries are in one language, but there are many document languages to be
searched. In such cases, space efficiency argues for indexing in the one query language." It also
notes DT can be *more accurate* even where QT is cheaper, because translation models are trained on
paired sentences with document context and queries are too short to supply it.
[arXiv:2111.05988](https://arxiv.org/abs/2111.05988)

### 5.2 The evidence, and it does not point one way

**Where query translation wins**

- **Sparse/lexical first stage, or a weak encoder.** BM25 without translation scores near 0% on
  non-English pairs ([arXiv:2511.19324](https://arxiv.org/abs/2511.19324)). On AfriQA, translation
  is the difference between a working system and a broken one: mDPR alone 19.0% R@10 vs 62.4% with
  Google Translate ([arXiv:2305.06897](https://arxiv.org/abs/2305.06897)).
- **When MT quality is high.** XOR-Retrieve makes the dependency explicit: DPR with
  human-translated queries R@5kt **72.1**, Google MT **67.2**, an in-house MT system **50.0**
  (R@2kt 65.1 / 64.3 / 43.5). Query translation quality dominates the result.
  [NAACL 2021](https://aclanthology.org/2021.naacl-main.46/)
- **Sinhala/Tamil against an English index, without a modern encoder.** A monolingual English
  baseline against native-script queries is near-total failure: R@1 of 1.6% (Si) and 0.6% (Ta),
  R@15 under 10%. [arXiv:2608.12820](https://arxiv.org/abs/2608.12820)

**Where query translation loses or actively hurts**

- **CLIRudit** (English queries → French academic documents): NV-Embed-v2 scores 0.580 MAP with
  **no** translation vs 0.600 with **gold human** translation — a ~3% gap — while query translation
  *degraded* several dense models (BGE-m-gemma2 0.571→0.533; NV-Embed-v2 0.580→0.541). The failure
  mode is mistranslated proper nouns with identical cross-language spelling (e.g. "Goose Bay").
  [arXiv:2504.16264](https://arxiv.org/abs/2504.16264)
- **Sinhala/Tamil→English e-government**: BGE-M3 untranslated R@15 96.2% (Si-En) / 95.6% (Ta-En)
  beats Google Translate query translation (92.4% / 93.0%), NLLB and mBART50.
  [arXiv:2608.12820](https://arxiv.org/abs/2608.12820)
- **Purpose-built CLIR dense retrievers** derive little benefit from translation, and gains over
  lexical and document-translated baselines are *most pronounced for low-resource and cross-script
  pairs* — the opposite of the intuition that translation is most needed where scripts differ.
  [arXiv:2511.19324](https://arxiv.org/abs/2511.19324)
- **Single-translation commitment is itself a known error source.** Work from 2013/14 on
  English-Hindi CLIR names the three canonical causes — "mismatching of query terms, lexical
  ambiguity and un-translated query terms" — and the classical remedy is generate-a-candidate-set
  then select, not commit to one rendering
  ([arXiv:1401.3510](https://arxiv.org/abs/1401.3510)). See PSQ below.

**Where document translation wins**

- **Sanskrit (Anveshana, English queries → Sanskrit documents).** DT+BM25 reaches 62.46 nDCG@10 /
  74.03 R@10, while Direct Retrieval with a shared embedding space (multilingual-e5-base) gets
  10.74 nDCG@10 / 18.26 R@10, XLM-R only 4.26, and QT+BM25 6.86. For a low-resource / unfamiliar
  corpus language, translating the **documents** at index time beat both alternatives by ~6×.
  [arXiv:2505.19494](https://arxiv.org/abs/2505.19494)
- **Sparse retrieval generally.** CLIRudit: BM25 collapses to 0.181 MAP untranslated and needs
  document translation (0.488) to compete ([arXiv:2504.16264](https://arxiv.org/abs/2504.16264)).
- **The RAG pipeline as a whole.** CrossRAG beats question-translation tRAG by **+13.9 points on
  MKQA** and +9.0 on MLQA, and beats MultiRAG by +3.8 / +1.3. GPT-4o flexible-EM on MKQA: no-RAG
  ~43% → tRAG 46.5% → monoRAG 51.5% → MultiRAG 53.1% → **CrossRAG 60.4%**. Averaged over all
  languages, gains over monolingual RAG are tRAG +8.9%, MultiRAG +14.3%, CrossRAG +17.8% (GPT-4o);
  on low-resource languages MultiRAG gains 6.6–8.4% over monoRAG and CrossRAG adds a further
  3.7–5.0% on top. [arXiv:2504.03616](https://arxiv.org/abs/2504.03616),
  [Findings EACL 2026](https://aclanthology.org/2026.findings-eacl.35/)

**Where document translation is worthless**

- For dense CLIR, performance is "largely unaffected by document translation and can even degrade
  slightly because of translation-induced noise."
  [arXiv:2511.19324](https://arxiv.org/abs/2511.19324)
- Its value **shrinks as the reranker gets stronger**: over NV-Embed-v2 first-stage results on
  CLEF 2003, DT adds +0.026 MAP for RankZephyr, +0.011 for RankGPT3.5, and only **+0.003 for
  RankGPT4.1**. Dense first-stage also beats translated BM25 outright (CIRAL nDCG@20: M3 0.392 vs
  BM25-DT 0.285; CLEF MAP: NV-Embed-v2 0.323 vs BM25-DT 0.308).
  [arXiv:2509.14749](https://arxiv.org/abs/2509.14749)
- Native-language indexing with a fine-tuned XLM-R reaches **98% of the MAP of neural document
  translation with an 84% reduction in indexing time**, and the 2% gap is not statistically
  significant. [arXiv:2209.01335](https://arxiv.org/abs/2209.01335)

### 5.3 Decision table

| Regime | Best strategy | Evidence |
|---|---|---|
| Strong multilingual dense encoder, high/mid-resource pair | **No translation** (MultiRAG / direct) | [2608.12820](https://arxiv.org/abs/2608.12820), [2504.16264](https://arxiv.org/abs/2504.16264), [2511.19324](https://arxiv.org/abs/2511.19324) |
| Lexical / sparse first stage | **Document translation** at index time | [2504.16264](https://arxiv.org/abs/2504.16264), [2505.19494](https://arxiv.org/abs/2505.19494), [2404.18797](https://arxiv.org/abs/2404.18797) |
| Very low-resource or unusual corpus language (Sanskrit-like) | **Document translation** | [2505.19494](https://arxiv.org/abs/2505.19494) |
| Low-resource query language, weak encoder | **Query translation** — it is the difference between 19% and 62% R@10 | [2305.06897](https://arxiv.org/abs/2305.06897) |
| Strong reranker in the pipeline | Skip document translation; the reranker absorbs the benefit | [2509.14749](https://arxiv.org/abs/2509.14749) |
| End-to-end RAG, mixed corpus, cost no object | **CrossRAG** (translate retrieved docs) | [2504.03616](https://arxiv.org/abs/2504.03616) |
| Many query languages, one document language | Query-side handling; index in the document language | [2111.05988](https://arxiv.org/abs/2111.05988) §2.1 |
| One query language, many document languages | Document translation into the query language; "space efficiency argues for indexing in the one query language" | [2111.05988](https://arxiv.org/abs/2111.05988) §2.1 |

Cost note that constrains all of this: CrossRAG translates every retrieved document on every query
— at top-5 that is five generation calls on the critical path. A fully deployed unconditioned
translate-in/translate-out pipeline (opus-mt-bn-en → FAISS over English FAO/IRRI manuals → NLLB-200
→ 4-bit Llama-3-8B) averages **~15.6 s end-to-end on a single Tesla T4**
([arXiv:2601.02065](https://arxiv.org/abs/2601.02065)). The obvious move is to push document
translation to **index time**, which is exactly what the PSQ revival did (§5.5).

### 5.4 The 1998/1999 result everyone rediscovers: fuse, don't choose

McCarley trained identical statistical MT models in **both directions on the same data** so the
QT-vs-DT comparison was not confounded by MT quality asymmetry. Result: late fusion of query
translation and document translation beats either alone, and beats even a perfect query
translation. TREC-7 short queries, English → French, average precision: qt 0.3296, dt 0.3345,
**qt+dt 0.3532**; human-translated query baseline ht 0.3611, but **ht+dt 0.4021** — the same pattern
across all 8 cells of Tables 1–2.
[ACL 1999](https://aclanthology.org/P99-1027/)

Oard's contemporaneous comparison of six bilingual-term-list QT techniques plus MT-based QT against
DT found MT-based query translation beat all six term-list techniques, and document translation gave
a further gain on top of that — and, separately, that arbitrarily picking *one* dictionary
translation per query term is typically no less effective than using every translation, i.e. naive
full-dictionary expansion buys nothing without weighting.
[AMTA 1998](https://aclanthology.org/1998.amta-papers.41/)

The modern dense equivalent of "fuse the two" is **query embedding interpolation**: mixing the
embedding of a query with the embedding of its translation at a controlled ratio beats the best
monolingual endpoint in **88 of 105 cases** on mMARCO with BGE-M3. Crucially the effect is
asymmetric and depends on the *document* language — mixing is uniformly beneficial when retrieving
from non-English collections, whereas "indices containing English are best served by pure English
queries." English is the strongest mixing partner for every non-English document language; after
controlling for that, gains correlate negatively with typological distance.
[arXiv:2606.13537](https://arxiv.org/abs/2606.13537)

### 5.5 PSQ: never commit to one translation, and do it at index time

Probabilistic Structured Queries use the full translation **probability matrix** as a lens on the
document-language term-frequency vector rather than a 1-best translation. The variant that matters
weights both the term-frequency and the document-frequency estimate by translation probability
(WTF/DF): TREC 2002 Arabic CLIR, English title queries — one-best baseline MAP 0.16, WTF/DF 0.20
(~25% relative), and it stays 0.19–0.20 across cumulative-probability thresholds 0.4–1.0 while
Pirkola/Kwok/MDF/WTF-only peak near 0.18–0.19 then collapse to 0.01–0.07. **The stability, not the
peak, is the contribution** — WTF/DF removes the need to tune the pruning threshold.
[SIGIR 2003](https://doi.org/10.1145/860435.860497)

The 2024 revival shows PSQ still beats both QT and DT BM25 in the neural era. Averaged over 456
topics across CLEF 2003 (fr/it/de/es), NTCIR-8 Chinese and TREC NeuCLIR 2022 (zh/fa/ru):

| Method | MAP | R@100 |
|---|---|---|
| QT-BM25 | 0.267 | 0.477 |
| DT-BM25 | 0.302 | 0.546 |
| PSQ-HMM | **0.332** | **0.585** |

Two design decisions worth copying: PSQ is moved to **indexing time** (translate documents into the
query language once, offline, into an inverted index) rather than query time, and the alignment
matrix is pruned on **multiple criteria at once** (PMF minimum-probability threshold + cumulative
CDF mass + top-k per term) because no single criterion is Pareto-optimal. Open-source Python
implementation and unpruned translation tables released.
[arXiv:2404.18797](https://arxiv.org/abs/2404.18797)

---

## 6. Hybrid lexical + dense in the cross-lingual case

Hybrid is where the wins are in multilingual retrieval, and this is not a marginal effect.

| Setting | BM25 | Dense | Hybrid |
|---|---|---|---|
| MIRACL, 18 languages, nDCG@10 | 0.393 | mDPR 0.415 | **0.578** (+47% over BM25) |
| MIRACL, 18 languages, R@100 | 0.787 | mDPR 0.788 | **0.889** |

Source: [TACL 2023](https://aclanthology.org/2023.tacl-1.63/). Mr. TyDi reached the same conclusion
first and stated it plainly in its abstract: "although the effectiveness of mDPR is much lower than
BM25, dense representations nevertheless appear to provide valuable relevance signals, improving
BM25 results in sparse-dense hybrids."
[MRL 2021](https://aclanthology.org/2021.mrl-1.12/)

For the *cross-lingual* case specifically:

- **AfriQA**: the best retrieval configuration reported is **hybrid sparse+dense with human question
  translation, 73.4% R@10**, above dense-only-with-human-translation (67.6%) and far above
  translation-free dense (19.0%). [arXiv:2305.06897](https://arxiv.org/abs/2305.06897)
- **M3-Embedding** is the practical way to get hybrid from one model: dense + sparse (lexical) +
  multi-vector from a single checkpoint, and on MIRACL the fused score (71.5) beats every individual
  mode (69.2 / 53.9 / 70.5). [ACL Findings 2024](https://aclanthology.org/2024.findings-acl.137/)
- **Agri-Query** is the closest thing to a working cross-lingual product-shaped hybrid: BM25 +
  gte-Qwen2-7B-instruct dense, fused with **RRF**, over a 165-page / ~59k-token manual, evaluated
  in EN/DE/FR. Hybrid RAG scores 0.880 (EN, Gemini 2.5 Flash) against **0.694** for feeding the same
  model the whole manual in a 128K context window; DE 0.870, FR 0.852. The benchmark is deliberately
  balanced at 108 questions — 54 answerable, 54 unanswerable — so hallucination is scored, not just
  recall. [arXiv:2508.18093](https://arxiv.org/abs/2508.18093)
- **Multi-query fusion via RRF** is the robustness mechanism, not a precision mechanism: semantic
  query expansion into several formulations, then RRF over the resulting ranked lists, "smooths
  performance variance across query formulations," i.e. it protects against a single bad query
  embedding. Reported on noisy multilingual historical documents with OCR error and language
  variation. [arXiv:2512.12694](https://arxiv.org/abs/2512.12694)
- **Weighted RRF across language shards** is the deployed pattern: when a language has fewer than
  τ=20 native exemplars in the index, fuse the cross-lingual/global index with the native-language
  shard using trust weights w_global=1.0, w_lang=2.0 and damping k=60 — the native shard trusted 2×.
  Hindi specifically ran a three-way RRF over global + English + Arabic proxy indices before earning
  a dedicated shard; final Hindi accuracy 73.5%.
  [arXiv:2607.22841](https://arxiv.org/abs/2607.22841)
- **Query expansion helps the lexical half.** LLM pseudo-document expansion lifts CLIRMatrix Hit@10
  from 69.35% (raw query) to roughly 84–85% with a zero-shot 8–12B multilingual LLM (up to ~15% on
  CLIRMatrix, ~10% on mMARCO over BM25). Query *length* largely determines which prompting technique
  works, and retrieval "is especially poor between languages written in different scripts."
  [arXiv:2511.19325](https://arxiv.org/abs/2511.19325)

**Tokenization/analysis beats merging strategy, by a lot.** The most under-appreciated CLEF result:
across 8 languages, four different merging strategies (raw score, round robin, dataset-size-based,
score-difference-per-topic) all landed between 18.2% and 18.6% average precision — a spread under
half a percentage point — while swapping the **word-normalization tool** moved English→Finnish
bilingual MAP by **44.1%** (34.0% → 19.0% when a stemmer replaced a morphological analyzer) and
English→Swedish by 29.9%, even though monolingual English was +1.5% *better* with the stemmer.
[CLEF 2003](https://ceur-ws.org/Vol-1169/CLEF2003wn-adhoc-AirioEt2003.pdf). If you run a lexical
half over Indic or agglutinative text, the analyzer choice is the lever.

---

## 7. Rerankers

Rerankers are the highest-leverage cheap addition to a cross-lingual first stage, and simultaneously
the component with the worst documented language bias. Both facts matter.

**They rescue cross-script pairs.** Cross-encoder reranking on cross-script pairs produces the
largest jumps in the entire CLIR literature: CLIRMatrix en-zh 0.0 → 30.0; mMARCO en-zh 0.0 → 91.0
with XLM-R trained on hard negatives. [arXiv:2511.19324](https://arxiv.org/abs/2511.19324)

**They make document translation redundant.** See §5.2 — DT's benefit over an NV-Embed-v2 first
stage falls from +0.026 MAP (RankZephyr) to +0.003 (RankGPT4.1).
[arXiv:2509.14749](https://arxiv.org/abs/2509.14749)

**They are where recall gets converted, and without them top-1 is unreliable.** On a multilingual
fact-check claim pool, Multilingual E5 scores S@1 38.80%, S@3 63.40%, S@5 74.40%, S@10 82.90%,
S@20 88.50%, MAP ~53 — the right item is in the top 20 nearly 90% of the time while top-1 is wrong
~61% of the time. That gap is the quantitative case for rerank-after-retrieve in a multilingual
corpus. [arXiv:2509.25138](https://arxiv.org/abs/2509.25138)

**They are systematically language-biased, and it costs measurable answer quality.**

| Finding | Number | Source |
|---|---|---|
| Multilingual rerankers ignore document language | For **English** queries, existing multilingual rerankers put a **non-English** document first **72.8%** of the time when semantically equivalent documents exist across languages | [LAMAR, arXiv:2607.22042](https://arxiv.org/abs/2607.22042) |
| BGE reranker concentrates the context | **>70%** of top-5 documents (avg over 13 languages) come from English **plus the query language alone** | [LAURA, arXiv:2604.20199](https://arxiv.org/abs/2604.20199) |
| Headroom left on the table | Recall@3-gram with Llama-3-8B-Instruct: 48.9 (BGE-Reranker-V2-M3), 47.1 (Qwen3-Reranker-0.6B) vs **63.6 oracle** — ~15 points, and *not* a coverage problem: the oracle evidence is already in the top-50 candidate pool, just downweighted. Worst on non-Latin scripts: ko 25.5 vs 41.0, th 26.4 vs 44.1, ja 29.2 vs 47.9 | [LAURA, arXiv:2604.20199](https://arxiv.org/abs/2604.20199) |

Two published fixes, at opposite ends of the objective:

- **LAURA** trains the reranker on documents that empirically produced *better generations*
  (utility averaged over four generator models, threshold 0.8) rather than on semantic relevance;
  it also partitions candidates by language and ranks within each group to guarantee balanced
  exposure. Significant at p<0.05 in 10 of 13 languages (overall p=8.62e-74); PEER language-fairness
  +~7 points for BGE. Pipeline: BGE-M3 retrieves top-50 over a unified 13-language corpus, reranker
  picks top-5. [arXiv:2604.20199](https://arxiv.org/abs/2604.20199)
- **LAMAR** goes the other way — an openly released cross-encoder (init from bge-m3-retromae) with
  stage-1 English-anchored relevance distillation (6.7M instances from MMARCO 14 langs / MIRACL 51
  langs / RLHN) and stage-2 preference alignment for **language coherence** (8.6K pairs). nDCG@1
  96.89 on XQuAD (12 langs) and 94.66 on BELEBELE (14 langs) for language coherence, while staying
  competitive on MIRACL (69.5 vs 69.7 best) and MTEB (86.84 vs 87.34). It also shows documents in
  the query's language yield higher downstream QA F1.
  [arXiv:2607.22042](https://arxiv.org/abs/2607.22042)

These two are in tension — LAURA wants language-agnostic utility, LAMAR wants query-language
coherence — and the tension is real, not a contradiction: LAURA optimises for evidence coverage,
LAMAR for downstream generation fluency. Which you want depends on whether your bottleneck is
missing evidence or wrong-language output.

**Instruction-following at the retrieval stage** is the only published surface for giving the
retriever a language policy, and it is weak: on mFollowIR (built on TREC NeuCLIR narratives for
ru/zh/fa, 123 queries total), the best bi-encoder Promptriever-Llama3.1 scores 10.4 average p-MRR
in the cross-lingual En-XX setting but drops to **5.2** in the multilingual XX-XX setting
(cross-encoder FollowIR-7B: 7.6 vs 7.7). [arXiv:2501.19264](https://arxiv.org/abs/2501.19264)

---

## 8. Which embedder for which language tier

**Read the caveats before the table.** The evidence supports a tiering, but it is *model-specific
and corpus-specific*, and two of the strongest results in this document directly contradict each
other at the low-resource end: AfriQA finds translation-free dense retrieval catastrophic (19.0%
R@10, [arXiv:2305.06897](https://arxiv.org/abs/2305.06897)) while the Sinhala/Tamil study finds
translation-free BGE-M3 beating every translation pipeline (96.2% R@15,
[arXiv:2608.12820](https://arxiv.org/abs/2608.12820)). The difference is the encoder (mDPR vs
BGE-M3) and the corpus, not the language tier. Treat this table as a starting hypothesis to
measure, never as a routing policy to hard-code.

| Tier | Examples | First choice | Add | Why / evidence |
|---|---|---|---|---|
| **A. High-resource, well-covered** | en, de, fr, es, zh, ja, ru | multilingual-e5-large-instruct (560M) or BGE-M3 | Cross-encoder rerank | Best public MMTEB model at 560M ([2502.13595](https://arxiv.org/abs/2502.13595)); no translation needed ([2504.16264](https://arxiv.org/abs/2504.16264)) |
| **B. Mid-resource, non-Latin script** | hi, ar, ko, th, bn, ta, te | **BGE-M3** (dense+sparse+multi-vec from one checkpoint) | Hybrid fusion + rerank; consider SHIFT/LangSAE if the index is mixed | M3 leads MKQA cross-lingual R@100 (75.5 vs mE5 70.9) ([2024.findings-acl.137](https://aclanthology.org/2024.findings-acl.137/)); BGE-M3 best in 8/13 Indian languages, mE5-large best in 4 incl. Hindi 0.52 MRR ([2506.01615](https://arxiv.org/abs/2506.01615)) |
| **B′. Hindi specifically** | hi | mE5-large or BGE-M3; **NLLB-E5** if you can host 3.3B | NLLB-E5 48.57 vs BGE-M3 46.18 avg NDCG@10 on Hindi-BEIR ([2409.05401](https://arxiv.org/abs/2409.05401)) — and its architecture (frozen NLLB encoder + frozen English E5 + one learned linear projection, distilled on **English data only**) bolts a language onto an English index without re-embedding the corpus |
| **C. Low-resource, script-distinct** | am, sw, yo, ig, si, km, lo, my | BGE-M3 **plus** a query-translation arm, fused | Hybrid sparse+dense; measure both arms before choosing | Evidence conflicts (see caveat). Hybrid+translation is the best AfriQA config at 73.4% R@10 ([2305.06897](https://arxiv.org/abs/2305.06897)); Amharic zero-shot ceiling is 23% relative below monolingual ([2605.24556](https://arxiv.org/abs/2605.24556)) |
| **D. Very low-resource / unusual corpus language** | sa, and similar | **Translate the documents at index time**, then monolingual retrieval | PSQ-style probability-weighted indexing rather than 1-best | DT+BM25 62.46 vs shared-embedding DR 10.74 nDCG@10 on Anveshana ([2505.19494](https://arxiv.org/abs/2505.19494)); PSQ-HMM 0.332 MAP vs QT 0.267 / DT 0.302 ([2404.18797](https://arxiv.org/abs/2404.18797)) |
| **E. Romanized / code-mixed input** *(orthogonal axis, applies to every tier)* | Hinglish, Arabizi, Greeklish | Any of the above **plus** a 50/50 native+Latinized fine-tune, and IndicLID/GlotLID rather than a script check | BGE-M3 loses 97% MRR@10 on Latinized Chinese; only the 50/50 mix repairs it ([2505.08411](https://arxiv.org/abs/2505.08411)); code-switching costs up to 27% and vocab expansion is insufficient ([2604.17632](https://arxiv.org/abs/2604.17632)); IndicLID 98.55% native vs 80.40% romanized ([2023.acl-short.71](https://aclanthology.org/2023.acl-short.71/)) |

**Anti-pattern:** do not adopt a language-*specific* embedding model for a cross-lingual system.
DeepRAG claims a 23% retrieval-precision improvement from a Hindi-only encoder with a Hindi-morphology
SentencePiece tokenizer trained on 2.7M+ Hindi samples ([arXiv:2503.08213](https://arxiv.org/abs/2503.08213))
— but its entire value proposition is a space in which a Hindi query and an English passage are *not*
comparable. Same for IndicIRSuite's eleven separate monolingual ColBERTs, which report +47.47% MRR@10
over INDIC-MARCO baselines but never evaluate any query/document language mismatch
([arXiv:2312.09508](https://arxiv.org/abs/2312.09508)). MuRIL is the partial exception — it was
pretrained with explicit translated *and transliterated* document pairs across 17 Indian languages —
but its Tatoeba cross-lingual **sentence retrieval** score is 25.15 (vs mBERT 18.41), which is
catastrophic in absolute terms for a retriever when purpose-built cross-lingual encoders sit in the
90s ([arXiv:2103.10730](https://arxiv.org/abs/2103.10730)).

**If you must improve a specific language without labels:** SWIM-IR is 28,265,848 synthetic
Wikipedia query-passage pairs across 33 languages, generated with PaLM-2 using summarize-then-ask
prompting (the LLM writes a passage summary *before* generating the query). Models trained purely on
it match human-supervised mContriever-X on XOR-Retrieve, XTREME-UP and MIRACL — zero human relevance
labels needed. [arXiv:2311.05800](https://arxiv.org/abs/2311.05800)

---

## 9. Mixed-language corpus: the retrieval-layer view

Covered fully elsewhere; here only the parts that are embedder- and reranker-shaped.

The mechanism is the §3 one. Dense retrievers "fundamentally favor monolingual alignment between
the query and the document language" — after debiasing with the DeLP metric (which factors out
exposure bias, gold-availability prior and cultural topic locality), "the strongest signal
consistently moves to the diagonal (Lq=Ld)": retrievers favour query/document **language match**,
not English per se ([arXiv:2601.02956](https://arxiv.org/abs/2601.02956)). The complementary
diagnostic is MLRS (MultiLingualRankShift), which measures preference by how much a document's rank
*improves* when it is translated into the query language; retriever preference scores are English
47.70 vs 35–38 for every other language
([arXiv:2502.11175](https://arxiv.org/abs/2502.11175)).

Measured cost on a real balanced Arabic+English corporate corpus (Legal and Travel, deliberately not
Wikipedia): M-E5 Hit@20 drops 42% (Legal) and 33% (Travel) cross-lingually with end-to-end accuracy
down 40%/37%; BGE-M3 drops 33%/13% but only in the English-query→Arabic-document direction. A
language-oracle ablation isolates the cause as **document-document** language mismatch — the
retriever ranks fine within one language but fails when a single mixed index forces it to compare
Arabic and English passages against one query. Both proposed repairs are cheap and lossless in the
same-language case ("no statistically significant loss relative to the direct retriever"), adding
~4–6% overall for BGE-M3 and ~20% for M-E5: (a) balanced retrieval — take an equal number of
passages from each language subset; (b) search the joint corpus **twice**, once with the original
query and once with its translation, then merge the ranked lists by embedding inner-product score.
[arXiv:2507.07543](https://arxiv.org/abs/2507.07543)

Model-side alternatives that avoid routing entirely:

- **Multilingual Translate-Distill (MTD)** trains ColBERT-X so relevance scores are *comparable
  across document languages*, producing one calibrated ranked list over a mixed collection. Beats
  Multilingual Translate-Train by 5% (CLEF03 nDCG@20 0.643→0.675) up to ~26% (NeuCLIR 2022), and
  15% (CLEF03 MAP 0.451→0.520) up to ~47%. It is robust to *how* languages are mixed in training
  batches (Mix Passages / Mix Entries / Round Robin all statistically equivalent) **as long as
  multiple languages appear in every mini-batch** — that batch composition is what teaches
  comparable cross-language scores. [arXiv:2405.00977](https://arxiv.org/abs/2405.00977). The same
  group's TREC 2023 run confirms it operationally: MTT with mixed-language batches was their best
  MLIR run at nDCG@20 0.362, and "a key to making MTT successful is to include documents from every
  target language in each batch" ([arXiv:2404.08118](https://arxiv.org/abs/2404.08118)).
  Predecessors: Translate-Distill ([arXiv:2401.04810](https://arxiv.org/abs/2401.04810)),
  ColBERT-X translate-train ([arXiv:2201.08471](https://arxiv.org/abs/2201.08471), where CLEF German
  MAP goes 0.263 QT-BM25 → 0.328 zero-shot → 0.397 translate-train).
- **Artificially code-switched training data** for rerankers: +5.1 MRR@10 in CLIR and +3.9 in MLIR
  on mMARCO across 36 language pairs, while monolingual IR stays flat; gains up to 2× absolute for
  distant language pairs, and it extends to unseen languages.
  [arXiv:2305.05295](https://arxiv.org/abs/2305.05295)
- SHIFT and LangSAE (§3) — index-side, training-free, no second index, no query-time cost.

Two results argue against reflexively splitting the index. Chirkova et al. ablate English-only vs
user-language-only vs **concatenated** multilingual Wikipedia across 13 languages and find
retrieval from the concatenated corpus beneficial in most cases with a single BGE-m3 retriever
([KnowLLM 2024](https://aclanthology.org/2024.knowllm-1.15/)). And KD-SPD benchmarks both
architectures head-to-head — per-language sub-search pipelines (mDPR + Round Robin, mDPR + score
merging) against a single end-to-end multilingual index — and finds "end-to-end mDPR does not show a
consistent advantage over the pipeline mDPR"
([arXiv:2305.09025](https://arxiv.org/abs/2305.09025)). Neither architecture dominates; this is an
empirical call.

If you do split and merge, the merging literature is 20+ years old and has hard numbers. Savoy &
Berger, EN/FR/FI/RU, 50 queries, round-robin baseline 0.2386–0.2430 MAP: raw-score merging
**collapses to 0.0642 (−73.1%)** when the per-language runs use different engines, but reaches
0.3067 (+30.1%) when all runs share one engine; **logistic regression on ln(rank)+RSV wins in all
three conditions** (+29.5% / +28.0% / +43.9%); biased round-robin (2 docs from each large
collection, 1 from the small one) gives a cheap +10.6%
([CLEF 2004](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf)). And the pooled-index
pathology is named precisely in CLEF 2002: pooling collections raises N in idf without raising term
occurrences, so "it makes retrieval result preferring documents in small document collection" —
directly relevant to a tenant whose index holds 3,000 English chunks and 30 Hindi ones
([CLEF 2002](https://ceur-ws.org/Vol-1168/CLEF2002wn-adhoc-LinEt2002.pdf)).

For scale calibration: TREC NeuCLIR 2024's MLIR task (one unified ranked list over ~2M Persian +
~3M Chinese + ~5M Russian documents, 51 topics, ~1,999 judgments/topic) tops out at **nDCG@20
0.545**, versus 0.664 / 0.698 / 0.593 for the corresponding single-language CLIR tasks — a mixed
index costs roughly 15–20% nDCG at TREC-grade rigour
([arXiv:2509.14355](https://arxiv.org/abs/2509.14355)). NeuCLIRBench consolidates those collections
(250,128 judgments) and — the signal worth noting — ships **a fusion baseline of strong neural
retrieval systems** as the reference first stage, i.e. the community's own reference is a fusion,
not a single index ([arXiv:2511.14758](https://arxiv.org/abs/2511.14758)).

---

## 10. What to measure at this layer

- **nDCG/Recall alone is insufficient on a mixed pool.** Track **Language Preference Rate** and
  **Lang-nDCG** alongside it, with MLAIRE's 4-way failure decomposition; they are near-orthogonal to
  semantic quality ([arXiv:2605.07249](https://arxiv.org/abs/2605.07249)).
- **PEER** (Probability of Equal Expected Rank) is a drop-in ir-measures-compatible fair-ranking
  metric using Kruskal-Wallis equivalence, with no language designated as protected —
  `github.com/hltcoe/peer_measure` ([arXiv:2405.00978](https://arxiv.org/abs/2405.00978)).
  **MRC@k** (mean rank correlation between ranked lists for semantically identical queries in
  different languages over the same collection) is the complementary fairness number; vanilla DPR
  scores MRC@5 of 13.1 (mBERT) / 11.7 (XLM-R) on MultiEuP-v2, i.e. top-5 lists are largely *not*
  shared across query languages ([arXiv:2509.06195](https://arxiv.org/abs/2509.06195)).
- **MLRS** — rank improvement when a document is translated into the query language — is a directly
  reusable per-corpus diagnostic for same-language collapse
  ([arXiv:2502.11175](https://arxiv.org/abs/2502.11175)).
- **Retrieval rank@1 does not prove grounding across a language boundary.** Up to ~47% of
  cross-lingual QA answers that *exactly match* the gold reference are not attributable to any
  retrieved passage (Japanese; attribution ranges 53.1% JA to 93.1% TE). A cheap guardrail exists:
  PaLM 2 fine-tuned on only ~100 attribution examples reaches 92–96% accuracy / 95–98% ROC AUC at
  detecting attribution ([arXiv:2305.14332](https://arxiv.org/abs/2305.14332)).
- **Standard cross-lingual retrieval sets to run against** instead of a bespoke query set:
  XOR-Retrieve ([NAACL 2021](https://aclanthology.org/2021.naacl-main.46/)), LAReQA's mixed pool
  ([arXiv:2004.05484](https://arxiv.org/abs/2004.05484)), CLIRMatrix BI-139 / MULTI-8
  ([EMNLP 2020](https://aclanthology.org/2020.emnlp-main.340/)), NeuCLIR/NeuCLIRBench
  ([arXiv:2511.14758](https://arxiv.org/abs/2511.14758)), MTEB(Indic) via MMTEB
  ([arXiv:2502.13595](https://arxiv.org/abs/2502.13595)).
- **Do not forget encoder-specific input conventions.** multilingual-e5 requires `query: ` /
  `passage: ` prefixes "even for non-English texts"
  ([model card](https://huggingface.co/intfloat/multilingual-e5-large)); omitting them silently
  degrades retrieval and would be indistinguishable from a genuine cross-lingual failure in any
  weak-similarity signal you compute.

---

## 11. Where the literature is silent

Stated as verified absences from the sweep, not as opportunities.

1. **No published retriever gates on writing-system presence in the corpus.** Script is used
   everywhere as an *analysis* variable — "cross-script pairs" are the hardest in
   [arXiv:2511.19324](https://arxiv.org/abs/2511.19324), "script-distinct languages" get the largest
   gains in [arXiv:2601.04768](https://arxiv.org/abs/2601.04768) — but nothing uses it as a runtime
   routing signal. Note the evidence cuts *against* the idea: purpose-built CLIR dense retrievers'
   advantage over lexical and document-translated baselines is largest precisely on cross-script
   pairs ([arXiv:2511.19324](https://arxiv.org/abs/2511.19324)), and a script check is blind to
   romanized input ([arXiv:2505.08411](https://arxiv.org/abs/2505.08411),
   [ACL 2023](https://aclanthology.org/2023.acl-short.71/)).
2. **No published method conditions query translation on the retrieval score of a first-pass
   search.** Every strategy in the taxonomy is unconditional: tRAG always translates the query,
   CrossRAG always translates documents, DKM-RAG always translates reranked passages
   ([arXiv:2502.11175](https://arxiv.org/abs/2502.11175)), QTT-RAG always translates and scores
   foreign documents ([arXiv:2510.23070](https://arxiv.org/abs/2510.23070)), DELTA always builds a
   five-segment fused query ([arXiv:2601.02956](https://arxiv.org/abs/2601.02956)). The nearest
   published gate is Syfer's, and it triggers on **sub-question drift** (cos < τ, τ=0.8), not on
   retrieval score ([arXiv:2608.13160](https://arxiv.org/abs/2608.13160)).
3. **No quality-vs-translation-call-budget curve.** Cost-explicit papers optimise by model choice,
   not by gating: ~15.6 s/query on a T4 ([arXiv:2601.02065](https://arxiv.org/abs/2601.02065)),
   DELTA 1.13 s/query vs DKM-RAG 3.80 ([arXiv:2601.02956](https://arxiv.org/abs/2601.02956)),
   89% cost reduction via 4-bit quantization ([arXiv:2511.08343](https://arxiv.org/abs/2511.08343)).
   Nobody reports retrieval quality as a function of how often the expensive path fires — despite
   direct evidence that unconditional translation is harmful in specific cells (Llama-3 extractive
   F1 on Hindi: 46.76 direct vs 26.22 translate-test, while Assamese goes 21.29 → 33.01,
   [arXiv:2407.13522](https://arxiv.org/abs/2407.13522); every translation strategy degraded Hindi
   with Llama-3.1-8B by up to 10.9 points, [arXiv:2507.22923](https://arxiv.org/abs/2507.22923)).
4. **No per-query router over the strategy space.** Each of tRAG/monoRAG/MultiRAG/CrossRAG/DELTA/
   QTT-RAG is evaluated as a fixed global policy, even though the precondition for routing is proven
   twice ([arXiv:2507.22923](https://arxiv.org/abs/2507.22923),
   [arXiv:2407.13522](https://arxiv.org/abs/2407.13522)) and DELTA notes its own gains vanish when
   the query is already English.
5. **No published operational threshold for "when does query translation lose to a multilingual
   embedder."** CLIRudit gives the qualitative failure class (proper nouns, domain terminology);
   [arXiv:2606.13537](https://arxiv.org/abs/2606.13537) gives the index-composition asymmetry and
   explicitly declines to propose per-query gating. There is no "translate if X" rule.
6. **No cross-lingual *retrieval* benchmark for Hindi.** XOR-TyDi's only Indic languages are Bengali
   and Telugu ([NAACL 2021](https://aclanthology.org/2021.naacl-main.46/)). IndicGenBench's
   XorQA-In-Xx is exactly (Hindi question, English passage, Hindi answer) across 28 languages and
   ~32k examples — but it **supplies the gold English passage**, so there is no index and no
   retrieval ([arXiv:2404.16816](https://arxiv.org/abs/2404.16816)). IndicRAGSuite, Hindi-BEIR and
   IndicIRSuite are monolingual. HEALTH-PARIKSHA has the right shape (English-only KB,
   ada-002 embeddings, top-3 chunks, Hindi/Tamil/Telugu/Kannada queries) but only 19 Hindi pairs out
   of 749 ([arXiv:2410.13671](https://arxiv.org/abs/2410.13671)).
7. **No ablation of RRF against the classical merging strategies (Z-score, logistic regression on
   rank+score) for dense per-language sub-searches.** The classical numbers exist for lexical runs
   ([CLEF 2004](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf)); modern MLIR work
   mostly attacks the problem inside the model instead, and where fusion is used it is RRF by
   default ([arXiv:2607.22841](https://arxiv.org/abs/2607.22841),
   [arXiv:2508.18093](https://arxiv.org/abs/2508.18093)).
8. **No per-tenant / dynamically-composed mixed-corpus work.** Every mixed-corpus fix assumes a
   fixed, large, known language inventory with parallel data available: SHIFT calibrates on 533k
   parallel pairs ([arXiv:2606.18801](https://arxiv.org/abs/2606.18801)), MTD needs a training
   pipeline ([arXiv:2405.00977](https://arxiv.org/abs/2405.00977)), RAGTIME assumes ~1M documents
   per language collection ([arXiv:2602.10024](https://arxiv.org/abs/2602.10024)), DS@GT's
   shard-vs-fuse decision keys on τ=20 native exemplars in a 30k-entry KB
   ([arXiv:2607.22841](https://arxiv.org/abs/2607.22841)). A tenant with 12 English PDFs and 3 Hindi
   ones is outside all of it. Mitigating detail: SHIFT's language vectors are per **language pair**,
   not per corpus, so they can be precomputed once globally and applied at ingest to any tenant.
9. **No published cosine-similarity-by-script distributions.** Degradation is always reported as
   nDCG/MRR/Recall, never as raw similarity distributions per script — which is what any
   similarity-threshold gate actually needs to be calibrated against.
10. **Sparse per-language coverage for Southeast Asian scripts.** The sweep found no comparable
    retrieval-degradation measurements for Khmer, Lao or Burmese; the low-resource evidence base
    here is Amharic, the AfriQA languages, Sinhala/Tamil and Indic.
