# 10 — BYOK Model Recommendation Matrix

Scope: the 22 embedding entries in Oreag's catalog, plus models Oreag does not carry and could add. Oreag cannot force a model on a BYOK user. It can **default**, **sort**, **label**, **warn**, and **block for new projects**. Every recommendation below is written against those five levers.

---

## 1. How to read this

### 1.1 CROSS-lingual is not MULTI-lingual

Two different capabilities, measured by different benchmarks, and models rank differently on each.

| | Query language | Corpus language | Benchmarks | What it proves |
|---|---|---|---|---|
| **MULTI-lingual** | Hindi | Hindi | MIRACL, MTEB(Indic), Hindi-BEIR | The model can retrieve *within* a language |
| **CROSS-lingual** | English | Hindi (or reverse) | BelebeleRetrieval cross subsets, XTREME-UP, XOR-Retrieve, MLQARetrieval, IndicCrosslingualSTS | The two languages occupy the *same* vector region |

MIRACL is monolingual per-language retrieval and is routinely miscited as cross-lingual evidence. It is not ([MMTEB task composition, arXiv 2502.13595](https://arxiv.org/html/2502.13595v1); [EmbeddingGemma §4.1, arXiv 2509.20354](https://arxiv.org/html/2509.20354v1)).

The gap between the two axes is not academic. **Qwen3-Embedding-0.6B tops the sub-1B multilingual aggregate at MTEB(Multilingual v2) Mean(Task) 64.34 and scores 6.6 MRR@10 on XTREME-UP — dead last of eleven models in the same table** ([arXiv 2509.20354](https://arxiv.org/html/2509.20354v1), which explicitly flags this: "even models with strong performance in the MTEB multilingual benchmark may struggle in XTREME-UP, such as Qwen3 Embedding 0.6B and Jina Embeddings v3"). `multilingual-e5-large-instruct` shows the same split in the other direction: rank 1 of 12 on MTEB(Indic) at 70.2 ([arXiv 2502.13595](https://arxiv.org/html/2502.13595v1)) but only 18.7 on XTREME-UP ([arXiv 2509.20354](https://arxiv.org/html/2509.20354v1)).

**Consequence for the picker: never sort by an aggregate multilingual score.** Sorting by MTEB(Multilingual) would put Qwen3 near the top of a list ordered for the exact capability it is worst at. Sort by a cross-lingual benchmark, or do not sort on multilinguality at all.

### 1.2 Direction matters, and the two research passes disagree on the labels

MTEB multi-subset retrieval subsets are named `A-B`. The benchmarks-crosswalk pass verified empirically, from MTEB's own `descriptive_stats`, that **A = corpus/document language and B = query language**: in `BelebeleRetrieval`, subset `eng_Latn-hin_Deva` has documents totalling 232,049 chars (byte-identical to the English corpus of `eng_Latn-eng_Latn`) and queries totalling 65,356 chars (identical to the Hindi queries of `hin_Deva-hin_Deva`) ([descriptive_stats JSON](https://cdn.jsdelivr.net/gh/embeddings-benchmark/mteb@main/mteb/descriptive_stats/Retrieval/BelebeleRetrieval.json)).

**A separate research pass read the same subset names in the opposite direction.** The numbers agree byte-for-byte; only the prose interpretation conflicts. This document uses the empirically verified convention (`corpusC/queryQ`) and labels every direction explicitly. **If you re-derive any of these numbers, verify the convention first — getting it backwards inverts the entire recommendation.** Under the verified convention, for every model measured, English-query-over-foreign-corpus beats foreign-query-over-English-corpus: gemini 94.4 vs 87.5, voyage-3-large 85.3 vs 72.8, text-embedding-3-large 78.2 vs 63.3 (Belebele nDCG@10 ×100, means over 121 subsets each). **The short foreign-language query is the bottleneck, not the foreign-language chunk.**

### 1.3 Why vendor numbers are suspect

Six concrete failures found in this catalog's own vendors:

1. **Direct refutation.** Jina's abstract claims v3 achieves "superior performance compared to multilingual-e5-large-instruct across all multilingual tasks" ([arXiv 2409.10173](https://arxiv.org/html/2409.10173v3)). Third-party measurement: MTEB(Multilingual v2) 58.37 vs 63.22, and XTREME-UP 8.5 vs 18.7 ([arXiv 2509.20354](https://arxiv.org/html/2509.20354v1)). Jina's *own* Table 3/4 also shows v3 losing multilingual retrieval (57.98 vs 58.38) and clustering to the model its abstract says it beats on everything.
2. **Undisclosed training contamination.** `gemini-embedding-001`'s MTEB `model_meta.json` declares `training_datasets` including `MIRACLRetrievalHardNegatives`. **MIRACL is a declared training set for this model**, so its MIRACL win is an in-domain score and is not evidence of generalisation. Belebele and MLQA are *not* in that list, which is why the cross-lingual claim survives.
3. **Broken independence chains.** Snowflake's Arctic-Embed 2.0 Table 1 appears to independently reproduce OpenAI's MIRACL 0.549 and MTEB-R 0.554 — but the table footnote reads "Asterisks denote results from Lee et al. (2024)," and those cells are asterisked. They are copied from Google's Gecko line of work, not measured by Snowflake ([arXiv 2412.04506](https://arxiv.org/html/2412.04506v2)).
4. **Unfalsifiable relative claims.** Voyage publishes only percentage deltas against models it selects ("outperforms OpenAI-v3-large by 8.26%") with no absolute score anywhere ([blog.voyageai.com 2025/05/20](https://blog.voyageai.com/2025/05/20/voyage-3-5/)). These cannot be converted into a cross-model comparison even in principle.
5. **Coverage claims that were never measured.** Snowflake's arctic-embed2 lists Hindi among 74 languages; Snowflake's own engineering blog states every reported score is "average across German (DE), English (EN), Spanish (ES), French (FR) and Italian (IT)." A tag list is not a measurement. (UNVERIFIED — this entry did not pass a verification pass.)
6. **Leaderboard contamination generally.** MTEB ships a zero-shot column — "the percentage of evaluation datasets that did not have their training split used to train the model" — precisely because leaderboard scores are contaminated ([MTEB v3 leaderboard](https://huggingface.co/blog/Samoed/mteb-v3-leaderboard)). Weaviate independently warns MTEB "results are self-reported" ([weaviate.io](https://weaviate.io/blog/how-to-choose-an-embedding-model)).

**Labelling rules used below:** every number is tagged `[vendor]` (published by the model's own maker), `[competitor]` (published by a rival, which biases *against* the model — usually higher credibility), `[independent]` (MTEB community runs, MMTEB, peer-reviewed third parties), or `UNVERIFIED` (asserted in research but not re-checked at the primary source this cycle).

### 1.4 Interaction with the global `cross_lingual_similarity_floor`

One env constant compared against a raw pgvector cosine, shared by 22 models. It cannot be right, for four independent reasons, all measured:

- **Across models, same task.** Belebele English-query-over-Tamil-corpus: gemini 0.9597 vs text-embedding-3-large 0.4285 vs all-MiniLM 0.079 [independent, MTEB].
- **Across languages, same model.** text-embedding-3-large IndicCrosslingualSTS: en-hi 0.393, en-ta 0.0056 [independent, MTEB].
- **Across corpora, same model.** The threshold needed to hit 0.95 precision for ada-002 is 0.718 on SciFact and 0.821 on an enterprise corpus ([arXiv 2608.05857](https://arxiv.org/html/2608.05857)).
- **Anisotropy floor.** Mean random-pair cosine ("RandCos") ranges 0.016 (all-mpnet) → 0.018 (all-MiniLM-L6) → 0.308 (BGE-large) → 0.696 (E5-large) → 0.707 (multilingual-E5-large) → 0.996 (GPT-2) ([arXiv 2606.29571](https://arxiv.org/html/2606.29571)). A floor of 0.40 is *below the noise floor* of the E5 family and *far above* it for MiniLM.

Cross-family cosine similarity between different models' vectors on the same text sits at **0.3–0.6** (RAGFlow's own model-swap gate measurement, MiniLM → BGE-M3; [ragflow.io blog](https://ragflow.io/blog/ragflow-seamless-upgrade-from-0.21-to-0.22-and-beyond)) `[vendor]`. That is the empirical statement of why one constant cannot cross 22 models.

This document does not solve the floor — see the scale-free-signals and auto-calibration notes — but every warning below assumes the floor is currently unreliable for the model in question, and says so where the failure is silent.

---

## 2. THE MASTER TABLE

All 22 catalog entries. **Rec. dim** applies the rule *"largest offered dimension ≤ 1536"* (Oreag's HNSW partial indexes exist only for {256, 384, 512, 768, 1024, 1536}). **Idx** = does the recommended dim get an index. Cross-lingual column: the single best number found, with its direction stated. Belebele figures are nDCG@10 ×100 [independent, MTEB community runs]; `*C/engQ` = mean over 121 subsets of English query over a non-English corpus.

| # | Provider | Model | Def. dim | Rec. dim | Idx | Tier | Best cross-lingual number found | Vendor? | Hindi / Indic coverage |
|---|---|---|---|---|---|---|---|---|---|
| 1 | gemini | **gemini-embedding-001** | 3072 | **1536** | ✅ | strong-multilingual | Belebele `*C/engQ` **94.4**; cross mean 0.9069 over 254 subsets | independent | **Best in catalog.** IndicCrosslingualSTS en-hi 0.754, en-ta 0.705, 12-lang mean 0.629. Fails: en-ur 0.242, en-or 0.087 |
| 2 | cohere | **embed-multilingual-v3.0** | 1024 | 1024 | ✅ | strong-multilingual | Belebele `*C/engQ` **87.9**; cross mean 0.8081 | independent | IndicSTS en-hi 0.645, en-ta 0.478, 12-lang mean 0.467 (3.7× OpenAI-3-large). Fails: en-ur 0.192, en-or 0.158 |
| 3 | together | **intfloat/multilingual-e5-large-instruct** | 1024 | 1024 | ✅ | strong-multilingual | Belebele `*C/engQ` **87.5**; XTREME-UP 18.7 (mid) | independent | **MTEB(Indic) rank 1/12 at 70.2.** Recall@1 hi 31.9%, ta 27.3%. XTREME-UP hi 30.6, ta 22.9, **ml 8.6** |
| 4 | voyage | **voyage-3-large** | 1024 | 1024 | ✅ | strong-multilingual | XTREME-UP MRR@10 **39.2** (Indic query → English passage) | competitor (Google) | XTREME-UP hi 54.3, ta 36.0, mr 45.5, pa 48.4, ml 45.3, or 32.3, **brx 7.9** |
| 5 | jina | **jina-embeddings-v3** | 1024 | 1024 | ✅ | usable-multilingual | Belebele `*C/engQ` 78.9 — but **XTREME-UP 8.5** | independent | Hindi/Bengali/Urdu on Jina's best-30 list; **Tamil is not.** XTREME-UP hi 13.8, ta 10.7, brx 0.1 |
| 6 | cohere | **embed-v4.0** | 1536 | 1536 | ✅ | usable-multilingual | **NONE PUBLISHED** (no Belebele/MLQA/IndicSTS/Mintaka/XQuAD run exists) | n/a | MIRACL monolingual only: hi 0.591, bn 0.722, te 0.731 — **below its own predecessor** |
| 7 | openai | **text-embedding-3-large** | 3072 | **1024** | ✅ | english-mostly | Belebele `*C/engQ` 78.2; **XTREME-UP 18.8** | independent | **IndicSTS 12-lang mean 0.126.** en-ta **0.0056**, en-or −0.028. XTREME-UP ta **6.0** |
| 8 | azure | **text-embedding-3-large** | 3072 | **1024** | ✅ | english-mostly | Same weights as #7 | independent | Same as #7 |
| 9 | openai | **text-embedding-3-small** | 1536 | 1536 | ✅ | english-mostly | Belebele `*C/engQ` 62.9; cross mean 0.5370 (< its own monolingual 0.5896) | independent | **IndicSTS 12-lang mean 0.041, with NEGATIVE values** (en-as −0.095, en-or −0.123, en-ta −0.037) |
| 10 | azure | **text-embedding-3-small** | 1536 | 1536 | ✅ | english-mostly | Same weights as #9 | independent | Same as #9 |
| 11 | azure | **text-embedding-ada-002** | 1536 | 1536 (fixed) | ✅ | english-mostly | **NONE PUBLISHED, vendor or independent** | n/a | **NONE.** No Hindi/Indic number exists anywhere. MIRACL 31.4 `[vendor]` is monolingual |
| 12 | mistral | **mistral-embed** | 1024 | 1024 | ✅ | unknown | **NO NATIVE NUMBER.** Only translate-then-embed: SemEval-2025 T7 Success@10 0.719 | independent | **NONE.** No Indic result from any source |
| 13 | voyage | **voyage-3.5** | 1024 | 1024 | ✅ | unknown | **NONE.** Only MMTEB(Multilingual) Mean(Task) 58.5 (aggregate, not cross-lingual) | competitor (Google) | **NONE** |
| 14 | voyage | **voyage-3.5-lite** | 1024 | 1024 | ✅ | unknown | **NONE, from any source** | n/a (vendor-only claims) | **NONE** |
| 15 | gemini | **text-embedding-004** ⛔ | 768 | — | — | english-mostly / **RETIRED** | **NONE EXISTS BY CONSTRUCTION** — Google substituted a different model for every multilingual benchmark | n/a | **NONE, and none can exist** |
| 16 | together | **BAAI/bge-large-en-v1.5** ⛔ | 1024 | 1024 | ✅ | english-mostly (english-**only**) | **NONE NATIVE.** Translate-first: MRR@5 DE 0.435 / FR 0.578 | independent | **NONE.** English BERT vocabulary |
| 17 | fireworks | **nomic-ai/nomic-embed-text-v1.5** | 768 | 768 | ✅ | english-mostly (english-**only**) | **NONE PUBLISHED** | n/a | **NONE.** 70 Devanagari + 36 Tamil single-char tokens in a 30,522 vocab |
| 18 | ollama | **nomic-embed-text** | 768 | 768 | ✅ | english-mostly (english-**only**) | **NONE PUBLISHED** | n/a | Same weights as #17 |
| 19 | lmstudio | **text-embedding-nomic-embed-text-v1.5** | 768 | 768 | ✅ | english-mostly (english-**only**) | **NONE PUBLISHED** | n/a | Same weights as #17 |
| 20 | ollama | **mxbai-embed-large** | 1024 | 1024 | ✅ | english-mostly (english-**only**) | **NONE PUBLISHED** | n/a | **NONE.** Identical 30,522 bert-uncased vocab |
| 21 | lmstudio | **text-embedding-all-minilm-l6-v2** | 384 | 384 | ✅ | english-mostly (english-**only**) | MTEB(Indic) cross-lingual STS **−6.3** | independent | **MTEB(Indic) rank 12/12**, avg 31.8, Bitext 2.5, Retrieval 6.2 |
| 22 | sentence_transformers | **all-MiniLM-L6-v2** | 384 | 384 | ✅ | english-mostly (english-**only**) | MTEB(Indic) cross-lingual STS **−6.3** (negative correlation) | independent | Same as #21. IndicSTS en-ta −0.210 |

⛔ = flagged DEPRECATED in Oreag's catalog today. **#15 is not deprecated, it is dead** — see §4.

### 2.1 The ranking, on the number that matches Oreag's dominant case

Belebele `*C/engQ` (English query, non-English corpus), nDCG@10 ×100 [independent, MTEB]:

```
gemini-embedding-001            94.4
cohere embed-multilingual-v3.0  87.9
multilingual-e5-large-instruct  87.5
voyage-3-large                  85.3
voyage-3.5                      80.6
jina-embeddings-v3              78.9
text-embedding-3-large          78.2
─────────────────────────────────────  usable / not usable
text-embedding-3-small          62.9
─────────────────────────────────────  measured failure
mxbai-embed-large-v1            36.9
bge-large-en-v1.5               36.7
nomic-embed-text-v1.5           30.5
all-MiniLM-L6-v2                26.2
```

Not in this table because no run exists: `embed-v4.0`, `mistral-embed`, `voyage-3.5-lite`, `ada-002`, `text-embedding-004`. Their absence is a finding, not a gap in the search — the MTEB results repo was enumerated (688 model directories) and probed per-file (404 on `BelebeleRetrieval.json`, `MLQARetrieval.json`, `IndicCrosslingualSTS.json`, `MintakaRetrieval.json`, `XQuADRetrieval.json` for `Cohere__Cohere-embed-v4.0`, versus 200 on all six for `embed-multilingual-v3.0`).

### 2.2 Where the benchmarks disagree — do not pick off one number

| Model | Belebele cross mean | MLQA cross mean | Winner |
|---|---|---|---|
| gemini-embedding-001 | **0.9069** | 0.7892 | Belebele |
| text-embedding-3-large | 0.6961 | **0.8181** | MLQA |

MLQA passages are literal translations of one another, which rewards surface lexical overlap; Belebele is harder. The ranking **flips** between them. (Note: the openai-3-small MLQA cross mean was corrected from an asserted 0.6429 to the actual **0.4328** on re-check of the raw JSON.)

---

## 3. Tier write-ups

### 3.1 strong-multilingual

**`gemini-embedding-001` (gemini, 3072 → recommend 1536).** The strongest cross-lingual and strongest Indic evidence of any catalog model, and most of it is independent: Belebele English-query-over-Hindi-corpus 0.9624 against its own English-only 0.9691 — a near-zero cross-lingual penalty — and a cross-lingual mean of 0.9069 over 254 subsets [independent, MTEB]. IndicCrosslingualSTS en-hi 0.754 / en-ta 0.705 / 12-lang mean 0.629, roughly 5× text-embedding-3-large's 0.126 [independent]. Google's own XTREME-UP figures (hi 69.1, ta 68.6, avg 64.33) are `[vendor]` and point the same way ([arXiv 2503.07891](https://arxiv.org/html/2503.07891v1)), but its MIRACL win must be discounted: MIRACL is a **declared training set** in the model's MTEB metadata. Caveats that matter operationally: 2,048-token input limit (smallest hosted model in the catalog), 3072 default gets no index, and non-3072 output is **not normalised by the API** (§6.3). Google now foregrounds `gemini-embedding-2` and demotes 001 to "For text-only use cases, gemini-embedding-001 remains available" ([ai.google.dev](https://ai.google.dev/gemini-api/docs/embeddings)) `[vendor]`; shutdown May 14, 2028.

**`embed-multilingual-v3.0` (cohere, 1024).** The cleanest evidence base in the catalog: Cohere publishes **zero** benchmark numbers on any docs page ([docs.cohere.com/v2/docs/models](https://docs.cohere.com/v2/docs/models)), so nothing here is self-reported. Belebele cross mean 0.8081, second only to Gemini, and **symmetric in both directions** — the into-Indic direction loses only 6–8 points where OpenAI loses 22–45 [independent, MTEB]. IndicSTS 12-lang mean 0.467. Fixed 1024 dims is a feature: it is inside the indexed set with no truncation decision to get wrong. Two caveats found on re-check: MTEB's `model_meta.json` records `embed_dim` **512** while Cohere's docs say 1024 — either MTEB evaluated a half-width configuration or the metadata is wrong, and if the former these strong scores were achieved at half production width; and the run used `mteb_version` 1.18.0 versus 1.34.7 (gemini) and 1.38.54 (embed-v4.0), so the three-way comparison spans three harness generations. 512-token context. Requires `input_type` (`search_document` / `search_query`) — Oreag must set this per call.

**`intfloat/multilingual-e5-large-instruct` (together, 1024).** Best *monolingual* non-English model in the catalog, mid on cross-lingual — the split is the whole story. MMTEB rank 1 overall by Borda (1375), **MTEB(Indic) rank 1 at 70.2** ([arXiv 2502.13595](https://arxiv.org/html/2502.13595v1)) [independent]; MIRACL (all) 65.7, reported in *Jina's* paper where it beats Jina [competitor, therefore credible]; best of 8 on low-resource Indian languages, Recall@1 hi 31.9% / ta 27.3% / bn 27.6% / te 27.5%, beating BGE-M3 on every one ([arXiv 2601.10205](https://arxiv.org/html/2601.10205v1)). But XTREME-UP is only 18.7, with a Malayalam collapse to 8.6 against voyage-3-large's 45.3 ([arXiv 2509.20354](https://arxiv.org/html/2509.20354v1)). **The instruction prefix is load-bearing and asymmetric** — queries need `Instruct: <task>\nQuery: `, documents must not get it; embedding both through one code path loses accuracy *and* shifts the cosine distribution, which directly poisons a global floor. 512-token max sequence — the shortest in the catalog. **Availability risk:** Together's page states this model "is not available on Together's Serverless API," and Together's docs elsewhere say "There are currently no embedding models offered via serverless" while the API reference still enumerates models — self-contradictory, needs a live probe.

**`voyage-3-large` (voyage, 1024).** Best measured cross-lingual score of any catalog specialist: **XTREME-UP MRR@10 39.2**, second of eleven models, on a task the paper defines as "mapping queries in 20 underrepresented languages to English passages" — genuinely query-in-B-over-corpus-in-A ([arXiv 2509.20354 Table 9](https://arxiv.org/html/2509.20354v1)) [competitor — Google publishing a rival that beats Google's own Gecko badly, which raises credibility]. Per-language hi 54.3, ta 36.0 (vs text-embedding-3-large's ta **6.0**), pa 48.4, gu 46.7, ml 45.3; collapses on the smallest languages (mni 19.2, brx 7.9). Voyage itself has never published a single Indic or MIRACL number. Caveats: Voyage's docs class it **legacy** ("Previous generation…", superseded by voyage-4) ([docs.voyageai.com](https://docs.voyageai.com/docs/embeddings)); the API also offers 2048 dims which is **outside** the indexed set — keep the catalog pinned at 1024; evidence is n=1 table.

### 3.2 usable-multilingual

**`embed-v4.0` (cohere, 1536).** Downgraded from strong-multilingual. Its 1536 default is indexed and its 128k context is the best in the catalog by a wide margin (vs Gemini's 2,048), but **there is no cross-lingual number for it from any source** — Cohere publishes none, and the MTEB results directory holds 35 files versus 298 for its predecessor, with every cross-lingual task 404. The one independent multilingual number that exists is monolingual MIRACL, on which it places **third of four and loses to the model it replaces in every Indic language**: hi 0.591 vs 0.624, bn 0.722 vs 0.759, te 0.731 vs 0.834 [independent, MTEB]. Harness drift (1.38.54 vs 1.18.0) is a possible confound — treat as a strong flag to A/B, not proof. Recommend it for long-chunk and multimodal projects; recommend `embed-multilingual-v3.0` for Indic-heavy retrieval. One unresolved spec conflict: Microsoft Foundry lists Cohere `embed-v-4-0` as 512 text tokens and 10 languages (no Hindi), contradicting Cohere's own docs — matters only if a user routes Cohere via Azure Foundry.

**`jina-embeddings-v3` (jina, 1024).** The marketing trap of the catalog, and the nuance is worth stating precisely. It **can** discriminate Hindi meaning cross-lingually — ALEE English-anchor/Hindi-reference triplet accuracy 0.87–0.94 ([arXiv 2607.00171](https://arxiv.org/html/2607.00171)) [independent] — but it **cannot rank** against a large English corpus: XTREME-UP 8.5, third-worst of the models in that table, 4.6× below voyage-3-large and 2.2× below multilingual-e5-large-instruct [competitor]. MTEB(Multilingual v2) 58.37, below BGE-M3, below mE5-instruct, roughly level with text-embedding-3-large. Jina's own MIRACL 61.9 loses to mE5-large 66.5 — self-damaging and therefore credible `[vendor]`. **Tamil is absent from Jina's own best-30 language list**; Hindi, Bengali and Urdu are on it. **Jina has deprecated it**: "This model is deprecated by newer models… For new multilingual projects, prefer jina-embeddings-v5-text-small" ([jina.ai/models/jina-embeddings-v3](https://jina.ai/models/jina-embeddings-v3/)). Task adapters matter modestly (45.98 vs 45.20 nDCG@10 for asymmetric vs single adapter, Table 8) but Oreag should still set `task=retrieval.query` / `retrieval.passage` — the default is tuned for symmetric STS, not asymmetric search. Verdict: usable for **monolingual** non-English work; effectively unusable for cross-lingual ranking.

### 3.3 english-mostly

**`text-embedding-3-large` (openai + azure, 3072 → 1024).** Adequate on Latin-script European cross-lingual (STS17 es-en 87.6) and catastrophic on Indic. IndicCrosslingualSTS 12-lang mean **0.126**, with **en-ta 0.0056** — a Tamil sentence and its exact English translation are essentially uncorrelated in this space — and en-or −0.028 [independent, MTEB]. XTREME-UP 18.8 avg with **Tamil 6.0** [competitor]. Belebele shows a severe directional asymmetry no vendor discloses: English-query-over-Tamil-corpus 0.4285 versus Tamil-query-over-English-corpus 0.2146, against its own English-only 0.9653. Its "independent" reputation is weaker than it looks: Snowflake did not reproduce OpenAI's MIRACL 0.549 — that cell is asterisked as cited from Lee et al. (2024), i.e. Google's own work, and 0.549 is numerically identical to OpenAI's launch figure. It is a citation loop presented as third-party corroboration. **OpenAI's own docs make no multilingual claim at all** and publish only English MTEB averages ([developers.openai.com](https://developers.openai.com/api/docs/guides/embeddings)). 8,192-token input is a genuine advantage over Gemini's 2,048.

**`text-embedding-3-small` (openai + azure, 1536).** The most dangerous popular default. Belebele cross-lingual mean 0.5370 — **worse cross-lingually than monolingually** (0.5896), a ~15× collapse from English-only 0.9541 to English-query-over-Tamil-corpus 0.0651. IndicCrosslingualSTS 12-lang mean **0.041 with negative entries** (en-or −0.123, en-as −0.095, en-ta −0.037, en-kn −0.006); best is en-hi at 0.253 [independent, MTEB]. Its MIRACL 44.0 is vendor-only, relayed by Microsoft Learn with the prefix "OpenAI reports that testing shows…". 1536 dims **is** indexed and it is the cheapest hosted model, which is exactly the risk: cheap, fast, indexed, and measurably below chance on Indic translation pairs. One asserted superlative ("last of every model tested on Belebele cross-lingual") is **UNVERIFIED** — not every model's file was enumerated.

**`text-embedding-ada-002` (azure, 1536, fixed).** MIRACL 31.4 vs 3-large's 54.9 — the worst multilingual score in the hosted catalog `[vendor, via Microsoft Learn which explicitly attributes it to OpenAI]`. **No independent multilingual evidence exists**: all three MTEB revision folders were enumerated and contain no MIRACL, Belebele, MLQA, IndicCrosslingualSTS or XQuAD; the single multilingual artifact is a French-only Mintaka run at `mteb_version` 1.1.3.dev0, nDCG@10 0.2994. Not Matryoshka — the `dimensions` field must equal 1536, and a client-side slice would silently corrupt it. Microsoft: "You can't upgrade between embedding models… you need to generate new embeddings." Legacy only. On the cross-lingual axis specifically, `unknown` is as defensible as `english-mostly`, because the absence is total.

**`text-embedding-004` (gemini, 768) — RETIRED, see §4.**

**`BAAI/bge-large-en-v1.5` (together, 1024).** BAAI is unambiguous: the model card's Language column reads "English" next to bge-m3's "Multilingual," and the card itself redirects you — "If you are looking for a model that supports more languages… you can try using bge-m3." Arctic-Embed 2.0 Table 1 lists it with `multilingual? = no` and **dashes** in the CLEF/MIRACL columns [independent]. English MTEB 64.23 avg / 54.29 retrieval / **83.11 STS** (corrected — 83.11 is the STS column, not pair classification, which is 87.12) `[vendor]`. The only non-English number anywhere is a translate-first one: MRR@5 EN 0.545 / DE 0.435 / FR 0.578 with queries machine-translated to English by Llama-3-70B ([arXiv 2605.24236](https://arxiv.org/html/2605.24236v1)) [independent] — and it **ties** e5-large-v2 (also English-only) on German while both beat native multilingual-e5-large (0.416), so that result credits the *translation step*, not this model.

**`nomic-embed-text-v1.5` (fireworks / ollama / lmstudio, 768) — same weights, three names.** Nomic's paper abstract: "the first fully reproducible… **English** text embedding model" ([arXiv 2402.01613](https://arxiv.org/abs/2402.01613)) `[vendor]`. Appears in **no** multilingual or cross-lingual table anywhere — verified absent from MMTEB by full-text search ("nomic" does not appear in arXiv 2502.13595), from Hindi-BEIR, from EmbeddingGemma's tables. **Critical disambiguation:** there is no multilingual variant of v1.5. Nomic's multilingual model is the separately-named `nomic-embed-text-v2-moe` (~100 languages); the adjacent `nomic-embed-vision-v1.5` is multi**modal**, not multi**lingual** — that adjective collision is the likely source of confusion. Requires `search_query: ` / `search_document: ` prefixes; omitting them costs English quality too. Ollama serves 2K context vs 8192 upstream. **84.9M Ollama pulls** — the highest-volume silent failure in the catalog.

**`mxbai-embed-large` (ollama, 1024).** Mixedbread's own blog: "our flagship, state-of-the-art **English** embedding model," trained on 700M+ scraped English pairs; MTEB v1 average 64.68 over 56 English datasets, retrieval 54.39, STS 85.00 `[vendor]`. Mixedbread ships a *separate* German model, which settles the question. Absent from MMTEB (full-text verified), BGE-M3's tables, Hindi-BEIR and EmbeddingGemma. The asserted "English MTEB rank ~9 at release" is **UNVERIFIED and should be dropped** — a historical leaderboard position is unverifiable after the fact.

**`all-MiniLM-L6-v2` (sentence_transformers) and `text-embedding-all-minilm-l6-v2` (lmstudio), 384.** MMTEB MTEB(Indic): **rank 12 of 12** (Borda 40), avg 31.8, Bitext Mining **2.5**, Retrieval **6.2**, and cross-lingual **STS −6.3** — a *negative* correlation on English↔Indic sentence pairs ([arXiv 2502.13595](https://arxiv.org/html/2502.13595v1)) [independent, 85-author ICLR-accepted community benchmark, no vendor stake]. The paper states verbatim: "we observe the expected detrimental performance of English models (all-MiniLM-L12, all-MiniLM-L6, all-mpnet-base) applied to non-English languages." **Column-alignment trap:** the correct row order is Btxt 2.5 | PairClf 53.7 | Clf 44.1 | STS −6.3 | Retrieval 6.2 — two independent extractions of the same HTML mis-assigned −6.3 to retrieval. Note also that MTEB(Indic)'s retrieval tasks (Belebele, XQuAD) are **monolingual**; the genuinely cross-lingual cell is IndicCrosslingualSTS, i.e. the −6.3.

### 3.4 unknown

**`mistral-embed` (mistral, 1024).** Downgraded from english-mostly to unknown, because *both* readings are unsourced. Mistral publishes a dimension and nothing else: no language list, no benchmark, no multilingual claim, on either the embeddings page or the models overview ([docs.mistral.ai](https://docs.mistral.ai/studio/knowledge-rag/embeddings/text_embeddings)). Absent from MMTEB, EmbeddingGemma, Gemini Embedding 2, Arctic-Embed 2.0 and Qwen3-Embedding. Two European datapoints only: MTEB-French overall 0.68, level with **bge-m3** and above multilingual-e5-large 0.66 ([arXiv 2405.20468](https://arxiv.org/html/2405.20468v2)) — not the profile of an English-only encoder; and SemEval-2025 Task 7 cross-lingual Success@10 0.719, where the paper states verbatim "All texts are translated to English except for mGTE" ([arXiv 2508.09517](https://arxiv.org/html/2508.09517)). **That 0.719 is a translate-then-embed number, not native cross-lingual embedding** — and it beat genuinely-multilingual mGTE used natively (0.574) by 14.5 points, which is direct evidence *for* routing this model through translation. Model is v23.12 and unchanged while Mistral shipped codestral-embed v25.05 for code.

**`voyage-3.5` (voyage, 1024).** Vendor claim and the one independent number point in **opposite directions**, and that contradiction is the single most important thing to tell a user. Voyage: "+8.26% over OpenAI-v3-large" (aggregate percentage, no absolute score, no per-language breakdown) `[vendor]`. Google's Gemini Embedding 2 paper Table 2: MMTEB(Multilingual) Mean(Task) **58.5**, versus Gemini Embedding 2 at 69.9 and Gemini Embedding at 68.4 ([arXiv 2605.27295](https://arxiv.org/html/2605.27295v1)) [competitor]. Three caveats the raw comparison hides: that 58.5 is competitor-run, cross-paper calibration against EmbeddingGemma's table is not valid (different papers, differently-versioned task sets), and **MMTEB(Multilingual) is not a cross-lingual benchmark** — it is dominated by monolingual-per-language tasks. Zero cross-lingual measurements of any kind exist. Do **not** transfer voyage-3-large's 39.2 here; they are different models and the one benchmark scoring both families disagrees with the vendor's ordering. Legacy per Voyage's docs.

**`voyage-3.5-lite` (voyage, 1024).** Zero independent numbers of any kind — confirmed absent from EmbeddingGemma (all baselines enumerated) and Gemini Embedding 2 (Tables 1–8 enumerated). Every claim traces to Voyage's own "+6.34% vs OpenAI-v3-large" `[vendor]`. Structural problem: because Voyage publishes only relative percentages against self-selected comparators, even the vendor evidence cannot be converted into a comparable absolute score. **It is the cheapest Voyage option ($0.02/1M), so it is the one a cost-sensitive BYOK user will reach for, and it is the one with zero verification.** Distilled "lite" models carry a known cross-lingual penalty risk (Qwen3-Embedding-0.6B scored 6.6 on XTREME-UP), so its cross-lingual behaviour must not be inferred from its English aggregate. (One sub-claim — "no voyage-3.5-lite folder in the MTEB results repo" — is **UNVERIFIED**; the leaderboard Space is JS-rendered and the parquet-backed dataset has no browsable per-model tree.)

---

## 4. WARNING LIST — models a user can pick today that will silently fail

Silently is the operative word. Every model below returns a **well-formed unit vector with plausible-looking cosine scores and no error** on a Hindi or Tamil query. Postgres FTS on `content_tsv` will keep doing real lexical work on the other leg of the hybrid, so RRF returns a half-plausible-looking list rather than an obviously broken one.

### Tier A — will produce garbage, not degraded results

| Model | Entry points | Evidence | Why the failure is invisible |
|---|---|---|---|
| **all-MiniLM-L6-v2** | `sentence_transformers`, `lmstudio/text-embedding-all-minilm-l6-v2` | MTEB(Indic) rank 12/12, Bitext **2.5**, cross-lingual STS **−6.3** ([arXiv 2502.13595](https://arxiv.org/html/2502.13595v1)) | 30,522-token bert-uncased vocab: **70 Devanagari and 36 Tamil tokens, all bare isolated letters** (अ आ उ ए क ख ग…). Hindi/Tamil is shredded to characters and `[UNK]`. Verified by downloading `vocab.txt` and counting |
| **nomic-embed-text-v1.5** | `fireworks`, `ollama/nomic-embed-text`, `lmstudio/text-embedding-nomic-embed-text-v1.5` | Vendor abstract says "English"; absent from every multilingual table (MMTEB full-text verified) | **Byte-identical vocab profile** to all-MiniLM: 30,522 / 70 / 36. 8192 context and better English buy nothing. **84.9M Ollama pulls** |
| **mxbai-embed-large** | `ollama` | Vendor calls it "our flagship… **English** embedding model"; separate German model exists | Same 30,522 / 70 / 36 vocab. **1024 dims puts it visually alongside voyage-3.5, cohere embed-multilingual-v3.0 and mistral-embed — same width, opposite language coverage** |
| **BAAI/bge-large-en-v1.5** | `together` | Card Language column: "English"; Arctic Table 1 `multilingual? = no` with dashed CLEF/MIRACL | **1024 dims, five characters from `bge-m3` in a dropdown.** BAAI ships a genuinely multilingual model under the same brand |

**All three local English models share ONE tokenizer bottleneck**, verified empirically rather than read off model cards. A user switching providers from `ollama` to `fireworks` to `lmstudio` to "fix" bad Hindi retrieval changes literally nothing — those are the same weights under three names.

### Tier B — measurably below usable on Indic, but will look plausible

| Model | The number | Sharpest fact |
|---|---|---|
| **text-embedding-3-small** (openai, azure) | IndicSTS 12-lang mean **0.041**, several values negative | Cheapest hosted model, 1536 dims **is** indexed, so nothing in Oreag flags it. Most likely wrong choice for a multilingual project |
| **text-embedding-3-large** (openai, azure) | IndicSTS **en-ta 0.0056**; XTREME-UP **ta 6.0** | Fine on European cross-lingual (STS17 es-en 87.6), near-zero on Indic. "Multilingual" is not one axis |
| **text-embedding-ada-002** (azure) | MIRACL 31.4 `[vendor]`, **no independent multilingual data at all** | Cannot be dimension-reduced, cannot be upgraded in place. Version-1 deployments cap at 2,046 tokens and silently truncate normal chunks |
| **jina-embeddings-v3** (jina) | XTREME-UP **8.5** | Markets itself as a frontier *multilingual* model. **Tamil is not on its own best-30 list.** Vendor-deprecated |

### Tier C — no evidence at all (unknown ≠ safe)

- **`mistral-embed`** — no vendor language list, no benchmark, no native cross-lingual number. Using it on an Indic corpus is a leap of faith.
- **`voyage-3.5`** — vendor claim and the single independent number contradict each other.
- **`voyage-3.5-lite`** — zero third-party numbers, and the cheapest option in its family.
- **`cohere embed-v4.0`** — no cross-lingual run exists; its only independent multilingual number puts it below its own predecessor in every Indic language.

### Tier D — hard block, not a warning

**`gemini/text-embedding-004` is retired, not deprecated.** Shutdown date **January 14, 2026**, replacement `gemini-embedding-2` ([ai.google.dev deprecations](https://ai.google.dev/gemini-api/docs/deprecations); confirmed on Google's GA blog for gemini-embedding-001). Today is 2026-09-08 — it has been dead ~8 months and every call fails. Oreag labels it `DEPRECATED`, which is materially wrong: projects on it are **broken, not degraded**.

Worse, it never had multilingual capability to lose. Google's own Gemini Embedding paper footnotes Table 1 verbatim: *"For Gecko Embedding (Lee et al., 2024), we evaluate text-embedding-004 on MTEB(Eng, v2), text-embedding-005 on MTEB(Code), and text-multilingual-embedding-002 on others."* Google substituted a **different model** for every multilingual and cross-lingual benchmark. Snowflake independently lists "Google Text Emb. 4" with `Multilingual = no` ([arXiv 2412.04506](https://arxiv.org/html/2412.04506v2)). **Anyone attributing XOR-Retrieve 65.67 or XTREME-UP 34.97 to text-embedding-004 is misreading that footnote** — those belong to `text-multilingual-embedding-002`.

Migration trap: at 768 dims it *was* indexed. A project migrating to `gemini-embedding-001`'s 3072 default would **also silently lose its index**. Migrate to 1536 (or 768) and apply the manual L2 renormalisation §6.3 requires.

### 4.1 How each failure interacts with the floor

- **English-only encoders produce compressed, high-and-flat cosine distributions on out-of-vocabulary script.** "Best cosine below floor" may **never fire** on exactly the corpora where translation is most needed — the fallback is dead code precisely where it is essential.
- On models whose IndicSTS is ~0.0 (`text-embedding-3-large`, `text-embedding-3-small`), the cosine on an English-query/Indic-passage pair carries almost no signal, so the floor is comparing noise to a constant.
- On high-anisotropy models (E5 family, RandCos ~0.70), a 0.40 floor sits **below the noise floor** and can never trigger.

### 4.2 The four cheap product moves

1. **`language_scope` badge** per catalog row (`english_only` | `multilingual`), rendered in the picker and usable as a filter. This is the pattern Google ships in Vertex RAG Engine's own model table (`e5-small-v2` "English-only", `multilingual-e5-large` "multilingual"), and Weaviate's phrasing is the one to copy verbatim because it is scoped to the **corpus**, not the model: *"Best for datasets primarily in English."* For most catalog entries the badge is derivable from the model name with zero research (`embed-multilingual-*`, `multilingual-e5-*`, `bge-large-**en**-v1.5`, `all-MiniLM`); only `mistral-embed`, `nomic-embed-text`, `mxbai-embed-large` need a lookup.
2. **Default to multilingual.** Weaviate reduced its whole two-model catalog to "is your corpus monolingual English or not" and made the multilingual model the default. A wrong English-only default degrades every non-English project with no error.
3. **Gate the translate path on a per-project `corpus_languages` list** (user-declared first, RAGFlow-style; detected later). `IF best_cosine < floor AND array_length(corpus_languages,1) > 1`. This collapses the false-positive cost — translating and re-embedding on a monolingual corpus, burning the user's own BYOK tokens for nothing — to zero without any per-model calibration.
4. **Consider translate-first, not translate-as-fallback, for `english-mostly` models.** Two independent measurements say an English-only encoder plus translation beats a multilingual encoder used natively: bge-large-en-v1.5 at MRR@5 DE 0.435 / FR 0.578 vs multilingual-e5-large's 0.416 / 0.511 ([arXiv 2605.24236](https://arxiv.org/html/2605.24236v1)), and mistral-embed at 0.719 vs mGTE's 0.574 ([arXiv 2508.09517](https://arxiv.org/html/2508.09517)). For a model at XTREME-UP 8.5, "search, check the floor, maybe translate" wastes a round trip and depends on the floor reading that is least trustworthy. **Counter-evidence exists** and should be weighed: for a genuinely strong multilingual encoder, native beats translation — BGE-M3 Tamil→English Recall@15 95.6% vs Google Translate 93.0% ([arXiv 2608.12820](https://arxiv.org/html/2608.12820)). So: translate-first for `english-mostly`, native-first for `strong-multilingual`.

---

## 5. Gaps in the catalog — models Oreag could add

### 5.1 Recommended additions

| Model | Provider path | Dim | Why | Evidence class |
|---|---|---|---|---|
| **BAAI/bge-m3** | ollama / lmstudio / sentence_transformers | **1024** ✅ | Safest local default | **Best independent Indic cross-lingual evidence in this whole report** |
| **google/embeddinggemma-300m** | ollama / lmstudio / sentence_transformers | **768** ✅ (MRL 512/256 also indexed) | Best cross-lingual number for a locally runnable model | Vendor-published, broad comparison set |
| **nomic-embed-text-v2-moe** | ollama | **768** ✅ | One-line upgrade for the 84.9M-pull nomic crowd | Vendor-only, unreplicated |
| **gemini-embedding-2** | gemini | — | Google's current flagship; auto-normalises truncated dims | Vendor |

**`bge-m3` — the safest default.** The only model anywhere with a genuinely independent, non-vendor Tamil→English cross-lingual retrieval number: **Recall@15 95.6% Tamil→English and 96.2% Sinhala→English against an English corpus of 1,699 Sri Lankan government contexts, beating the strongest query-translation pipeline (Google Translate 93.0% / 92.4%; NLLB 89.0% / 87.0%)** ([arXiv 2608.12820](https://arxiv.org/html/2608.12820)). Best neural model on Hindi-BEIR at 47.29 avg nDCG@10 vs mE5 39.93, BM25 36.50, LaBSE 18.72 ([arXiv 2408.09437](https://arxiv.org/html/2408.09437)). Second-best open model on XTREME-UP at 26.9 ([arXiv 2509.20354](https://arxiv.org/html/2509.20354v1)). XLM-RoBERTa backbone (~250k SentencePiece vocab with real Devanagari and Tamil subwords — the exact opposite of the bert-uncased 30,522 shared by all three current local models). 1024 dims matches the indexed set and the width of voyage/cohere-multilingual/mistral, so it is a like-for-like local swap. **8192 context — the longest of any recommended multilingual local model.** MIT. **No task prefix required**, which removes a whole class of silent misconfiguration. UNVERIFIED: this entry did not pass a verification pass.

**`embeddinggemma-300m` — best cross-lingual number a local user can run.** XTREME-UP MRR@10 **47.7**, beating voyage-3-large's 39.2 despite being 308M params ([arXiv 2509.20354 Table 9](https://arxiv.org/html/2509.20354v1)) `[vendor — Google authored the paper, but the comparison set is broad and the benchmark is public]`. XOR-Retrieve Recall@5kt 84.14. The 20-language XTREME-UP set is overwhelmingly Indic (Hindi, Tamil, Gujarati, Kannada, Malayalam, Marathi, Punjabi, Urdu, Assamese, Odia, Sanskrit…). 768 default and Matryoshka 512/256 are **all** inside Oreag's indexed set, so a user can trade quality for index size without ever hitting the 3072 cliff. Costs: 2048-token context (a regression from nomic v1.5's 8192); **mandatory task prompts** (`task: search result | query: {q}` / `title: none | text: {d}`) that sentence-transformers applies automatically via `encode_query`/`encode_document` but Ollama's `/api/embed` does **not**; and an unresolved licence question — the model card states Gemma Terms with a gated download while the HF launch blog says Apache 2.0. **Verify the licence before shipping this recommendation**; Gemma Terms are not OSI-open and that matters to the self-hosting-for-privacy user this targets. UNVERIFIED entry.

**`nomic-embed-text-v2-moe` — the migration story writes itself.** Same vendor, same 768 dims, one-line pull, for the 84.9M-pull `nomic-embed-text` audience (v2-moe has ~863K pulls — most local users don't know it exists). MIRACL Hindi **67.0**, beating bge-m3's 59.5 and mE5-large's 62.0 `[vendor, arXiv 2502.07972]`. BEIR English 52.86, so it does not sacrifice English. **But: MIRACL is monolingual — there is no true cross-lingual number, no MKQA, no XOR-Retrieve, no XTREME-UP. Say so.** Hard limits: **512-token max sequence** (a severe regression from v1.5's 8192), mandatory `search_query:`/`search_document:` prefixes that Ollama will not add, and **no Tamil evidence at all** — Tamil is in neither MIRACL nor the pretraining table, so Tamil users must not be pointed here on the strength of the Hindi number. UNVERIFIED entry. (Correction applied: the ALEE Hindi triplet-accuracy row cited for this model in research was the wrong language's row; the correct `hin_Deva` values are 0.965/0.981/0.946/0.949 | 0.853/0.910/0.849/0.895 | 0.915/0.927/0.919/0.916, still below mE5-large-instruct and bge-m3, so the directional claim survives.)

**`gemini-embedding-2`.** `ai.google.dev` now foregrounds it as "the first multimodal embedding model in the Gemini API… over 100 languages" and demotes 001. It **auto-normalises truncated dimensions**, which removes the single sharpest production trap in the current catalog (§6.3). MMTEB(Multilingual) Mean(Task) 69.9 vs Gemini Embedding's 68.4 ([arXiv 2605.27295](https://arxiv.org/html/2605.27295v1)) `[vendor]`.

**Also worth carrying, lower priority:** `intfloat/multilingual-e5-large` (non-instruct) via sentence_transformers — MTEB(Indic) rank 2/12 at 66.4 with Retrieval 82.6 and Bitext 77.7, and MIRACL (all) 66.5 (higher than the instruct variant's 65.7). Its value is narrative: it is the **local equivalent of the multilingual model the `together` provider already offers**, at the same 1024 dims, so a hosted→local migration needs no dimension change. Requires `query: `/`passage: ` prefixes. Its XTREME-UP is only 18.7, which is why bge-m3 and embeddinggemma rank above it for Oreag's specific gate. And `jina-embeddings-v5-text-small` (32K context) is Jina's own stated replacement for the deprecated v3 — no numbers gathered.

### 5.2 Evaluated and NOT recommended — the instructive negatives

| Model | Why not |
|---|---|
| **qwen3-embedding:0.6b** | **The central cautionary tale.** MTEB(Multilingual v2) Mean(Task) 64.34 (highest sub-1B in that table) and XTREME-UP **6.6 — dead last of eleven**. If Oreag sorts local models by "MTEB multilingual score" it will actively recommend the worst model for its own cross-lingual feature |
| **paraphrase-multilingual-mpnet-base-v2** | **Hindi is in the 50-language list. Tamil is not. Neither are Telugu, Kannada, Malayalam or Bengali** — the entire Dravidian family plus Bengali, verified against the sbert.net language list. Upstream `max_seq_length` is **128 tokens**. sibling multilingual-MiniLM-L12 scores MTEB(Indic) 49.7 with Bitext 15.3, well below mE5-large's 66.4 / 77.7 |
| **snowflake-arctic-embed2** | Hindi appears in the 74-language tag list but **was never evaluated** — Snowflake's own blog states every score is "average across German, English, Spanish, French and Italian." Fine for a European corpus; entirely unvalidated for Indic. **A tag list is not evidence** |
| **granite-embedding:278m** | Genuinely multilingual across **the wrong 12 languages**: English, German, Spanish, French, Japanese, Portuguese, Arabic, Czech, Italian, Korean, Dutch, Chinese. No Indic language of any kind. (Provenance: language list taken from search-result summaries of IBM's model card, not opened directly — **verify before publishing**) |

All four entries in this subsection are UNVERIFIED (no verification pass).

---

## 6. Dimension guidance

### 6.1 The rule, and how small the problem actually is

**Rule: recommend the largest offered dimension ≤ 1536.** That single rule produces the correct answer for all 22 entries and for any future model, with no per-model knowledge. Applied:

| Provider | Model | Default | Options | **Recommended** | Change needed? | Measured cost of the change |
|---|---|---|---|---|---|---|
| openai / azure | text-embedding-3-large | 3072 | 256, 1024, 3072 | **1024** | ✅ **YES** | ~1–2% English (extrapolated). **Cross-lingual cost at 1024 UNMEASURED**. At 256 it is measured: 93.3% English / **90.3% cross-lingual** retention |
| gemini | gemini-embedding-001 | 3072 | 768, 1536, 3072 | **1536** | ✅ **YES** | MTEB 68.17 @1536 vs 68.16 @2048 — **zero measured English cost**. 768 costs 0.18. **Cross-lingual cost UNMEASURED.** Must L2-normalise (§6.3) |
| openai / azure | text-embedding-3-small | 1536 | 512, 1536 | 1536 | no | — (no index reason to truncate) |
| azure | text-embedding-ada-002 | 1536 | none | 1536 | no | **NOT Matryoshka — never slice** |
| cohere | embed-v4.0 | 1536 | 256, 512, 1024, 1536 | 1536 | no | **1536 is its maximum.** Full fidelity + full index, no trade-off |
| cohere | embed-multilingual-v3.0 | 1024 | none | 1024 | no | no MRL |
| mistral | mistral-embed | 1024 | none | 1024 | no | no MRL |
| voyage | voyage-3.5 / -3.5-lite / -3-large | 1024 | 256, 512, 1024, **2048** | 1024 | no | **Do NOT expose 2048** — outside the indexed set, for no gain |
| jina | jina-embeddings-v3 | 1024 | 256, 512, 1024 | 1024 | no | 512 costs only **0.19 nDCG@10** if storage matters |
| together | multilingual-e5-large-instruct | 1024 | none | 1024 | no | no MRL |
| together | bge-large-en-v1.5 | 1024 | none | 1024 | no | no MRL, deprecated |
| fireworks / ollama / lmstudio | nomic-embed-text-v1.5 | 768 | 64–768 (client-side) | 768 | no | 512 costs 0.32 MTEB |
| ollama | mxbai-embed-large | 1024 | MRL-trained | 1024 | no | "over 93% of performance remains at 512" `[vendor]` |
| lmstudio / sentence_transformers | all-MiniLM-L6-v2 | 384 | none | 384 | no | — |
| gemini | text-embedding-004 | 768 | — | — | **retired** | Retained 94% of MTEB-R at 256 (historical) |

**Only 2 of 22 entries need a decision.** Both are 3072-dim, both currently exact-scan every chunk, and both have an indexed option that is nearly free on English.

### 6.2 The quality cost of truncation, and where it is unmeasured

**The one cross-lingual truncation measurement that exists for a catalog model.** Arctic-Embed 2.0 Table 1 truncates `text-embedding-3-large` to 256 and reports both axes ([arXiv 2412.04506](https://arxiv.org/html/2412.04506v2)) [competitor]:

| Metric | Full | @256 | Retention |
|---|---|---|---|
| MTEB-R (English retrieval) | 0.554 | 0.517 | **93.3%** |
| CLEF (cross-lingual retrieval) | 0.565 | 0.510 | **90.3%** |

**Cross-lingual loses ~1.45× as much relative quality as English.** Since Oreag's cross-lingual path is gated on cosine quality, aggressive truncation degrades precisely the capability the translation fallback exists to serve — and it degrades it *more* than an English-only benchmark would reveal.

**Retention under truncation is not scale-free.** At the same nominal 256 dims: jina-v3 loses 1.0% relative (1024→256: 63.35→62.72 nDCG@10, [arXiv 2409.10173](https://arxiv.org/html/2409.10173v2)), text-embedding-3-large loses 6.7% English / 9.7% cross-lingual, Arctic's own models retain 98–99%, Google text-embedding-004 retained 94%. That is a **7–10× spread at the same dimension**, because MRL was applied at different training stages. **Oreag cannot ship one global truncation policy.** It must be a per-model table — which a BYOK product *can* do, since the catalog is fixed and finite.

**Direction, not magnitude, is what transfers.** Three independent sources agree that cross-lingual degrades at least as fast as monolingual under truncation: Arctic on OpenAI/CLEF, Arctic on its own models, and M3DR on its own (22-language Gemma3-Matryoshka cross-lingual / monolingual NDCG@5: 2056-dim 77.31 / 74.10; **1536-dim 76.87 / 73.25**; 768-dim 73.15 / 70.77 — so 2056→1536 retains 99.4% cross-lingual, but 2056→768 costs 4.16 points cross-lingual vs 3.33 monolingual; at 6 languages the same paper saw a 3-point cross-lingual drop *while monolingual improved slightly*, [arXiv 2512.03514](https://arxiv.org/html/2512.03514)). **Use the direction to set policy; never quote a magnitude for a model it was not measured on.**

**EXPLICITLY UNMEASURED — flag these in the UI rather than inventing a number:**

- **The cross-lingual cost of truncating `text-embedding-3-large` to 1024** — the exact configuration this document recommends. Only the 256 point is measured.
- **The cross-lingual cost of truncating `gemini-embedding-001` to 1536 or 768.** Google publishes no cross-lingual-by-dimension data. (The MRL table itself — 68.17@1536, 67.99@768, 67.55@512, 66.19@256, 63.31@128 — traces to Google's docs page for English MTEB only.)
- **`jina-embeddings-v3` truncation cross-lingually.** The paper's Table 6 curve is thorough and aggregate; MIRACL appears only at full 1024. The vendor measured truncation, measured multilingual, and never crossed the two. Any warning about truncating jina cross-lingually would be extrapolation.
- **`cohere embed-v4.0`** — zero per-dimension quality numbers published for any of 256/512/1024/1536.
- **Voyage** — only relative percentages, never absolute nDCG by dimension, and no cross-lingual breakdown at all.
- **Whether Ollama / LM Studio / Fireworks apply nomic-v1.5's required `layer_norm` server-side**, which determines whether client-side truncation there is even valid.

Jina's own paper notes the blind spot is industry-wide: OpenAI's and Cohere's models "were not evaluated on the full range of multilingual and cross-lingual MTEB tasks."

**Do not repeat OpenAI's reassurance.** Its entire public truncation justification is one sentence — "a text-embedding-3-large embedding can be shortened to a size of 256 while still outperforming an unshortened text-embedding-ada-002 embedding with a size of 1536" ([developers.openai.com](https://developers.openai.com/api/docs/guides/embeddings)) `[vendor]`. True, but it sets the bar at a 2022 model, says nothing about the delta Oreag cares about, and conceals that 3-large is among the **worst** truncators measured. OpenAI reported MIRACL 31.4→54.9 at full dimension and never re-measured MIRACL at any reduced dimension — the multilingual gain that justifies the model is the number never revisited after truncation. Warning copy should read as a sourced third-party figure: *"1024 recommended for indexing. Independent measurement at 256 dims: 93% English / 90% cross-lingual retention (Snowflake, arXiv 2412.04506). Cost at 1024 is not published."*

### 6.3 The normalisation caveat — four different vendor contracts, and Gemini's is inverted

This is a live production trap, not a theoretical one.

| Provider | Contract |
|---|---|
| **OpenAI** | Returns unit-norm vectors **including** when `dimensions` is passed. Renormalise only if you slice client-side: "When you change the dimension manually, you need to be sure to normalize the dimensions of the embedding" ([developers.openai.com](https://developers.openai.com/api/docs/guides/embeddings)) |
| **Gemini (`gemini-embedding-001`)** | **The opposite.** Only the default 3072 output is normalised; "you must manually normalize non-3072 dimensions" ([ai.google.dev](https://ai.google.dev/gemini-api/docs/embeddings)). `gemini-embedding-2` auto-normalises truncated dims |
| **Voyage** | Normalises, but their own truncation example renormalises after slicing anyway |
| **Nomic v1.5** | Card mandates the order **`layer_norm` → truncate → L2-normalise**, in that order, in both the Sentence Transformers and Transformers examples ([HF card](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5)) |
| **Cohere** | **Says nothing either way**, at any output dimension. Measure `‖v‖` empirically |

**Why this bites Oreag specifically.** To get an HNSW index for a Gemini project, Oreag must request **1536** — which is precisely the configuration that returns **unnormalised** vectors. A truncated unit vector has ‖v‖ < 1, so any inner-product path understates true cosine by a factor of ‖a‖·‖b‖. Depressed similarities fall below `cross_lingual_similarity_floor`, so the translate-and-re-embed path **fires when it should not**: extra latency, extra embedding calls, extra metered spend on the user's own BYOK key, on every query. It degrades quietly and looks like "Gemini is just bad at cross-lingual."

- `pgvector`'s `<=>` (`vector_cosine_ops`) is **safe** — cosine distance normalises internally.
- `<#>` (inner product), `<->`, an `ip` operator class, and any numpy dot taken because "the vendor says vectors are unit norm" are **not safe**.

**Mitigation (cheap, do it unconditionally):** L2-normalise every embedding in Oreag's own Python at both ingest and query time — one line, idempotent for providers that already normalise, and it makes all 22 models behave identically regardless of vendor contract. Then add an assertion that ‖v‖ ≈ 1.0 ± 1e-3, logging provider and dimension on failure. That assertion would have caught this.

### 6.4 Three more things the picker should carry

**(a) Truncation capability is a three-class taxonomy, and one class must be hard-blocked.**

- **server-side** (API parameter): OpenAI/Azure v3, `gemini-embedding-001`, `cohere embed-v4.0`, Voyage, Jina. **Prefer these** — the vendor owns the normalise order.
- **client-side only** (MRL-trained open weights): nomic-embed-text-v1.5, mxbai-embed-large. Subtler trap: nomic's mandated `layer_norm`→slice→normalise order may not be reproducible from a server-returned vector.
- **NOT Matryoshka — slicing silently destroys the embedding**: `ada-002`, `mistral-embed`, `multilingual-e5-large-instruct`, `bge-large-en-v1.5`, `all-MiniLM-L6-v2`, `cohere embed-multilingual-v3.0`. OpenAI's API refuses it (`dimensions` must equal 1536 for ada-002); a client-side slice would not. **Add `is_matryoshka: bool` and assert it before any slice — raise, don't proceed.**

**(b) The 1536 ceiling is not actually forced.** pgvector's 2000-dim HNSW cap applies to the `vector` type; **`halfvec` is indexable to 4000 dims**, and pgvector documents the expression-index cast form ([pgvector README](https://github.com/pgvector/pgvector)). So a 3072-dim project can get a real HNSW index via `CREATE INDEX ... USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)` with **no column DDL** — preserving the property that switching models needs only a re-embed. This matters most for `text-embedding-3-large`, where a cross-lingual-heavy project could keep full 3072 fidelity and pay fp16 rounding instead of a measured ~10% cross-lingual retention loss. Gotcha: the probe vector must be cast identically (`embedding::halfvec(3072) <=> $1::halfvec(3072)`) or the planner will not use the index. Storage 6KB+8 vs 12KB+8 per row. **No published fp16-HNSW recall number exists for these models — measure on Oreag's own eval set before defaulting.**

**(c) Cosine scale is a function of dimension, so the dimension recommendation silently re-tunes the floor.** Both the mean and standard deviation of pairwise cosine decay as O(m^−1/2) in dimension m ([arXiv 2606.28330](https://arxiv.org/html/2606.28330)); the same semantic pair scores differently at 256, 1024 and 3072 on the *same model*. Changing a picker default therefore shifts how often the translation path fires, with no code change and no way for the user to see why. The floor must be keyed on `(provider, model, dimension)` at minimum, or replaced with a percentile/rank test — and any calibration row must be invalidated on a dimension change exactly as on a model change.

### 6.5 Recommended catalog schema

```
(provider, model) → {
  default_dim, recommended_dim, indexable_dims,
  is_matryoshka: bool,
  truncation: 'server' | 'client' | 'none',
  needs_client_normalisation: bool,
  language_scope: 'english_only' | 'multilingual',
  cross_lingual_measured: bool,          # ship this to the UI so warnings stay honest
  max_input_tokens: int,                 # validate at chunk time, not just label
  lifecycle: 'current' | 'previous_generation' | 'deprecated' | 'retired',
  replacement_model: str | null
}
```

`lifecycle` must be keyed on `(provider, model)`, not model alone: the same model name can be alive on one provider surface and dead on another, and Oreag carries `text-embedding-3-small`/`-3-large` under **both** `openai` and `azure`. All three Voyage entries are labelled "Previous generation" by Voyage today, and `jina-embeddings-v3` is vendor-deprecated — neither state is expressible in a boolean `DEPRECATED` flag. `max_input_tokens` is absent from the catalog today and silently breaks ingestion: `multilingual-e5-large-instruct` is 512 (Pinecone lists 507 for the family), `cohere embed-multilingual-v3.0` 512, `gemini-embedding-001` 2,048, versus OpenAI's 8,192 and Cohere v4's 128k.

Because `chunks.embedding` is an unconstrained `vector`, **changing any of these recommendations later costs only a re-embed of that project — no DDL, no migration.** Google's Vertex RAG Engine cannot do this at all ("The association between your embedding model and the RAG corpus remains fixed for the lifetime of your RAG corpus"), and AnythingLLM's swap is destructive across all workspaces. That is a real differentiator and should be stated in the picker: *"you can change this later; it re-embeds this project only."*
