# BYOK Threshold Design: the cross-lingual gate when every project runs a different embedding model

Scope: the design of `cross_lingual_similarity_floor` — one global env constant, compared against the best raw cosine from the search that already ran, used to decide whether to translate the query and re-embed. Oreag cannot force a model; it can recommend, warn, sort, label, or default. Every claim below carries its source. Vendor-self-reported numbers are labelled at each use. Numbers I could not confirm are marked UNVERIFIED.

Stack constraints assumed throughout: `chunks.embedding` is `vector` with no fixed dimension (model switch = re-embed, no DDL); HNSW partial indexes exist only for dims {256, 384, 512, 768, 1024, 1536}; retrieval is pgvector cosine + Postgres FTS fused with rank-only RRF k=60.

---

## 1. The problem, precisely

One constant sits on top of N score distributions that differ along **five independent axes**. Each axis is separately sufficient to break it.

### 1.1 Axis one — the per-model anisotropy floor (additive offset)

Mean cosine between *random* pairs ("RandCos") differs by ~40x across encoder families:

| Model | RandCos (mean random-pair cosine) |
|---|---|
| all-mpnet-base | 0.016 |
| all-MiniLM-L6-v2 | 0.018 |
| all-MiniLM-L12 | 0.019 |
| BGE-large | 0.308 |
| E5-large | 0.696 |
| multilingual-E5-large | 0.707 |
| ELECTRA-base | 0.907 |
| GPT-2 | 0.996 |

Source: <https://arxiv.org/html/2606.29571> (19 encoders, pooled over STS-B, SICK-R, STS16, Quora, PAWS, SNLI, MultiNLI). Caveat from that same finding: the E5-family numbers were presumably measured **without** the mandatory `query:`/`passage:` prefixes, so treat them as an upper bound on the deployed null.

Direct consequence for Oreag: a floor near 0.40 is *below the noise floor* of `together/intfloat/multilingual-e5-large-instruct` (whose family sits at ~0.70) and *far above* the typical signal on `sentence_transformers/all-MiniLM-L6-v2` (family ~0.02). On the first the gate can essentially never fire; on the second it can essentially always fire. That is an inference from the published RandCos values above, not a measurement on Oreag's own corpora — flag as such.

The same paper adds a metric-choice warning that matters for the local models in the catalog: on spaces with RandCos > 0.5, "rank-based and L1-type metrics beat cosine by a clear margin" (~0.055 Spearman), i.e. on crowded encoders cosine is not merely miscalibrated, it is the wrong comparison function (<https://arxiv.org/html/2606.29571>). pgvector's HNSW pins one distance operator per index, so Oreag cannot switch metric per project without re-indexing.

### 1.2 Axis two — the threshold needed for a fixed precision target differs ~10x across models, and also across corpora for the *same* model

Synthetic Query Probing generated 100 chunks × 10 queries × 3 relevance classes = 3,000 pairs per corpus and read off the cosine threshold required to hit 0.95 precision (<https://arxiv.org/html/2608.05857>):

| Model | SciFact | Enterprise corpus |
|---|---|---|
| Titan-1024 | 0.063 | 0.393 |
| Titan-512 | 0.090 | 0.400 |
| Titan-256 | 0.144 | 0.439 |
| ada-002 | 0.718 | 0.821 |

Two readings, both fatal to a single constant: ada-002 needs a threshold ~10x higher than Titan-1024 on the same corpus, **and** the same ada-002 model needs 0.718 vs 0.821 across two corpora — enterprise thresholds ran "roughly six times higher" than the scientific corpus for the same model. The same study reports IRRELEVANT-class mean similarity of Titan-1024 at 0.02 (SciFact) / 0.19 (enterprise) versus ada-002 at 0.69 / 0.75, with ada compressing all scores into 0.63–0.93 and standard deviations "two to six times smaller" than Titan. Class *ordering* was preserved everywhere; only the scale moved.

The Calibrated Similarity paper states the conclusion outright: "a threshold of 0.8 has no consistent semantic interpretation across models or datasets" (<https://arxiv.org/html/2601.16907>). Honest limitation on that source: it evaluated exactly one model (Xenova/paraphrase-mpnet-base-v2, 768-dim), so its cross-model generality is asserted, not demonstrated.

### 1.3 Axis three — vectors from different model families are barely correlated at all

RAGFlow gates an embedding-model swap on re-encoding 5–10 sampled chunks with the candidate model and averaging the cosine between new and old vectors; ≥0.9 allows the swap, below denies it. Their stated empirical figure: "embeddings from completely different model families (for example, MiniLM to BGE-M3) tend to sit around 0.3–0.6 in similarity" (<https://ragflow.io/blog/ragflow-seamless-upgrade-from-0.21-to-0.22-and-beyond>, vendor-self-reported). Anyone arguing one cosine constant is fine across 22 catalog entries has to explain that number.

### 1.4 Axis four — cross-lingual capability itself spans the full range of the metric

The floor exists to detect cross-lingual retrieval failure, and the underlying capability differs by more than the entire usable range of cosine. Independent MTEB-run figures (parsed from <https://github.com/embeddings-benchmark/results>):

| Model | Belebele eng→tam nDCG@10 | Belebele eng→hin | IndicCrosslingualSTS en-ta (cosine Spearman) | IndicCrosslingualSTS 12-lang mean |
|---|---|---|---|---|
| gemini-embedding-001 | 0.9228 | 0.9269 | 0.7049 | 0.6287 |
| cohere embed-multilingual-v3.0 | 0.8478 | 0.8713 | 0.4776 | 0.4673 |
| openai text-embedding-3-large | 0.2146 | 0.6887 | 0.0056 | 0.1259 |
| openai text-embedding-3-small | 0.0651 | 0.2329 | −0.0367 | 0.0413 |

On `text-embedding-3-large`, a Tamil sentence and its exact English translation are essentially uncorrelated (en-ta cosine Spearman 0.0056). On `all-MiniLM-L6-v2` the same statistic is −21.0 ×10⁻² (MMTEB, <https://arxiv.org/html/2502.13595>, where MTEB(Indic) STS = IndicCrosslingualSTS; all-MiniLM-L6 row: Avg 31.8, Bitext 2.5, STS −6.3, Retrieval 6.2, rank 12/12). A cosine value that means "translate now" on Gemini means "retrieval is impossible on this model, translating is the only mode that ever works" on MiniLM.

There is a second, subtler failure here. English-only encoders return finite, well-formed, plausible cosines on Devanagari or Tamil text — the mechanism was verified empirically by counting tokenizer coverage: all-MiniLM-L6-v2, nomic-embed-text-v1.5 and mxbai-embed-large-v1 all carry the same bert-base-uncased 30,522-token WordPiece vocabulary with only 70 Devanagari and 36 Tamil bare isolated letters. So a Hindi query is shredded into single characters and `[UNK]`, and the API still returns a unit vector. The gate reads a number that carries no signal in either direction.

### 1.5 Axis five — the same model's cross-lingual cosine varies by language, and by dimension

Within a single multilingual model, average cosine of positive (translation-equivalent) pairs ranged from ~0.8 (Portuguese) to ~0.2 (Tamil) on SBERT distiluse-base-multilingual-cased; LASER3 produced high positives (0.7–0.8) but also high negatives (~0.55) versus ~0.05 negatives for SBERT (<https://primer.ai/developer/language-agnostic-multilingual-sentence-embedding-models-for-semantic-search/> — industry blog, not peer-reviewed; the underlying anisotropy mechanism is corroborated by <https://arxiv.org/html/2606.29571>). One constant therefore mis-fires per *language* even on one model.

And before any model changes: the standard deviation of pairwise cosine decays as approximately m^(−1/2) in dimension m, with "both the expectation and the standard deviation decay at the same rate" (<https://arxiv.org/html/2606.28330>). The practitioner form of the same claim: "A score of 0.30 at 768-dim might correspond to 0.35 at 256-dim for the same pair" (same source, UNVERIFIED as an independent measurement). Oreag exposes Matryoshka options on six catalog entries (512/1536; 256/1024/3072; 768/1536/3072; 256/512/1024), so changing a *picker default* silently retunes the gate with no code change.

### 1.6 Three implementation traps that shift the distribution before any of the above applies

1. **Asymmetric encoders.** `jina-embeddings-v3` swaps `retrieval.query` / `retrieval.passage` LoRA adapters (<https://arxiv.org/abs/2409.10173>); `nomic-embed-text-v1.5` requires `search_query: ` / `search_document: ` prefixes; E5 requires `query: ` / `passage: ` ("otherwise you will see a performance degradation", <https://huggingface.co/intfloat/multilingual-e5-large-instruct>); Cohere and Voyage take `input_type`. If queries and chunks go through one symmetric code path, accuracy drops *and* the cosine scale moves.
2. **Gemini truncation is unnormalised.** For `gemini-embedding-001`, "you must manually normalize non-3072 dimensions"; only gemini-embedding-2 auto-normalises truncated dims (<https://ai.google.dev/gemini-api/docs/embeddings>, vendor). The exact configuration Oreag wants for an HNSW index (1536) is the one that returns unnormalised vectors. pgvector's `<=>` self-normalises and is safe; `<#>` and any numpy dot are not, and will silently depress similarity — pushing scores below the floor and firing the translate path spuriously on the user's own metered key. OpenAI is the opposite: vectors are unit-norm including when the `dimensions` parameter is used, and renormalisation is required only for client-side slicing (<https://developers.openai.com/api/docs/guides/embeddings>, vendor).
3. **RRF destroys the quantity.** Rank-only RRF "operates purely on rank indices, discarding any absolute similarity or distance information" so "the RRF score reflects how highly the retrievers ranked a document, not how relevant it is" (<https://dev.to/aws-builders/reciprocal-rank-fusion-rrf-how-it-works-and-when-to-skip-it-4obi>, engineering blog; the mechanism is definitional to RRF). Azure documents the same and applies its threshold pre-fusion for exactly this reason: "Filtering occurs before fusing results from different recall sets" (<https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/search/hybrid-search-ranking.md>). Oreag's current design — gate on the best raw cosine from the leg that already ran — is correct on this axis and must survive any refactor.

**Summary of Section 1.** The cross-model difference is *affine* (different additive floor, different spread) plus a genuine capability difference plus a per-language and per-dimension shift. No single raw-cosine constant can be correct across the catalog, and nothing in the literature claims otherwise.

---

## 2. Option A — user-tuned per-project cosine floor

**The design.** Expose `cross_lingual_similarity_floor` per project; the user sets it.

### 2.1 What it costs the user

To set it correctly the user must know, for their specific project:

- The **null baseline** of their model — the cosine an unrelated pair earns. Published for only a handful of models (§1.1); not published by any vendor for `text-embedding-3-small`, `text-embedding-3-large`, `gemini-embedding-001`, `mistral-embed`, the Voyage line, `jina-embeddings-v3`, `embed-v4.0`, `embed-multilingual-v3.0`, `nomic-embed-text-v1.5`, or `mxbai-embed-large`.
- That the number is **corpus-dependent as well as model-dependent** — the same model needed 0.718 vs 0.821 on two corpora at the same precision target (<https://arxiv.org/html/2608.05857>).
- That the number is **language-dependent within their own corpus** (§1.5).
- That the number **changes when they change dimension** (§1.5), including when Oreag changes a default.
- That the number is a **similarity, not a distance** — Qdrant documents that `score_threshold` "may exclude lower or higher scores depending on the used metric"; Elasticsearch is explicit that "The similarity value calculated relates to the raw `similarity` used. Not the document score" (<https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrievers/knn-retriever>).

Cohere is the only catalog vendor that publishes a recipe, and it is manual: take 30–50 representative queries, pair each with a **borderline-relevant** document, score them, and "the average of `sample_scores` can then be used as a reference when deciding a threshold" — alongside the warning that "The score is query dependent" and "you can't assume that a document with a relevance score of 0.9109375 is twice as relevant as one with a relevance score of 0.04421997" (<https://docs.cohere.com/docs/reranking-best-practices>, vendor documentation, not peer-reviewed). Note this is guidance for a *reranker* whose scores are already normalised to [0,1]; raw embedding cosines are a harder case, not an easier one.

The borderline-document half of that recipe requires human judgement about relevance. That is the real cost: not "type a number" but "hand-label 30–50 borderline pairs, per project, per model change, per corpus change."

### 2.2 Failure modes when it is set wrong

The two directions are **asymmetric**, which is why the industry default is to fail open:

| Setting | Failure | Who pays |
|---|---|---|
| Too high | Translation fires on every query: extra LLM call, extra embedding call, extra latency, on every request | The user's own BYOK key and metered spend, permanently |
| Too low | Translation never fires | Silent bad answers; looks like "the model is bad at cross-lingual" |

Open WebUI ships `RAG_RELEVANCE_THRESHOLD` at **default 0.0** — inert until deliberately enabled — across four embedding engines (SentenceTransformers / Ollama / OpenAI / Azure OpenAI), documented as "the relevance threshold to consider for documents when used with reranking" (<https://github.com/open-webui/docs/blob/main/docs/reference/env-configuration.mdx>). That is the safe default for an untunable constant.

Two more failure modes specific to a raw exposed number:

- **Direction inversion.** pgvector `<=>` returns cosine *distance*. A floor written against distance and one written against `1 − distance` are inverted, and a single constant makes that silent. Name and type it unambiguously (`cross_lingual_min_cosine_similarity`), assert `0 ≤ floor ≤ 1` at startup, and test that the compared value is the similarity and not the fused RRF score.
- **Range-unknown thresholds break in practice.** LangChain's `similarity_score_threshold` retriever emits `UserWarning: relevance scores must be between 0 and 1` and can return negative scores depending on the backend's distance semantics (<https://github.com/langchain-ai/langchain/issues/10864>, <https://github.com/langchain-ai/langchain/issues/13437>). Azure's countermeasure is to publish the band: vector `@search.score` under cosine is documented as **0.333 – 1.00**, so a typed constant is guaranteed to land inside a known range (<https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/search/hybrid-search-ranking.md>). Oreag compares against a raw pgvector cosine with no published band per model.

### 2.3 Where a user-tuned floor IS the right answer

Being fair to this option:

- **Single-model, single-corpus, stable deployments.** All five sources of variance are held constant, so one number *is* correct, and a user who has measured it on their own data knows more than any automatic procedure will infer. Cohere's own recipe presumes exactly this situation.
- **As an override, not a default.** Someone who has run 50 labelled queries should be able to write the answer down. Removing that capability is worse than exposing it.
- **As an escape hatch when calibration is impossible.** A brand-new project with 30 chunks cannot be calibrated (§4.6); a manual value beats a badly-estimated one.
- **In a tuning sandbox.** RAGFlow's Retrieval Testing lets a user change threshold, vector-vs-keyword weight, top-k and rerank model, and explicitly does *not* persist them: "Parameter changes in Retrieval Testing are only used for the current test and are not automatically synchronized to Chat Assistant or Agent" (<https://github.com/infiniflow/ragflow/blob/main/docs/guides/dataset/retrieval_testing.md>). Tuning without risking production retrieval is a genuinely good use of a raw number.

What Option A cannot be is the *primary* mechanism for a BYOK product whose users pick a provider per project and never see a cosine again.

---

## 3. Option B — scale-free statistics that need no tuning

This is the section that decides the design, so it reports negative results first and in full.

### 3.1 NEGATIVE: raw score dispersion (NQC / WIG / SMV / σ-x%) does not transfer

Exact forms, from the QPP survey (<https://ar5iv.labs.arxiv.org/html/2305.10923>): NQC = std(top-k)/Score(q,D) with k=100; WIG = mean over top-k of (1/√|q|)·[Score(q,d) − Score(q,D)] with k=5; SMV normalised by Score(q,D) with k=100; σ_x% = std over documents scoring at least x% of the top score, x=50.

Three independent disqualifiers:

1. **The normaliser does not exist.** Score(q,D) is the query's score against the whole collection treated as one document. There is no cosine analogue. Every surrogate re-introduces per-model tuning.
2. **Neither is affine-invariant.** NQC divides, so it survives rescaling but not an additive offset. WIG subtracts, so it survives an offset but not rescaling. The difference between embedding models is *both* (different anisotropy floor and different spread, §1.1–1.2). Neither survives it.
3. **The empirical record on dense retrieval is negative.** On ROBUST with BM25, LETOR features reach r=0.459 while dense predictors reach r=0.151 (bi-encoder) and r=0.069 (cross-encoder); on MS MARCO the classical predictors go **negative** — UQC r=−0.123, NQC r=−0.010. Per-query MAE on nDCG reaches 0.167, ±32.7% of a mean system performance of 0.511. Predictors that work on ROBUST and GOV2 "do not generalise to other collections (WT10G and MS-MARCO)" (<https://arxiv.org/html/2504.01101>). Even where NQC works it is unstable across years: Kendall τ 0.463 on TREC DL 2019 vs 0.082 on DL 2020 for ANCE nDCG@10 (<https://arxiv.org/html/2310.11405>).

Each also carries per-collection-tuned cutoffs (k=5, k=100, x=50). **Verdict: not comparable across models, and not predictive on dense retrieval. Do not ship.**

### 3.2 NEGATIVE: the naive top-1 margin is worse than the cosine it replaces

The obvious cheap fix — "use the gap between rank 1 and the rest instead of an absolute cosine, because relative must be better than absolute" — was measured head to head. Cosine separates relevant from irrelevant chunks at **AUC 0.72**; the top-1 margin-over-the-bundle rule reaches only **AUC 0.57**, barely above the 0.5 coin flip. Absolute cutoff and gated abstention sit at 0.69–0.72. Setup: EmbeddingGemma 300M over 87 guideline documents / 63,650 passages, cosine against LLM-judged (Qwen) chunk relevance. The same source states a rule of thumb that a signal needs roughly **AUC 0.80** before a single global cutoff on it is accurate enough to act on — which none of the measured signals reach. Source: <https://arxiv.org/abs/2606.29580>. **UNVERIFIED: this is a preprint and the abstract page presented as withdrawn when fetched — treat the exact figures as indicative, not settled.** The direction is consistent with §3.1.

The lesson generalises: invariance is necessary but nowhere near sufficient. The raw margin is shift-invariant (both terms shift equally) and still uninformative. A statistic must be invariant **and** discriminative.

### 3.3 NEGATIVE (transfer): predictor quality does not carry across rankers

Oreag's situation — many rankers, one signal that must mean the same thing on all of them — is measured directly. Over 97 TREC DL queries across 8 rankers: predicting query difficulty for a *fixed* ranker, NQC reaches Kendall τ 0.381 on AP@50 (beating supervised BERTQPP at 0.209); predicting which *ranker* wins for a given query, the ordering **reverses** — BERTQPP 0.117, NQC 0.085. Correlation between the two settings' performance: **−0.053**, essentially zero and slightly negative (<https://arxiv.org/html/2601.17359v1>).

This is a guardrail on evaluation, not a statistic: any candidate signal must be benchmarked **across** the catalog (hold corpus and queries fixed, vary the embedding model), because a signal that looks excellent on `text-embedding-3-small` may be uninformative on `mistral-embed` and a single-model number will not warn you.

### 3.4 NEGATIVE (evaluation method): correlation with nDCG is the wrong instrument

13 QPP models across score-based, robustness-based and neural families were scored both by correlation and by downstream usefulness in fusion weighting. NQC had the **best** correlation with AP on TREC DL'19 (τ=0.386) and did **not** produce the best downstream fusion results. Correlation between the standard-evaluation ranking of predictors and their downstream effectiveness was only τ=0.4805 (DL'19) and 0.6798 (DL'20); per-query correlations between predictor accuracy and downstream gain were ρ=0.27–0.57 (<https://arxiv.org/html/2601.17339v1>). Notably, the best downstream configuration came from RSD, a *robustness/perturbation*-based predictor, not a score-magnitude one — consistent with the broader pattern that stability-derived signals transfer better than magnitude-derived ones.

Oreag's decision is binary (translate / don't). It must be evaluated as a binary decision — AUROC and risk–coverage against a relevance label — not by correlation with a continuous quality metric. AUROC is the right instrument specifically because it is independent of base accuracy, and base accuracy differs enormously across the catalog (§1.4).

### 3.5 POSITIVE: neighbourhood-relative scoring (ratio margin, CSLS)

**Ratio margin** (Artetxe & Schwenk, ACL 2019, <https://aclanthology.org/P19-1309/>) was written to remove a hard cosine threshold from cross-lingual bitext mining — the closest published match to Oreag's exact problem. Its stated motivation is that cosine is "not being globally consistent" and that "some sentences without any correct translation have overall high cosine scores." Score(x,y) = cos(x,y) divided by the mean cosine of x and y to their k nearest neighbours. BUCC EN-DE mining F1: absolute/cosine threshold 77.0–82.8, distance margin 94.4–94.5, **ratio margin 94.8** — 12 to 18 F1 points purely from replacing an absolute threshold with a neighbourhood-relative one.

Comparability: **partial.** A per-model *multiplicative* rescale cancels exactly in the ratio. A per-model *additive* offset c does not — (s₁+c)/(mean+c) compresses toward 1 as c grows — so a high-anisotropy model yields ratios closer to 1. The compression is monotone and far weaker than the raw-cosine spread it replaces, but the usable trigger band will be narrower on high-anisotropy models.

**CSLS** — CSLS(x,y) = 2·cos(x,y) − r_src(x) − r_tgt(y), where r is the mean cosine to k nearest neighbours — is the additive twin, and it is the rare result measured on **five of Oreag's actual catalog models** rather than on academic encoders (<https://arxiv.org/html/2605.26575>):

| Model | Cross-lingual mutual-NN reciprocity, cosine → CSLS | Recall@1 |
|---|---|---|
| gemini-embedding-001 | 26.5% → 33.8% | — |
| mistral-embed | 9.4% → 21.4% | 0.111 → 0.141 |
| openai text-embedding-3-large | 19.3% → 30.0% | 0.144 → 0.165 |
| openai text-embedding-3-small | 10.9% → 24.2% | — |
| qwen3-embedding-8b | 17.7% → 28.8% | 0.146 → 0.188 |

Mean gap closure 63.5%, over 6,518 idiomatic expressions in English, Bangla, Hindi and Arabic. The study also settles a mechanism question: **hub mass explains 49.5% of the variance in retrieval reciprocity, while anisotropy's partial R² is 0.003** (pairwise correlation with reciprocity r=+0.006). Hub mass — the share of NN retrievals taken by the top 1% of vectors — ranges 0.173–0.315 (Gemini) to 0.212–0.539 (OpenAI-3-small). CSLS beat surgical hub ablation by a 130x effect size (Cohen's d 2.38 vs 0.03). Stated deployment cost: ~7% marginal per query, with the gallery term cacheable at index time. The paper's explicit recommendation is that multilingual RAG pipelines replace cosine with CSLS as the default retrieval metric.

Comparability: **CSLS is shift-invariant exactly** — 2(s+c) − (r₁+c) − (r₂+c) = 2s − r₁ − r₂ — where the ratio margin is scale-invariant. Since the measured cross-model spread is dominated by the additive RandCos floor (0.308 → 0.996, §1.1), CSLS is the better-matched correction, and it has direct cross-model evidence: consistent gains on five production models with **no per-model retuning**.

Implementation note for Oreag: the query-side neighbourhood term is free (the top-k is already materialised). The document-side term is one float column per chunk, computed at ingest, and **must be recomputed on re-embed** — which is fine, since a model switch already forces a full re-embed. On 3072-dim projects (exact scan, no index) the ingest-time kNN pass is the expensive part; sample it.

### 3.6 POSITIVE: shape-of-the-curve statistics (knee detection, EVT)

**Tail-Aware Adaptive-k** normalises the ranked similarity curve to [0,1] on both axes, finds the knee by maximum deviation from the diagonal, then fits a Generalized Pareto Distribution in a window of size ⌈√(N log N)⌉ around the knee and truncates where the Cramér–von Mises statistic stabilises (<https://arxiv.org/html/2606.11907>). F1 on WebQuestions / 2WikiMultiHopQA / MuSiQue: **65.86 / 65.81 / 66.34 vs oracle 68.75 / 67.79 / 68.38** — within 2.04 to 2.89 points of oracle, highest among dynamic selection methods. Complexity drops from O(N²M) to O(N + √(N log N)·M).

Comparability: **yes, by construction and with published cross-model evidence** — validated across four encoders (Bailian-text-embedding-v4, BGE, Contriever, Qwen3) **and** five dimensions (64/256/384/768/1024, overlapping Oreag's Matryoshka options), with the paper describing it as "model-agnostic" and "independent of absolute score values." Normalising both axes inside a single query's own list makes it invariant to any affine transform, absorbing both the additive floor and the spread.

**Surprise** (<https://arxiv.org/html/2010.09797>) is the ancestor: fit a GPD to the non-relevant tail of one query's result list and report −log(1 − G(s − u)), which converts to a p-value (Surprise 2.3 ↔ p=0.1, 4.6 ↔ p=0.01) on every model, corpus and language. Be honest about its accuracy: Robust04 F1 0.251 (BM25) and 0.268 (DRMM) vs BiCut 0.244/0.262 and Global-k 0.248/0.263 — it beats BiCut by 0.007 F1. **Its value to Oreag is the calibrated unit, not an accuracy win.**

Both need a real tail to fit against. On a top-10 list the GPD fit is unreliable; retrieve deep (100+). Pleasant interaction with Oreag's stack: the 3072-dim projects that exact-scan every chunk supply the whole distribution for free, so EVT is *cheaper* there, not more expensive. And the fit must run on the dense candidate list **before** RRF, which destroys scores by design (§1.6).

The shipped-product shallow end of the same idea is Weaviate's `autocut`, which cuts at score discontinuities and takes an integer number of "jumps" rather than a value; documented behaviour on distances [0.1899, 0.1901, 0.191, 0.21, 0.215, 0.23] is autocut:1 → first three, autocut:2 → first five (<https://weaviate.io/blog/hybrid-search-fusion-algorithms>). Two caveats Weaviate itself documents: with a small search limit, results are "very sensitive to the limit parameter due to the normalization of the scores" (their mitigation: search internally at limit 100 and trim), and the jump-detection algorithm is not published — there is **no published accuracy evaluation of autocut at all**. Prefer the knee+EVT formulation, which has F1-vs-oracle numbers across four encoders and five dimensions.

**Critical blind spot for Oreag's specific gate:** a knee/jump statistic says nothing when *nothing* is relevant — a uniformly bad list has no knee. That is exactly the cross-lingual failure case. Use curve-shape statistics for result trimming; do not make them the sole abstain/translate trigger.

### 3.7 POSITIVE but structurally wrong for this gate: dense/lexical rank agreement

Oreag already computes both ranked lists before RRF fuses them. Per-query agreement between them (overlap@k or Rank-Biased Overlap) is **completely scale-free** — it reads only positions — and costs literally nothing. RRF's founding result is that ignoring scores and fusing ranks beats Condorcet Fuse and every individual system, with k=60 found empirically on TREC data (<https://www.semanticscholar.org/paper/Reciprocal-rank-fusion-outperforms-condorcet-and-Cormack-Clarke/9e698010f9d8fa374e7f49f776af301dd200c548>). Evidence that agreement has real dynamic range: DPR's rankings have RBO ~0.1 against BM25 while SPAR reaches ~0.5–0.6.

Two honest caveats. First, **no published study evaluates per-query dense/lexical rank agreement as a retrieval-failure predictor across embedding models** — the RBO figures come from a model-comparison context, not a per-query confidence context. This is an unvalidated hypothesis, not a finding. Second, and disqualifying for *this* gate: on a genuinely cross-lingual query the lexical list is near-empty by construction, so agreement collapses for reasons unrelated to retrieval quality. It is a plausible general "did retrieval fail" signal and a poor cross-lingual trigger.

(Also worth noting on fusion: <https://arxiv.org/html/2210.11934> finds RRF "sensitive to its parameters" and reports a tuned convex combination beating it in and out of domain — but that tuning is per-domain, which a BYOK product cannot do. RRF stays.)

### 3.8 POSITIVE and genuinely ranker-agnostic: content-based judgment

**QPP-GenRE** discards the score entirely: an LLM emits a binary relevance judgment per query–document pair, and the IR metric is computed from those pseudo-labels. The paper states it is "ranker-agnostic" because it "operates on individual query–document pairs... independently of a ranker," explicitly "avoiding dependency on ranker-specific score distributions that plague traditional QPP methods" (<https://arxiv.org/html/2404.01012>).

Pearson ρ vs BM25 on TREC-DL 19/20/21/22 — RR@10: **0.538 / 0.560 / 0.524 / 0.350** vs WIG 0.113–0.286, NQC 0.152–0.227, SMV 0.126–0.240, BERT-QPP 0.206–0.281. nDCG@10 at judging depth 200: **0.724 / 0.638 / 0.546 / 0.388** vs WIG 0.520–0.622, M-QPPF 0.404–0.435. Rankers covered include BM25 (lexical) plus ANCE and TAS-B (dense). A fine-tuned 3B open model outperforms few-shot 70B. Latency 452.6 ms/query at judgment depth 10.

The ceiling is real and should be stated: Cohen's κ between the fine-tuned judge and TREC assessors ranged **0.038–0.333**, with a fine-tuned Llama-3-8B-Instruct reaching 0.418 on TREC-DL 21 versus GPT-3.5's 0.260 (<https://arxiv.org/html/2404.01012v2>). Pseudo-labels are good enough to calibrate against; they are not ground truth.

The RAG-side equivalent is the **sufficient-context autorater**: binary "does this context contain enough to answer", 93% accuracy (Gemini 1.5 Pro, 1-shot) vs FLAMe 87.8% and TRUE-NLI 82.6%, over FreshQA (452 instances, 77.4% sufficient), Musique-Ans (500, 44.6%) and HotpotQA (500, 55.4%); selective-generation gains >10% for Gemma 27B in the high-accuracy region and 2–10% improvement in fraction-correct-among-answered across Gemini, GPT and Gemma (<https://arxiv.org/html/2411.06037>, ICLR 2025). Its most useful finding for Oreag is negative-space: with insufficient context, models still answer 35–62% of instances correctly from parametric knowledge, so "the model answered" is not evidence the retrieval worked.

**Reportable meta-finding:** that paper does **not** evaluate similarity-score thresholds or any retrieval-score-based signal as a standalone approach at all. The state of the art on "should this RAG system answer?" does not reach for a cosine floor. Oreag's current design is off the beaten path.

Comparability: **complete.** The statistic is a count of LLM judgments over retrieved text; there is no embedding score for a model's distribution to distort. It transfers across all 22 entries, all Matryoshka dims, and the 3072-dim no-index projects with zero constants changed. The dependency it introduces instead is on the *judge* model's consistency — which Oreag controls centrally rather than the user controlling via BYOK. Cost and latency are the objection, not portability.

### 3.9 Comparability scorecard

| Signal | Shift-invariant | Scale-invariant | Cross-model evidence | Predictive power evidence | Verdict for the gate |
|---|---|---|---|---|---|
| Raw cosine floor (today) | No | No | Contradicted (§1.2, §1.3) | AUC 0.72 (UNVERIFIED preprint) | Broken |
| NQC | No | Yes | Negative (§3.1, §3.3) | r ≈ 0 to −0.123 on dense/MS MARCO | Do not ship |
| WIG | Yes | No | Negative | ρ 0.520–0.622 nDCG (BM25 only) | Do not ship |
| Raw top-1 margin | Yes | No | None | AUC 0.57 (UNVERIFIED) | Do not ship |
| Ratio margin | Partial (compresses) | Yes | Bitext only (BUCC) | +12–18 F1 over absolute threshold | Ship-able, cheapest upgrade |
| CSLS | Yes (exact) | No | **5 catalog models, no retuning** | +42–78% relative reciprocity; R@1 +0.02–0.04 | Strongest geometric option |
| Knee + GPD (TAA-k) | Yes | Yes | **4 encoders, 5 dims** | Within 2.0–2.9 F1 of oracle | Best for trimming; blind when all-bad |
| Surprise (EVT p-value) | Yes | Yes | — | +0.007 F1 over BiCut | Take the unit, not the accuracy |
| Dense/lexical rank agreement | Yes | Yes | **None published** | None published | Hypothesis; wrong for cross-lingual |
| Weaviate autocut | Yes (length-sensitive) | Yes | — | **None published** | Heuristic only |
| LLM judgment (QPP-GenRE / sufficient context) | n/a (no score) | n/a | Ranker-agnostic by construction | ρ 0.538–0.724; autorater 93% acc | Best signal; use as label, gate on cost |

**The decision this section forces:** no free, purely geometric statistic clears the ~0.80 AUC bar on published evidence for this specific binary decision. The invariance argument alone is not enough (§3.2 proves it). So the design cannot be "swap the constant for a clever ratio and ship." It must be either a per-project calibration that converts scores into a portable unit (§4), or a content-based judgment (§3.8), or both in a cascade (§5).

---

## 4. Option C — automatic per-project calibration from the corpus's own score distribution

The insight that makes this BYOK-compatible: the labels can be manufactured from the user's own documents at ingest, with zero user interaction and zero relevance judgments.

### 4.1 Tier 0 — free, no table, no extra API calls

`looks_weak(rows)` already receives the result rows of the search that just ran. Widen the **dense candidate pool to ~100** before RRF (one extra `ORDER BY` on the HNSW partial index for indexed dims; free on the 3072-dim exact-scan projects that already touched every row), then:

```
best      = max(similarity)                       # dense leg only, pre-RRF
tail      = similarities of ranks ~10..100
mu, sigma = mean(tail), stddev_samp(tail)
z         = (best - mu) / max(sigma, 1e-6)
weak      = z < TAU                               # TAU in sigmas
```

This is WIG's Score(q,D) term estimated from the query's own tail rather than from a collection language model, and it is Ethayarajh's anisotropy adjustment — subtract the model's own random-pair baseline so the reported similarity reflects residual semantic signal rather than the shared cone offset (<https://kawine.github.io/assets/emnlp_2019_contextual_slides.pdf>). TAU is scale-free in a way a cosine is not: on ada-002 (null ~0.70, tight spread) and MiniLM (null ~0.02, wide spread), the same TAU means the same thing because it is measured in units of that model's own noise.

Two guards: needs ≥30 tail rows (fall back otherwise), and it must read the raw cosine leg, never the RRF output (§1.6). Caveat carried forward honestly: §3.1 shows the *classical* dispersion predictors fail on dense retrieval, and a z-statistic is in that family. Its virtue here is that it is free and portable, not that it is proven discriminative — which is exactly why §6's experiment is non-optional.

### 4.2 Tier 1 — ingest-time null calibration (one extra embedding call per project)

Run once per `content_version`, alongside the existing `corpus_profile()` cache:

1. Sample n=256 chunk embeddings: `SELECT embedding FROM chunks WHERE project_id=$1 ORDER BY random() LIMIT 256`. Zero API cost — those vectors exist.
2. Embed K=16 fixed **off-domain natural-language** probes through the **production query path** (same `input_type` / prefix / LoRA adapter — see §4.5). ~320 tokens, ≈ $0.0000064 at $0.02/1M.
3. Score 16 × 256 = 4,096 pairs. OpenAI vectors are unit-norm so dot == cosine (<https://developers.openai.com/api/docs/guides/embeddings>, vendor); L2-normalise defensively for everyone else (§1.6 trap 2).
4. Store `null_mean`, `null_sd`, `null_p99`, and **`null_bestmax`** = mean over probes of max-over-256.

That last field is the one home-grown implementations get wrong. The gate reads a **maximum** over the retrieved set, and the maximum of N null draws grows with N. BLAST solved this in the 1990s: the E-value is "the expected number of optimal local alignments that will score at least as high as the observed alignment score, assuming that the query and the database sequences are randomly generated," with K and λ estimated from large sets of random alignments, and "the E-value depends on the database size, as larger databases have more chances of producing the alignment by chance" (<https://academic.oup.com/bioinformatics/article/40/12/btae729/7916501>). So a 5,000-chunk project and a 500,000-chunk project need different floors on the same model with the same content. Calibrate `null_bestmax` on a sample the size of the actual candidate pool. Sobering caveat from that same 2024 re-examination: even blastp's mature E-values "can at times be significantly conservative while at others too liberal" — a calibrated null is better than a constant, not perfect.

Cost per project: <1 second, one embedding call, ~$0.00001. Storage: ~15 floats.

### 4.3 Tier 2 — add a positive anchor and get a real conformal floor (~cents per project)

This is CONFLARE's published procedure plus Promptagator's round-trip filter.

1. Sample m=100 chunks (m=32 on a free tier). Ask the project's already-configured BYOK chat model for **one question answerable only from that chunk**. CONFLARE specifies exactly this for the no-labels case: sample reference documents and task an LLM with "creat[ing] one question and answer from each document", using the cosine between the question vector and the answering chunk as the nonconformity score, cutting at "the value of the list item that corresponds to the percentile determined by the user-specified error rate" (<https://arxiv.org/html/2404.04287v1>). **Honest caveat: that paper reports no calibration set size, no alpha values, no retrieval set sizes and no accuracy metrics — it is a methodology paper with no experimental validation. Cite it as a published design, not as evidence the recipe works.**
2. **Round-trip filter.** Keep a synthetic question only if it retrieves its own source chunk in the top-K. Promptagator generates 8 queries per document at temperature 0.7 from a 1M-document sample and filters exactly this way (<https://arxiv.org/pdf/2209.11755>). Without it, a lazy generation ("What is this document about?") contributes a spuriously low positive and drags the floor permissive. The filter is a **rank** test, so it is entirely independent of the model's cosine scale. Generate ~1.3x the target n to survive attrition.
3. Take s_i = cos(question_i, its source chunk) — a label-free positive distribution where the chunk *is* the label.
4. **Floor = the conformal quantile.** Sort ascending, take the ⌈(n+1)(1−α)⌉/n-th value; coverage is provably between 1−α and 1−α+1/(n+1) under exchangeability (<https://ar5iv.labs.arxiv.org/html/2107.07511>). α=0.1 means "90% of genuinely answerable queries clear this floor."

Sample-size table from that same source: n=1000 "is sufficient for most purposes" (coverage typically 0.88–0.92 at α=0.1); ~102 points buys ±0.05 coverage slack, 2,491 points buys ±0.01 (δ=0.1). So **n=100 is defensible (±0.05); n=32 is a point estimate and must be labelled as such in the UI.**

Empirical support that a conformally calibrated cosine cutoff behaves in a real RAG pipeline: with nonconformity A(q,s) = 1 − cos(emb(q), emb(s)), calibration on 1,440 snippets (NeuCLIR) and 1,710 (RAGTIME), both variants hit target coverage across α 0.05–0.40; at α ≤ 0.20 the embedding-based filter removed **25–55% of snippets while maintaining full coverage**, with overall context shrinking 2–3x and downstream ARGUE F1 improving at α=0.05–0.10 (<https://arxiv.org/html/2511.17908>). That paper's own warning is the one Oreag must honour: the guarantee "holds only if the calibration data is representative of the questions the framework is expected to encounter" — synthetic questions are not user questions, so this is a good estimate, not a guarantee.

Cost: ~100 short generations (~150 output tokens each) + ~100 query embeddings ≈ 2k input / 15k output LLM tokens + ~2k embedding tokens, on the user's own key, once. Cents.

**Free by-product — a model-quality warning.** If `pos_q10 ≤ null_p99`, this model cannot separate this corpus from noise. That is a defensible, measured basis for the exact levers Oreag has: warn at model-pick time, sort the picker, and label the entry. It is also the direct analogue of the RAGFlow diagnostic (§1.3) run against Oreag's own corpora.

### 4.4 Optional refinement — parametric null instead of empirical quantiles

If the product wants a p-value ("accept only hits whose cosine has null probability < 1e-4") rather than a sigma count, cosine similarities of unrelated sentence pairs "are often well captured by a gamma distribution shifted and truncated to [−1,1]", with a single gamma often sufficing and 2–4 components for complex cases; example fit on arXiv abstracts: α=13.3, c=−0.28, λ=35.5, validated on all-MiniLM-L6-v2 (384d), all-mpnet-base-v2 (768d) and all-roberta-large-v1 (1024d) over arXiv, Wikipedia and AG News (<https://arxiv.org/html/2510.05309>). Motivation stated there: a permutation test "requires a sufficiently large dataset to accurately model the tail." Store three floats, or precompute the p=1e-4 cutoff into one float so query time stays a comparison.

### 4.5 Two rules that make the calibration valid

- **Calibrate query-side to chunk-side, never chunk-to-chunk.** The cheapest imaginable calibration (sample stored chunk embeddings, compute pairwise cosines, call that the null) is invalid on the many asymmetric models in the catalog: jina-v3's `retrieval.query`/`retrieval.passage` LoRA adapters (<https://arxiv.org/abs/2409.10173>), nomic's `search_query:`/`search_document:` prefixes, E5's `query:`/`passage:`, Cohere's and Voyage's `input_type`. Chunk-to-chunk similarity is drawn from a different distribution. Embed the probes through the **production query code path** and score against the **stored** chunk vectors. The rule is harmless on symmetric models, so apply it universally.
- **Key the calibration row on dimension.** Truncation changes which subspace the comparison happens in. OpenAI supports the `dimensions` parameter but requires renormalisation on manual truncation; Gemini requires manual normalisation for all non-3072 outputs (§1.6). Changing dimension must invalidate the calibration exactly as changing model does.

### 4.6 Storage, refresh, cold start

```
project_score_calibration(
  project_id, provider, model, dimension, content_version,
  corpus_size,
  null_mean, null_sd, null_p99, null_bestmax,
  pos_n, pos_q05, pos_q10, pos_median,
  floor, tau, alpha, method, sample_size,
  judge_model, calibrated_at
)
```
Primary key `(project_id, provider, model, dimension)`. `corpus_size` is required for the BLAST correction (§4.2). `judge_model` is recorded because calibration quality varies with the user's BYOK chat model, so a later chat-model swap is a legitimate refresh trigger.

**Refresh policy.** (1) Mandatory on any provider / model / dimension change — the old vector space no longer exists, and a model switch already forces a re-embed, so this is free to attach. (2) On `content_version` bump, riding the same invalidation the `corpus_profile()` cache already uses. (3) A monthly TTL. (4) On drift: practitioner guidance is to compare current embedding/score statistics against a stored reference via KL divergence or Population Stability Index, monitor the gap between the known-good mean and the noise floor, alert at three sigma below a rolling baseline, keep sample sizes in the hundreds per class, and require agreement across multiple signals before escalating (<https://zilliz.com/ai-faq/what-is-embedding-drift-and-how-do-i-detect-it> — vendor FAQ/practitioner posts, not peer-reviewed). At ~$0.00001 for the null-only path, simply redoing Tier 1 on every `content_version` change is cheaper than deciding whether to.

**Cold start.** No calibration row exists on the first query of a new project, and a 30-chunk project cannot produce a meaningful null. Ordered fallback:
1. Tier 0 (§4.1) — needs only ≥30 rows in the candidate pool, no stored state at all.
2. If fewer than 30 rows: fall back to the existing global env constant, and record that this happened.
3. Never block ingest on calibration. Run it as a background job on the ingest worker; the gate degrades to (1) or (2) meanwhile.
4. Surface state honestly in settings: "calibrated N days ago from M chunks" (or "not yet calibrated — using default").

**Self-improvement path.** Log the realised `best` per real query into the existing usage/tracing tables. After ~200 real queries, replace the synthetic positives with the empirical p05 of real query bests. The floor becomes fully self-tuning with no synthetic data — the classic unsupervised score-distribution approach (fit a mixture to a ranked list and derive the cutoff, no relevance judgments, <https://e.humanities.uva.nl/publications/2009/aram_wher09b.pdf>; the two-gamma mixture is described as "the most-likely universal model, with the normal-exponential being a usable approximation") applied to live traffic. Do the mixture fit offline over logged lists, not in the request path.

### 4.7 What Option C does NOT solve

Cross-model **threshold mapping** looked like the elegant BYOK answer — learn one conversion function and translate a threshold between models — and it is a dead end. Isotonic regression achieved R² ≥ 0.98 *within* the Titan family across dimensions, but only 0.820–0.945 across families, and the fitted function is itself corpus-dependent (<https://arxiv.org/html/2608.05857>). With 22 entries that is 22×21 mappings per corpus. Calibrating in place is strictly cheaper. The one thing the within-family result *does* buy: a calibration can be safely shared across the Matryoshka options of **one** model (3-small 512/1536; 3-large 256/1024/3072; gemini-embedding-001 768/1536/3072; jina-v3 256/512/1024) rather than fitted per dimension — though given §1.5's dimension-dependence of cosine scale, measuring per dimension is cheap enough to just do.

Also ruled out: **whitening / isotropy correction of the embeddings themselves** fixes the anisotropy offset at the root but rewrites every stored vector, breaks them against the vendor's own query-time embeddings, and needs re-fitting per project. Cross-Example Softmax calibration has the same disqualifier — it requires retraining the encoder, which a BYOK product cannot do (<https://arxiv.org/html/2011.08824>).

---

## 5. Option D — combinations

Four compositions, in increasing order of how much they change.

**D1 — auto-calibrated default, preset override.** Ship Tier 1/2 calibration as the default and let advanced users override with a coarse band, not a raw float. AnythingLLM's shape is the one to copy: a `<select>`, not a slider or number box, labelled "Document similarity threshold", helped by "The minimum similarity score required for a source to be considered related to the chat. The higher the number, the more similar the source must be to the chat", with four options — "No restriction" (0.0), "Low (similarity score ≥ .25)", "Medium (≥ .50)", "High (≥ .75)", default 0.25 (<https://github.com/Mintplex-Labs/anything-llm/blob/master/frontend/src/pages/WorkspaceSettings/VectorDatabase/DocumentSimilarityThreshold/index.jsx>). The option label embeds the number, so the value is auditable but not fiddleable. For Oreag the bands should be expressed in the **calibrated** unit (percentile against this project's own null, or α), not raw cosine — which is the one change that makes a band mean the same thing on `all-MiniLM-L6-v2` at 384 dims and `gemini-embedding-001` at 1536.

**D2 — cheap-signal cascade with an expensive tiebreak.** Gate on the free scale-free statistic (§4.1 z-score, or CSLS/ratio margin), and only when it is *ambiguous* — within a band around the trigger point — spend one batched LLM relevance judgment over the top 3–5 chunks. Zero "relevant" judgments means the retrieval failed and the query should be translated and re-embedded. This turns the gate from a geometry question into a content question at the exact moments geometry is unreliable, while keeping the per-query cost near zero for the common case. Justified by §3.8's numbers (ranker-agnostic, 2–3x the score-based predictors) and bounded by §3.8's honest ceiling (judge κ 0.038–0.418) and its latency (452.6 ms/query at depth 10).

**D3 — gate the gate on corpus language.** This is the cheapest large win and it needs no calibration at all. RAGFlow ships cross-lingual retrieval as an explicit user-selected target-language list, never a score trigger: "Select one or more target languages so a query can match related content in other languages in the dataset... the system's default chat model translates the query you entered... into the selected target languages", with the warning "make sure these languages exist in the dataset to ensure effective search" (<https://github.com/infiniflow/ragflow/blob/main/docs/guides/dataset/retrieval_testing.md>). RAGFlow's dataset config also carries a first-class user-declared **Language** field. Onyx does the same thing under a different name: "Multilingual expansion rephrases your queries into the specified other languages. This can be helpful for cross-language results" (<https://docs.onyx.app/admins/advanced_configs/search_configs>).

For Oreag: add `projects.corpus_languages text[]` and make the branch `IF best_is_weak AND array_length(corpus_languages,1) > 1 THEN translate`. That collapses the entire false-positive cost — translating and re-embedding on a monolingual corpus, burning the user's BYOK tokens for nothing — to zero, **without any per-model calibration**. One migration plus one conditional. Populate by user declaration first (as RAGFlow does); populate by detection later, using the scripts already computed by `corpus_profile()` per `content_version`.

**D4 — migrate the threshold to a reranker score (the structural fix).** Dify makes Score Threshold and TopK "only effective during the Rerank phase," with the rerank model disabled by default (<https://docs.dify.ai/en/use-dify/knowledge/create-knowledge/setting-indexing-methods>). Open WebUI independently does the same, binding `RAG_RELEVANCE_THRESHOLD` to reranking with default 0.0 across four embedding engines. The reason this works is exactly Oreag's problem inverted: a raw cosine is not comparable across embedding models, but a cross-encoder rerank score is, because one fixed model scores every candidate regardless of which embedder built the index. If Oreag ever adds a reranker to the BYOK key set, moving the gate from "best cosine" to "best rerank score" makes a single global constant genuinely defensible and the BYOK calibration problem largely evaporates. Note the caveat that even then, Cohere documents its own rerank scores as "query dependent" and refuses an absolute interpretation (<https://docs.cohere.com/docs/reranking-best-practices>) — so the constant becomes *portable across embedding models*, not *universally meaningful*.

---

## 6. Recommendation

**Ship D3 + Tier 0 + D1 now; Tier 1/2 calibration next; keep D2 as the ambiguity tiebreak; treat D4 as the endgame. Do not ship any new geometric constant until the experiment in §6.2 clears it.**

Concretely, in dependency order:

| Step | Change | Cost | Why |
|---|---|---|---|
| 0 | Rename/type the constant (`..._min_cosine_similarity`), assert 0–1 at startup, assert the compared value is the pre-RRF dense similarity, L2-normalise every embedding on ingest and query with a ‖v‖≈1±1e-3 assertion | Hours | §1.6, §2.2. Prevents a whole-product silent failure; the norm assertion catches the Gemini-1536 trap |
| 1 | `projects.corpus_languages`; only fire the translate path on a multi-language project | One migration | §5-D3. Removes most of the constant's blast radius with no calibration |
| 2 | Widen the dense candidate pool to ~100 pre-RRF; compute and **log** z, ratio margin, knee position, top-1 percentile into the existing Langfuse traces — do not gate on them yet | Days | §4.1, §3.9. Builds the dataset that decides everything else |
| 3 | Tier 1 null calibration per (project, provider, model, dimension, content_version); gate becomes `best < null_bestmax + TAU·null_sd`, falling back to the env constant when uncalibrated | ~$0.00001/project | §4.2. Converts an incomparable cosine into a portable sigma count |
| 4 | Tier 2 conformal floor with round-trip-filtered synthetic questions; expose α (coverage), never a cosine | ~cents/project | §4.3. Gives the number a meaning a user can actually reason about |
| 5 | D1 preset bands over the calibrated unit as an advanced override | Days | §2.3. Preserves the legitimate manual case without exposing a raw float |
| 6 | D2 LLM tiebreak in the ambiguity band | Metered | §3.8, §5 |

**Why not the alternatives.**

- Not Option A alone: the user cannot know the five things §2.1 requires, and no vendor publishes them. Qdrant and Elasticsearch — the two engines with the deepest vector expertise — decline to supply a cross-model default at all, which means Oreag shipping one constant is *industry standard*, and also that industry standard is unaided guesswork.
- Not Option B alone: §3.2 is the decisive negative — the most obvious scale-free replacement measured **worse** than the raw cosine it replaces (AUC 0.57 vs 0.72, UNVERIFIED preprint), and nothing in §3.9 clears the ~0.80 AUC bar for this binary decision on published evidence. Invariance without demonstrated discriminative power is not a design.
- Not CSLS as the first move, despite it being the best-evidenced geometric option (§3.5, five catalog models, no retuning): it needs a per-chunk neighbourhood column recomputed on every re-embed, and on 3072-dim exact-scan projects the ingest kNN pass is expensive. It is the right *phase-2* upgrade to step 3, and its evidence is for improving retrieval ranking, not for the abstain decision specifically.
- Not "one constant per model, hardcoded from published numbers": the thresholds are corpus-dependent as well (0.718 vs 0.821 for one model on two corpora), and Oreag has no access to a user's corpus at model-registration time.

**Where the recommendation is weakest, stated plainly.** Tier 0's z-statistic is in the same family as the NQC/WIG predictors that §3.1 shows failing on dense retrieval. Its defence is that it is free, portable, and strictly better than a raw constant — not that it is proven. Tier 2's conformal guarantee is conditional on exchangeability between synthetic calibration questions and real user questions, which is violated to an unknown degree (<https://arxiv.org/html/2511.17908>). And CONFLARE, the closest published match to the whole recipe, contains no experimental validation at all. This design is defensible, not proven. That is what §6.2 is for.

### 6.1 What would kill it

- Tier 1's calibrated z fails to clear ~0.80 AUROC on any catalog model → do not gate on it; degrade to warn/sort/label, keep D3, and go straight to D2/D4.
- The null distribution turns out to be unstable across `content_version` bumps within one project → the refresh cost stops being negligible and the whole calibration table is a liability.
- Synthetic positives systematically overestimate real query similarity (exchangeability violation large) → the floor is permissive and the gate under-fires; the fix is step 4's self-improvement path (real logged bests) rather than synthetic anchors.

### 6.2 The experiment that proves or kills it

**Design.** Hold corpus and query set fixed; vary the embedding model across the catalog. This orientation is mandatory, not stylistic: predictor quality within one ranker and across rankers correlate at **−0.053** (<https://arxiv.org/html/2601.17359v1>), so a single-model number will not warn you when a signal fails to transfer.

1. **Corpora.** At least three, chosen to span the corpus-effect axis §1.2 demonstrates: one English-only, one Indic-script, one mixed. Real Oreag project corpora if consent allows, otherwise seeded.
2. **Models.** Minimum six spanning the capability and anisotropy range: `gemini-embedding-001@1536`, `cohere embed-multilingual-v3.0@1024`, `openai text-embedding-3-large@1024`, `openai text-embedding-3-small@1536`, `together intfloat/multilingual-e5-large-instruct@1024` (with correct prefixes), `sentence_transformers all-MiniLM-L6-v2@384`. This set deliberately includes the two extremes of §1.4 (Belebele eng→tam 0.9228 vs 0.0651) and of §1.1's null baseline.
3. **Queries.** English queries over each corpus, plus Indic-script queries, plus deliberately unanswerable queries as negatives.
4. **Label.** The sufficient-context autorater — binary "does this retrieved context contain enough to answer" — at 93% accuracy (<https://arxiv.org/html/2411.06037>). Use it to label **retrieval** quality, not end-to-end answer quality: that paper shows downstream behaviour varies a lot by generator size, and that models answer 35–62% of insufficient-context instances correctly from parametric knowledge, so "the model answered" is not a valid label. Verify a 10% sample by hand, as <https://arxiv.org/html/2511.17908> did with its LLM-generated relevance labels.
5. **Candidates scored per query, all logged, none gating:** raw cosine (today's baseline), calibrated z (Tier 1), conformal percentile (Tier 2), ratio margin, CSLS, knee position, top-1 percentile, dense/lexical overlap@10, and LLM judgment count.
6. **Metric: AUROC and the risk–coverage curve, per model**, never correlation with a continuous quality metric (§3.4). AUROC because it is independent of base accuracy, and base accuracy differs by 60+ nDCG points across these models (§1.4).

**Pass condition.** A candidate ships as a *gate* only if it clears **≈0.80 AUROC on every tested model** — the bar stated in §3.2 for a single global cutoff to be actionable — with a single shared constant (TAU or α). A candidate that clears 0.80 on some models and not others ships as a **warning/sort/label** signal, not a gate; that is a legitimate outcome, since warn/sort/label are levers Oreag has and gating is the one that costs the user money when wrong.

**Kill condition.** If **no** candidate clears 0.80 on the weakest model, the honest conclusion is that no geometric signal can gate this decision on that model, and the design collapses to: D3 (language gate) + D2 (LLM judgment) + model-pick warnings driven by the `pos_q10 ≤ null_p99` separation test (§4.3). That is a worse product only in latency and cost, not in correctness.

**Baseline to beat.** Today's global constant, measured the same way. Publish that number internally whatever happens — it is the first honest measurement of the current behaviour that will exist.

---

## 7. UX patterns worth copying, and what nobody does

### 7.1 Copy these

| Pattern | Product | What to take |
|---|---|---|
| Threshold as 3–4 named presets with the number embedded in the label, never a raw float | AnythingLLM — "Low (similarity score ≥ .25)" / "Medium (≥ .50)" / "High (≥ .75)", default 0.25 (<https://github.com/Mintplex-Labs/anything-llm/blob/master/frontend/src/pages/WorkspaceSettings/VectorDatabase/DocumentSimilarityThreshold/index.jsx>) | The interaction. Not the calibration — AnythingLLM applies the same bands to all-MiniLM-L6-v2 (384d) and text-embedding-3-large alike |
| Escalate instead of returning empty | Flowise Similarity Score Threshold Retriever — "Max K" and "K Increment": "It'll fetch N results, then N + kIncrement, then N + kIncrement * 2" (<https://github.com/FlowiseAI/Flowise/blob/main/packages/components/nodes/retrievers/SimilarityThresholdRetriever/SimilarityThresholdRetriever.ts>) | Widen k first, escalate to translation second. A better mental model than one binary floor. (Note their shipped inconsistency: UI default 80 vs code-path default 0.9) |
| Fail open by default | Open WebUI — `RAG_RELEVANCE_THRESHOLD` default **0.0** (<https://github.com/open-webui/docs/blob/main/docs/reference/env-configuration.mdx>) | The asymmetric-cost argument of §2.2, shipped |
| Threshold lives on a rerank score, not a cosine | Dify — "The TopK and Score configurations are only effective during the Rerank phase" (<https://docs.dify.ai/en/use-dify/knowledge/create-knowledge/setting-indexing-methods>) | The only surveyed design that becomes genuinely model-independent |
| Derive a tunable from a known property instead of asking | Dify — TopK "automatically adjusts the number of chunks based on the chosen model's context window" | Oreag knows each model's dimension and each project's chunk count; top-k and the exact-scan budget can auto-derive |
| Show the score arithmetic | RAGFlow — "overall hybrid similarity score is 28.56, calculated as 25.17 term similarity score multiplied by 0.7 plus 36.49 vector similarity score multiplied by 0.3" (<https://github.com/infiniflow/ragflow/blob/main/docs/guides/dataset/retrieval_testing.md>) | Surface the raw cosine and the FTS rank **separately**; never surface the RRF sum, which has no interpretable magnitude |
| Non-persistent tuning sandbox | RAGFlow Retrieval Testing — "Parameter changes... are only used for the current test and are not automatically synchronized to Chat Assistant or Agent" | A read-only endpoint accepting override params. Hours of work against the existing hybrid search |
| Publish the score band, and filter pre-fusion | Azure AI Search — vector `@search.score` cosine "0.333 – 1.00"; hybrid RRF "bounded by the number of queries being fused, with each query contributing a maximum of approximately 1/k"; "Filtering occurs before fusing results from different recall sets" (<https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/search/hybrid-search-ranking.md>) | Pinning the score into a known band is what makes any constant survivable. Oreag's per-model equivalent is a stored percentile |
| Language scope as first-class picker metadata | Google Vertex AI RAG Engine — model table tags each row "English-only" or "multilingual" with its dimension (<https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/rag-engine/use-embedding-models>); Weaviate — "ideal for datasets that include multiple languages" vs "Best for datasets primarily in English", with the multilingual model as **default** (<https://docs.weaviate.io/cloud/embeddings/models>) | A `language_scope` enum plus multilingual-by-default. Vendor-declared, needs no benchmark claim, cannot be wrong |
| Cross-lingual as an explicit language list, never a score trigger | RAGFlow (§5-D3), Onyx multilingual expansion | The only shipping designs for this feature, and both refuse to gate on a score |
| Model swap that keeps the old index serving | Onyx — "the old embedding model will still be available for searches" during re-index (<https://docs.onyx.app/admins/advanced_configs/search_configs>) | Onyx needs a whole second Vespa index per (model, precision); Oreag needs one nullable column or a `model_version` discriminator, because `chunks.embedding` has no fixed dimension |
| Four-part destructive-change modal | AnythingLLM — name the blast radius, what is destroyed, what survives ("Your uploaded documents will not be deleted"), and the recovery ("available for re-embedding") (<https://github.com/Mintplex-Labs/anything-llm/blob/master/frontend/src/pages/GeneralSettings/EmbeddingPreference/index.jsx>) | Oreag's swap is strictly gentler, and Oreag meters tokens — so it can add a **priced** estimate no surveyed product can |
| Fixed-schema model card | Pinecone — METRIC / DIMENSION / MAX INPUT TOKENS / TASK / PRICE per model (<https://docs.pinecone.io/models/multilingual-e5-large>) | 22 heterogeneous models become comparable the moment every one renders the same five fields. Max-input-tokens should be a chunk-time validation, not just a label |
| Three-axis taxonomy and lifecycle state | Voyage — "quality" / "latency and cost" / "domain", with a separate "Previous generation" block (<https://docs.voyageai.com/docs/embeddings>) | A `lifecycle` enum ('current' / 'superseded' / 'deprecated' / 'retired') keyed on **(provider, model)**, not model alone — the same model is alive on one provider surface and dead on another |
| Measurement-gated model swap | RAGFlow — re-encode 5–10 sampled chunks, mean cosine ≥0.9 allows the swap (<https://ragflow.io/blog/ragflow-seamless-upgrade-from-0.21-to-0.22-and-beyond>) | Copy the **diagnostic**, not the gate. Oreag always re-embeds, so the check is unnecessary — but the same sample-and-re-encode routine is exactly how §4.2's per-model distribution gets measured |
| Rank by Borda, filter by language, disclose contamination | MTEB leaderboard — Borda count default, language filter, and a zero-shot column giving "the percentage of evaluation datasets that did not have their training split used to train the model" (<https://huggingface.co/blog/Samoed/mteb-v3-leaderboard>) | Copy the **language filter**. Do NOT embed a single MTEB number next to each model: Weaviate independently warns MTEB "results are self-reported" and models may have trained on MTEB datasets (<https://weaviate.io/blog/how-to-choose-an-embedding-model>), and `gemini-embedding-001`'s own MTEB metadata declares MIRACL as a training set |

### 7.2 What nobody does — Oreag's differentiation surface

Each of these was searched for across 14+ multi-model RAG products and found absent, not merely thin:

1. **Nobody auto-detects corpus language and warns that the chosen model is a poor fit.** The closest is RAGFlow's user-*declared* dataset Language dropdown. AnythingLLM's own troubleshooting names "non-English documents with the default English embedder" as a top cause of empty results — and ships no warning. Oreag already computes `corpus_profile()` scripts per `content_version`.
2. **Nobody publishes or ships per-(model, dimension) threshold defaults.** Qdrant phrases it as the user's problem: use `score_threshold` "if you know the minimal acceptance score for your model" (<https://qdrant.tech/documentation/concepts/search/>). Elasticsearch documents its `similarity` param purely mechanically.
3. **Nobody shows the empirical similarity distribution for *your* corpus to help pick a threshold.** The histogram-with-slider interaction exists in a 2011 document-similarity patent (US 9075498 / US 10255334), not in any RAG product surveyed — prior art for the interaction, not a competitor.
4. **Nobody warns at pick time that a chosen dimension loses the index.** Oreag's exact case: 3072 dims → no HNSW → exact scan of every chunk. The warning writes itself: "3072 dimensions cannot be indexed (pgvector HNSW supports up to 2000); every query will scan all chunks in this project." And the vendor's own numbers support the fix — OpenAI states "a text-embedding-3-large embedding can be shortened to a size of 256 while still outperforming an unshortened text-embedding-ada-002 embedding with a size of 1536" (<https://developers.openai.com/api/docs/guides/embeddings>, **vendor-self-reported**), while an independent measurement finds text-embedding-3-large retains 93.3% of MTEB-R and only **90.3% of CLEF** at 256 dims (<https://arxiv.org/html/2412.04506v2>) — so cross-lingual degrades ~1.45x faster than English, and the recommendation is **1024, never 256**.
5. **Nobody triggers cross-lingual retrieval automatically.** Oreag's auto-trigger design is genuinely novel *and* genuinely unvalidated by any shipping product. That cuts both ways and is the strongest argument for D3 (§5): keep the automatic behaviour, but scope it to projects that actually contain another language.
6. **Nobody surfaces capability metadata in the picker.** Onyx's model registry is literally `{name, dim, index_name}` — no language list, no quality score, no deprecation flag — despite a serious admin model picker spanning Cohere, OpenAI, Google and Voyage. Vendors label; platforms do not. A platform that labels is ahead of a well-funded BYOK competitor.
7. **Nobody prices a re-embed.** Oreag meters every token (Phase 7), so its swap modal can say "re-embedding 12,431 chunks ≈ 3.1M tokens on text-embedding-3-small" — turning a scary warning into a priced decision. No surveyed product can.

### 7.3 The floor Oreag is competing against

The frameworks abdicate and say so. LlamaIndex points at MTEB and states the constraint ("If you change your embedding model, you must re-index your data") with a `SimilarityPostprocessor(similarity_cutoff=...)` documented only by example, no default and no per-model guidance. Haystack's "Choosing the Right Embedder" splits three ways and defers to MTEB (<https://docs.haystack.deepset.ai/docs/choosing-the-right-embedder>). LangChain offers a provider-agnostic interface with no capability metadata and a threshold retriever with documented score-scale defects (§2.2). Three of the most-used RAG frameworks provide no ranking, no labelling, no language guidance and no threshold calibration.

So the bar is low, and a modest amount of honest per-model metadata plus one automatic calibration is disproportionately differentiating. The corresponding obligation is not to overclaim: label every vendor number as vendor-reported, mark every unmeasured cost as unpublished rather than inventing one, and say "calibrated N days ago from M chunks" rather than implying a guarantee the exchangeability assumption does not support.
