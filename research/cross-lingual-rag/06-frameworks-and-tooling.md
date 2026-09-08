# Frameworks and Tooling: What Is Shippable Today

Scope: what you can install, call, or fine-tune **this week** to get "corpus in language A,
question in language B, correct A-passage retrieved, answer generated in B, with a language
policy". Research-only artifacts are listed separately from things with weights or a repo.

## Notation

The five target behaviours, used as columns throughout:

| # | Behaviour |
|---|---|
| **1** | Documents embedded in language A |
| **2** | Query accepted in language B |
| **3** | Retrieval surfaces the semantically correct language-A passage |
| **4** | Answer generated in language B, grounded in the A evidence |
| **5** | Explicit language policy (pin a language, or match the query) |
| **M** | Extra column: works when the corpus **mixes** languages in one index (your known open limit) |

Behaviours 1 and 2 are free in every vector store — embedding a string and accepting a string
are not capabilities. All the information in these tables is in columns **3, 4, 5, M**.
`Y` = shipped and documented. `~` = works but you wire it. `N` = absent. `—` = out of scope.

---

## 1. RAG frameworks and search platforms

| Product | 3 | 4 | 5 | M | What it actually provides | What you still build |
|---|---|---|---|---|---|---|
| [RAGFlow](https://ragflow.io/docs/glossary) | **Y** | N | N | ~ | A real, first-class **Cross-language search** feature since v0.19.0 (26 May 2025): "an English query can be used to retrieve Chinese documents", implemented by having the default chat model translate the query before matching. Supported in the Knowledge and Chat modules, explicitly aimed at "Chinese-English datasets". | Everything about the answer: docs are silent on generated-answer language. No gate — it is an always-on toggle with a target-language dropdown, so you pay translation on every query. Mixed-corpus handling is a manual multi-select fan-out. |
| [Haystack 2.x](https://haystack.deepset.ai/tutorials/32_classifying_documents_and_queries_by_language) | N | N | N | ~ | The only framework with **language routing as real components**: `DocumentLanguageClassifier` tags documents with ISO codes, `MetadataRouter` sends them to per-language stores, `TextLanguageRouter` routes a query to a named output (or `unmatched`). | The routing ships pointed the wrong way. The tutorial states: "The language of a question is detected, and only documents in that language are used to generate the answer." That is your bug as the documented default. Cross-lingual retrieval comes only from the embedder you bring. |
| [Haystack multilingual cookbook](https://haystack.deepset.ai/cookbook/multilingual_rag_podcast) | ~ | ~ | N | N | A ~30-line worked recipe: index Italian transcripts with `multilingual-e5-large`, ask in English, answer in English. Answer language is a **hardcoded prompt string** — "Using only the information contained in these documents in Italian, answer the question using English". | Query-language detection, any policy object, mixed corpora. This is the canonical "a blog post shows you how" artifact, not a feature. |
| [Elasticsearch — LID + per-language fields/indices](https://www.elastic.co/blog/multilingual-search-using-language-identification-in-elasticsearch) | N | — | — | **Y** | Ships a language-identification model (`lang_ident_model_1`) usable in an ingest pipeline, plus two documented mixed-corpus patterns: **language-per-field** (queried with `multi_match`/`best_fields` across all language fields at once) and **language-per-index** (queried via `lang-per-index_*`). The `best_fields` pattern is effectively per-language sub-search + fusion. | Cross-lingual matching — this path only picks the right *same-language* field. Note Elastic explicitly advises **against** detecting the query's language: "search queries tend to be short" and LID "work[s] best with more than 50 characters"; get it from user locale instead. |
| [Elastic Search Labs — multilingual vector tutorial](https://www.elastic.co/search-labs/tutorials/examples/multilingual-model-semantic-search-elasticsearch) | ~ | N | N | ~ | Demonstrates German queries retrieving English documents over "mixed-language document collections" using `multilingual-e5-base`. | All of it. You upload the model, build the inference ingest pipeline, define `dense_vector` fields, and issue the kNN query. The capability is E5's, not the platform's. |
| [Azure AI Search](https://docs.azure.cn/en-us/search/search-language-support) | N | N | N | ~ | Documented pattern is manual: "Create a blended index with language-specific versions of each field (for example, description_en, description_fr, description_ko)", one analyzer per field, constrain with `searchFields`, bias with scoring profiles. | Everything cross-lingual. The doc concedes the hinge of your design is missing: "Sometimes the language of the agent issuing a query isn't known", with no mechanism to determine it. |
| [Vespa](https://docs.vespa.ai/en/linguistics.html) | **N (disclaimed)** | N | N | ~ | Stores multiple languages in one schema. Vendor states in writing: "Vespa supports having documents in multiple languages in the same schema, but does not out-of-the-box support cross-lingual retrieval." Also: "Vespa does _not_ know the language of a document." | All of it. Independently useful signal for your script gate: with the 0.02 confidence cutoff, "queries with 3 terms or fewer will default to English" — vendor confirmation that short-query language detection is unreliable. |
| [Weaviate](https://docs.weaviate.io/weaviate/model-providers/cohere/embeddings) | ~ | N | N | N | Gets cross-lingual retrieval **by accident**: "The server default is `embed-multilingual-v3.0`" for the Cohere vectorizer, so a stock setup is multilingual without the docs saying so. Hybrid-search docs contain no language parameter, no LID, no cross-lingual guidance. | Everything except the embedding space. Multi-tenancy could shard by language but the docs never present that as a multilingual pattern. |
| [LangChain](https://docs.langchain.com/oss/python/langchain/retrieval) | N | N | N | N | Nothing. The current retrieval documentation names only generic "query enhancement" (rewriting, multiple variations, expansion) and mentions multilingual, cross-lingual and translation nowhere. | All five behaviours. The multi-query retriever can be repurposed to fan out into several languages, but that is your glue over a general primitive. Emptiest framework on this axis. |
| [LlamaIndex](https://huggingface.co/llamaindex/vdr-2b-multi-v1) | ~ | N | N | N | Split verdict. The **framework** ships no language handling (the node-postprocessor guide lists only `SimilarityPostprocessor`, `CohereRerank`, `TimeWeightedPostprocessor`). The **model** `vdr-2b-multi-v1` does advertise cross-lingual visual-document retrieval: "This allows for searching german documents with italian queries" — 5 languages, no Hindi, screenshots not text. | The whole pipeline. Nothing in the querying stack detects query language or constrains answer language. |
| [Vertex AI Search / Agent Search](https://docs.cloud.google.com/generative-ai-app-builder/docs/about-advanced-features) | N | N | N | N | Nothing on the advanced-features surface: no multilingual or cross-language search, no query-language setting, no answer-language setting. | Everything. Notable as a negative result — a managed RAG product from a company with world-class MT ships none of this. |
| [kapa.ai](https://docs.kapa.ai/) | N | N | N | N | 20+ connectors, agentic retrieval, widgets, Zendesk/Slack/Discord agents, analytics. No documented multilingual capability, no language detection, no answer-language setting; the per-feature multilingual page 404s. | Everything. Included deliberately: this is the exact product category (English docs, global askers) where answer-language matching is most obviously valuable, and even here it is unshipped. |

**Blunt read:** exactly one framework ships behaviour 3 as a product feature (RAGFlow), and it
uses your mechanism. Exactly zero ship behaviour 4 or 5. Two ship the routing primitives for M
(Haystack, Elastic) and Haystack's default routing reproduces your bug.

---

## 2. Embedders — the retrieval layer (behaviour 3)

| Model | Languages | Evidence you can act on | Coverage |
|---|---|---|---|
| [BGE-M3 / M3-Embedding](https://huggingface.co/BAAI/bge-m3) ([paper](https://aclanthology.org/2024.findings-acl.137/)) | 100+, 8192 tokens | Dense+sparse+multi-vector in one model. MIRACL nDCG@10: dense 69.2, fused 71.5 vs mE5-large 66.6, OpenAI-3 54.9. On MKQA (25 languages against **one shared English corpus** — your exact case) R@100 75.5 vs mE5-large 70.9. In the [Sinhala/Tamil e-government head-to-head](https://arxiv.org/abs/2608.12820) it beat every query-translation pipeline with **no translation at all**: R@15 96.2% (Si-En) / 95.6% (Ta-En) vs Google Translate 92.4%/93.0%. | 3 = Y; 4,5 = N; M = **no** — [SHIFT](https://arxiv.org/abs/2606.18801) shows this model class strongly prefers query-language documents, and its reranker sibling concentrates >70% of top-5 in English + query language ([LAURA](https://arxiv.org/abs/2604.20199)). |
| [multilingual-e5-large / -large-instruct](https://huggingface.co/intfloat/multilingual-e5-large) ([paper](https://arxiv.org/abs/2402.05672)) | 100 (XLM-R set) | [MMTEB](https://arxiv.org/abs/2502.13595): `multilingual-e5-large-instruct` is "the best-performing publicly available model" at 560M params, and tops MTEB(Indic) (23 tasks, Borda 209 / avg 70.2). Two production traps: the card itself does **not** claim cross-lingual retrieval (that claim comes from Elastic/Haystack downstream), and it warns "low-resource languages may see performance degradation". Forgetting the mandatory `query: ` / `passage: ` prefixes silently degrades retrieval — a plausible confound in any weak-similarity gate. | 3 = Y; M = N |
| [jina-embeddings-v3](https://arxiv.org/abs/2409.10173) | 89, 8192 tokens | 570M backbone with **separate `retrieval.query` and `retrieval.passage` LoRA adapters** (<3% of params at rank 4). One index, one encoder, independently tunable query and passage sides — the cheapest architectural lever for a mixed-script corpus that does not duplicate the index. | 3 = Y; M = ~ |
| [Cohere embed-multilingual-v3.0](https://huggingface.co/CohereLabs/Cohere-embed-multilingual-v3.0) | 100+ | Managed API marketed explicitly for search *within* and *across* languages. Proof that cross-lingual retrieval is a commodity SKU, not research. Also Weaviate's server default. | 3 = Y; M = N |
| [LaBSE](https://arxiv.org/abs/2007.01852) | 109 | Tatoeba bitext retrieval 83.7% avg over 112 languages (prior SOTA 65.5). Optimised for **translation-pair mining**, not question→passage relevance — do not mistake bitext scores for retrieval scores. | 3 = ~ |
| [mContriever / Contriever](https://arxiv.org/abs/2112.09118) | multi | The founding claim, verbatim in the abstract: unsupervised models "can perform cross-lingual retrieval between different scripts, such as retrieving English documents from Arabic queries, which would not be possible with term matching methods." Standard baseline. | 3 = Y |
| [ColBERT-X / PLAID-X + Multilingual Translate-Distill](https://arxiv.org/abs/2405.00977) ([base](https://arxiv.org/abs/2201.08471), [Translate-Distill](https://arxiv.org/abs/2401.04810)) | XLM-R set | The strongest **model-side** answer to M: trained so relevance scores are *comparable across document languages*, producing one calibrated ranked list over a mixed collection. Beats Multilingual Translate-Train by 5–25% nDCG@20 / 15–45% MAP, and is robust to how languages are mixed **as long as every training mini-batch contains multiple languages**. Checkpoints on HuggingFace. | 3 = Y; **M = Y**; 4,5 = — |
| [NLLB-E5](https://aclanthology.org/2025.naacl-long.220/) ([paper](https://arxiv.org/abs/2409.05401)) | NLLB set, Hindi-focused | 48.57 avg nDCG@10 on Hindi-BEIR vs BGE-M3's 46.18. The architecture is the transferable idea: **frozen** NLLB encoder + **frozen** English E5 joined by one learnable linear projection, trained on English-only data with zero Hindi pairs. Bolts a language onto an English index without re-embedding the corpus. | 3 = Y (Hindi); M = ~ (no per-language cluster for a Hindi query to fall into) |
| [MuRIL](https://www.kaggle.com/models/google/muril) ([paper](https://arxiv.org/abs/2103.10730)) | 17 Indian + transliterated | Trained on translated **and transliterated** document pairs, so it uniquely covers romanized Hindi. But read the retrieval number as a warning, not an endorsement: Tatoeba cross-lingual **sentence retrieval 25.15** vs mBERT 18.41 — better than mBERT, catastrophic in absolute terms for a retriever. Its wins are classification-shaped (PANX NER 77.60, XNLI 74.07). | 3 = N as a retriever |
| [DeepRAG Hindi embedder](https://arxiv.org/abs/2503.08213) | Hindi only | **Do not adopt.** Claims +23% retrieval precision over multilingual models by training a Hindi-only space on 2.7M samples. Its entire value proposition is a space where a Hindi query and an English passage are *not* comparable — adopting it breaks behaviour 3 outright. | 3 = **anti** |
| [IndicIRSuite / Indic-ColBERT](https://github.com/saifulhaq95/IndicIRSuite) | 11 Indian | Eleven **separate monolingual** ColBERT models on translated MS MARCO (+47.47% MRR@10 over INDIC-MARCO baselines). Existence proof that per-language retrieval infrastructure for Indic already exists and is trained; the missing piece is only the routing/fusion layer. Never evaluates query/document language mismatch. | 3 = N; M = ~ (the multi-monolingual extreme, 11 indices to serve) |

---

## 3. Mixed-corpus fixes — the layer your open limit actually lives in

These are ordered cheapest-first. **None of them require the per-language sub-search
architecture you assumed you needed.**

| Artifact | Where it acts | Cost | Reported effect |
|---|---|---|---|
| [SHIFT](https://arxiv.org/abs/2606.18801) | **Index time only** | Training-free, zero query-time overhead | Estimate a relative language vector as the mean embedding difference over parallel pairs (533k mMARCO), subtract it from document embeddings at indexing; query embeddings untouched. `multilingual-e5-large` nDCG@20 0.633 → 0.737 avg over four benchmarks (Belebele 0.816→0.910, MLQA 0.494→0.649); Target-Languages Recall@20 0.540 → 0.694. Vectors are per **language pair**, so precompute once globally and apply to any tenant's index at ingest. |
| [LangSAE Editing](https://arxiv.org/abs/2601.04768) | Embedding post-hoc | Training-free; reconstructs to original dimensionality so **existing vector DBs keep working** | Sparse autoencoder over pooled `multilingual-e5-large` embeddings, suppress language-identity latents. Belebele nDCG@20 0.5359 → 0.6534 (+21.9%), R@20 +26.6%; XQuAD 0.7141 → 0.8613. Script-distinct case is dramatic: Chinese 0.3397 → 0.6947 (**+104.3%**). |
| [LIR](https://aclanthology.org/2021.emnlp-main.470/) | Embedding post-hoc | Matrix factorization + orthogonal projection, 2021 | The linear ancestor of the above: the *principal components* of a weakly-aligned multilingual space encode **language identity, not meaning**. ~100% relative MAP improvement on LAReQA for weak-alignment encoders. |
| [LAMAR](https://arxiv.org/abs/2607.22042) | Reranker (open cross-encoder) | Drop-in rerank stage | Your bug stated as a research result: existing multilingual rerankers put a **non-English document first 72.8% of the time** for English queries when equivalent documents exist across languages. LAMAR (bge-m3-retromae init; 6.7M-instance English-anchored distillation + 8.6K language-coherence preference pairs) hits nDCG@1 96.89 on XQuAD / 94.66 on BELEBELE for language coherence while staying competitive on MIRACL (69.5 vs 69.7 best). Shows query-language documents yield higher downstream QA F1. |
| [LAURA](https://arxiv.org/abs/2604.20199) | Reranker | Requires training on utility labels | Partition candidates by language, rank within each group for balanced exposure, then threshold on **downstream generative utility** rather than semantic relevance. Headroom quantified: Recall@3-gram 48.9 (BGE-Reranker-V2-M3) vs 63.6 oracle — ~15 points sitting in the candidate pool, downweighted not missing. Worst on exactly the non-Latin scripts you care about (ko 25.5/41.0, th 26.4/44.1, ja 29.2/47.9). Significant in 10 of 13 languages. |
| [Multilingual Translate-Distill](https://arxiv.org/abs/2405.00977) | Retriever training | Full training pipeline | Makes scores comparable across document languages so one index suffices. Recipe from the [TREC 2023 system](https://arxiv.org/abs/2404.08118): "A key to making MTT successful is to include documents from every target language in each batch." |
| [Balanced retrieval + dual-query merge](https://arxiv.org/abs/2507.07543) | Retrieval | ~4–6% overhead (BGE-M3), ~20% (M-E5) | The paper that *is* your open limit. Mixed Arabic-English corporate corpus; language-oracle ablation isolates the cause as document-document mismatch inside one index (M-E5 Hit@20 −42% Legal / −33% Travel). Two fixes: (a) take an equal number of passages from each language subset; (b) search the joint corpus **twice**, once with the original query and once with its translation, merge by inner-product score, take top-20. Both are free in same-language cases — "no statistically significant loss relative to the direct retriever". |
| [Weighted RRF per-language fusion](https://arxiv.org/abs/2607.22841) | Retrieval fusion | One extra sub-search | The constants, copyable: when a language has fewer than **τ=20** native exemplars, fuse the global cross-lingual index with the native shard by weighted RRF, **w_global=1.0, w_lang=2.0, k=60** — native shard trusted 2×. Hindi ran three-way RRF over global + English + Arabic proxy indices before earning a shard; final Hindi accuracy 73.5%. LangGraph + BGE-M3 + FAISS over a 30,209-entry KB. |
| [DELTA](https://arxiv.org/abs/2601.02956) | Query construction | One retrieval pass, **1.13 s/query** | Explicitly **rejects** per-language sub-search on cost. Fuses one query string from five ` | `-delimited segments — `[GLOB]` English pivot, `[LOCAL:xx]` original native query, `[TITLE_BRIDGE]`, `[ALIASES]`, `[LOCALE_HINT]` — weighted by literal repetition (r_local ∈ {1,2,3}, r_glob ∈ {1,2}) from an LLM culture-specificity confidence. 62.88 avg vs 58.81 English-pivot vs 51.30 MultiRAG vs 49.63 CrossRAG. Against English-pivot over 16,828 queries it newly recovers gold for 1,235 queries, because pivoting "degrades native surface-form anchors — titles, aliases, and original scripts". No gain when the query is already English. |

**Warning before you build fusion.** [Savoy & Berger (CLEF 2004)](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf)
measured merge strategies head to head over EN/FR/FI/RU: raw-score merging **collapses −73% MAP**
when the per-language runs use different engines, but gains +30% when they share one; logistic
regression on ln(rank)+RSV wins in all conditions (+28% to +44%); biased round-robin is a cheap
+10%. And [Lin & Chen (CLEF 2002)](https://ceur-ws.org/Vol-1168/CLEF2002wn-adhoc-LinEt2002.pdf)
found the **centralized single mixed index beat every merge strategy** (0.0398 MAP vs 0.0381
raw-score, 0.0224 round-robin) — while attributing the win to an idf artifact: pooling raises N
without raising term occurrences, so "it makes retrieval result preferring documents in small
document collection." A 3-file Hindi shard will exhibit exactly that pathology.

---

## 4. Translators (if you keep a translation hop)

| Tool | What it gives you |
|---|---|
| [IndicTrans2](https://github.com/AI4Bharat/IndicTrans2) | Open models for all 22 scheduled Indian languages, both directions with English. The direct replacement for an LLM translation call on the critical path. |
| NLLB-200 / NLLB-200-distilled-600M | Used as the outbound translator in the [Bengali agricultural pipeline](https://arxiv.org/abs/2601.02065) and as the document translator in [CroSearch-R1](https://arxiv.org/abs/2604.25182). Note [AfriQA](https://arxiv.org/abs/2305.06897): NLLB-based XOR-Full F1 ~16.3% vs ~23.0% with Google Translate — MT engine quality is not fungible. |
| Helsinki-NLP `opus-mt-*` / `marian-mt-bbc` | The inbound query translators in the two closest published product clones ([Bengali advisory](https://arxiv.org/abs/2601.02065), [prosthetic manuals](https://arxiv.org/abs/2506.23958)). Cheap, local, per-pair. |
| [PSQ reference implementation](https://arxiv.org/abs/2404.18797) | Open-source Python + unpruned translation tables. Never commits to one translation of a term — weights document-language terms by a full translation-probability matrix. Still beats both QT-BM25 and DT-BM25 in 2024 (MAP 0.332 vs 0.267 / 0.302; R@100 0.585 vs 0.477 / 0.546 over 456 topics). Moves translation to **indexing time**. |
| [Bhashini](https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2093333&reg=48&lang=2) | Indian government MT/ASR/TTS APIs for 22 languages, deployed across government portals. A translation substrate, not a retrieval or RAG system — it is document translation applied nationally. |

**The 1999 result you should not re-derive:** [McCarley](https://aclanthology.org/P99-1027/)
trained MT in both directions on the same data and found late fusion of query translation and
document translation beats either alone, and beats even a *perfect* query translation
(TREC-7 avg precision: qt 0.3296, dt 0.3345, qt+dt 0.3532; human-translated query 0.3611 but
ht+dt **0.4021**). The [CLIR survey](https://arxiv.org/abs/2111.05988) §2.1 states the
architecture rule outright: query translation wins when there are many query languages and one
document language; document translation wins when there is one query language and many
document languages — "space efficiency argues for indexing in the one query language."
Your single-language tenants are case one; your **mixed-corpus tenants are case two**.

---

## 5. Language detection (the gate's input)

| Tool | Coverage | Numbers |
|---|---|---|
| [GlotLID](https://github.com/cisnlp/GlotLID) | 2,000+ labels | fastText-based; the only thing here that covers a 40-language product surface with headroom. |
| [IndicLID / Bhasha-Abhijnaanam](https://ai4bharat.iitm.ac.in/indiclid) ([paper](https://aclanthology.org/2023.acl-short.71/)) | 22 Indian, native **and romanized** | The asymmetry is the whole story for a script gate: **98.55% accuracy on native script** (vs NLLB 98.78%, CLD3 98.03%, while ~10× faster and ~4× smaller) but only **80.40% on romanized**. First LID for romanized Indian text. |
| `lingua` | — | The detector [XRAG](https://arxiv.org/abs/2505.10089) uses to compute Response Language Correctness. |
| OpenLID | — | The detector [Ranaldi et al.](https://arxiv.org/abs/2504.03616) use for "percentage of answers generated in the correct language". |
| Elastic `lang_ident_model_1` | — | Runs in an ingest pipeline; Elastic recommends it for **documents**, not queries. |
| `langdetect-haystack` | defaults to `en` only | Haystack's classifier tags everything else `unmatched` unless you enumerate languages. |

**Two hard constraints on a Unicode script gate.** (a) It is blind to romanized input —
`mera order kahan hai` is Latin script, so both gates stay shut; [Script Gap](https://arxiv.org/abs/2512.10780)
measures up to **24 points** of LLM degradation from romanization across five Indian languages
plus Nepali, and [Lost in Transliteration](https://arxiv.org/abs/2505.08411) shows BGE-M3 losing
**97% of MRR@10** on Latinized Chinese (0.2342 → 0.0078) and 49% on Latinized Russian.
(b) Whole-response LID passes a code-switched answer — and code-switching in non-Latin scripts
is a documented residual failure even after prompt fixes
([Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/)), while
[CS-MTEB](https://arxiv.org/abs/2604.17632) shows code-switching costing robust multilingual
retrievers up to **27%** (e5-large-v2 Japanese reranking 60.17 → 25.75), with vocabulary
expansion insufficient. Counterpoint worth testing before "fixing" it:
[MiLQ](https://arxiv.org/abs/2505.16631) finds mixed-language queries retrieve **English**
documents far better than native-script ones (BM25 MAP@100 38.35 vs 12.35 low-resource,
34.92 vs 8.56 high-resource) — Hinglish input may already be helping you reach the English half.

---

## 6. Generation-language control (behaviours 4 and 5)

| Mechanism | Needs | Reported effect |
|---|---|---|
| **Prompt-side recipe** — [Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/) | Nothing; API-safe | Command-R-35B answered in English for **~50%** of non-English queries with a default English prompt over English Wikipedia. Translating the prompt into the user's language **plus** an explicit "generate the response in the user language" instruction raises Correct Language Rate to **>95%** in most cases. Named-entity code-switching persists in non-Latin scripts. |
| **Explicit pin string** — [QTT-RAG](https://arxiv.org/abs/2510.23070), [HEALTH-PARIKSHA](https://arxiv.org/abs/2410.13671) | Nothing | The two published verbatim policy strings: "respond only in {query language}" and "The provided query is in {query_lang}, and you must always respond in {response_lang}." |
| [Soft Constrained Decoding (SCD)](https://github.com/WisdomShell/SCD) ([paper](https://arxiv.org/abs/2511.09984)) | **Logit access** | Training-free penalty on non-target-language tokens. With English context: ZH 68.4→90.6, RU 80.2→95.4, AR 85.4→96.4 language consistency, with ROUGE rising alongside (ZH 0.182→0.306). Baseline context matters: swapping retrieved context Chinese→English alone drops consistency 92.0%→68.4%. |
| [Language Confusion Gate (LCG)](https://arxiv.org/abs/2510.17555) | Logit access | The stat that makes this cheap: at confusion points the language-consistent token is already in the **top-3 predictions 99.29%** of the time. Qwen3-8B FLORES Latin confusion 12.1%→2.0%, CJK 4.5%→0.1%; HumanEval-XL pass@1 80.56→79.44. Intervenes only when needed and tolerates legitimate code-switching. |
| [LATB / Adaptive-LATB](https://arxiv.org/abs/2606.08994) | Logit access | Decode-time only. Llama3-8B-Instruct on XLSum: Russian response-level confusion 92.50% → **0.10%**, Chinese 98.90% → 0.00%, ROUGE maintained. |
| [ReCoVeR](https://arxiv.org/abs/2509.14814) | Activation access | Steering vectors from multi-parallel corpora. The win is **cross-lingual**, not monolingual: Gemma-2 70.4% → 96.2% correct answer language; multilingual MMLU within 0.4 points of baseline. |
| [ITLC](https://arxiv.org/abs/2506.12450) | Activation access | Single middle-layer injection (LDA projection, k=100). ~26.7% average cross-lingual improvement; 85.65% on LCB vs ReCoVeR's 90.29%, at substantially lower compute. Mechanism: Qwen2.5 cross-lingual representation similarity is **0.922 at middle layers, 0.375 at the last**. |
| **Model choice alone** — [Language Confusion Benchmark](https://aclanthology.org/2024.emnlp-main.380/) | Nothing | Moves this ~60 points. Cross-lingual line-level pass rate: Llama 3 70B-Instruct **30.3%**, Llama 2 70B-Instruct 38.4%, GPT-4o 92.4%, Command R+ Refresh **95.4%**. Confusion worsens with longer prompts and higher temperature; beam search consistently hurts. |

**Prompting alone is not sufficient, and this is measured.**
[Qi et al.](https://arxiv.org/abs/2504.00597) find **24.85%** of Arabic queries answered
*correctly but in the wrong language* despite an explicit "Please respond in Arabic" instruction
— and neither a two-step answer-then-translate prompt nor larger models (Gemma3-27B-IT,
GPT-5-nano) fixed it: "the problem persists ... an inherent decoding limitation." Their summary:
"the query language is much more predictive of accuracy than the passage language, suggesting
that generating in the target language is the major bottleneck."

---

## 7. Evaluation harnesses

| Harness | Covers | Why you would run it |
|---|---|---|
| [XOR-TyDi / XOR-Full](https://github.com/AkariAsai/XORQA) ([paper](https://aclanthology.org/2021.naacl-main.46/)) | 1–4 | The canonical task definition of your product, since 2021. 40k questions in 7 languages **selected because no same-language answer exists**. Makes any rank-1 claim comparable to published numbers. Note: its own MT-pipeline baseline (translate question → DPR over English → generate → translate back) scores 18.7 F1 / 12.1 EM. Retrieval-only R@5kt: human-translated queries 72.1, Google MT 67.2, in-house MT **50.0**. |
| [XRAG](https://github.com/amazon-science/XRAG) ([paper](https://arxiv.org/abs/2505.10089)) | 1–4, **incl. answer language** | The only benchmark that scores **Response Language Correctness** as a first-class metric, and it ships both a monolingual-English-corpus condition and a **mixed English+query-language** condition — a ready-made harness for your open limit. ~1,000 verified QA pairs per language pair, EN/DE/ES/ZH/AR, News Crawl Jun–Nov 2024. Wrong-language answer rates: ~5% GPT-4o and Command-R+, ~15% Claude 3.5 Sonnet, ~35% Mistral-large. GPT-4o scores 6.3% without retrieval vs 85% human, so the questions genuinely need the corpus. |
| [LAReQA](https://arxiv.org/abs/2004.05484) ([paper](https://aclanthology.org/2020.emnlp-main.477/)) | M | Retrieval from a **mixed-language candidate pool**, since 2020. Its distinction is the one that explains your bug: *weak* alignment (nearest neighbour in another language is right) vs *strong* alignment (cross-language pairs must beat unrelated same-language pairs). Read the warning: training on translated data with monolingual positives (X-X, mAP 0.23) is **worse** than English-only training (0.29); only X-Y (0.66), which forces the model to accept a foreign-language answer, fixes it. |
| [MLAIRE](https://arxiv.org/abs/2605.07249) | Diagnostic for M | Purpose-built for "users issue queries over mixed-language corpora". Introduces Language Preference Rate and Lang-nDCG. The result that indicts single-script measurement: semantic quality and query-language preference are near-orthogonal and often anti-correlated (nDCG↔LPR Pearson −0.28 MLQA, −0.38 XQuAD, −0.29 Belebele across 31 retrievers) — mE5-large 96.15% nDCG @ 99.92% LPR vs Qwen3-Embedding-8B 68.64% @ 53.00%. |
| [MIRAGE-Bench](https://github.com/vectara/mirage-bench) ([paper](https://arxiv.org/abs/2410.13716)) | 4 | 18 languages incl. Hindi. Its surrogate judge (random forest over 7 heuristics including a **langid probability that the response is in the target language** plus a separate English-detection feature) reproduces GPT-4o pairwise preferences at **Kendall τ = 0.909** — rank generation quality without paying for an LLM judge every run. Retrieval is per-language Wikipedia, so it does not exercise M. |
| [NoMIRACL](https://github.com/project-miracl/nomiracl) ([paper](https://arxiv.org/abs/2312.11361)) | The gate | 18 languages, 31 native annotators. Measures whether the system admits nothing is relevant. LLaMA-2 and Orca-2 exceed **88% hallucination rate** on the non-relevant subset; the low-hallucination models swing to a **74.9% error rate** on the relevant subset. This is the instrument for your weak-similarity gate. |
| [BERGEN](https://github.com/naver/bergen) | 1–3 | The only general-purpose open-source RAG eval library with first-class multilingual support (20+ retrievers, 4 rerankers, 20+ LLMs) including the query-language-vs-datastore-language axis. Ships **no** answer-language metric — its companion paper handles correct-language generation by prompt engineering, not measurement. |
| [RAGAS](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/) | 3 only | Faithfulness, context precision/recall, noise sensitivity, factual correctness, BLEU/ROUGE. The official available-metrics page documents **no** language-consistency metric and no answer-language detection. The most-used RAG eval library cannot score behaviour 4 out of the box. |
| [MEMERAG](https://arxiv.org/abs/2502.17163) | Judge validation | 1,250 native questions in EN/DE/ES/FR/**HI**, 2,322 expert-annotated sentences. Proves human sentence-level grounding annotation is reliable with guidelines (faithfulness Gwet's AC1 0.84–0.93 vs 0.34–0.42 κ in prior work) and that **the best LLM judge differs by language** (GPT-4o mini best in English, Qwen 2.5 32B elsewhere; guidelines + CoT beats zero-shot). Does not measure answer language. |
| [XOR-AttriQA](https://arxiv.org/abs/2305.14332) | Grounding across the language boundary | The number rank-1 retrieval cannot see: up to **~47%** of cross-lingual answers that *exactly match gold* are not attributable to any retrieved passage (Japanese 53.1% attributable, Telugu 93.1%). Cheap fix: PaLM 2 fine-tuned on **~100** attribution examples reaches 92–96% accuracy / 95–98% ROC AUC. |
| [MMTEB / MTEB(Indic)](https://github.com/embeddings-benchmark/mteb) ([paper](https://arxiv.org/abs/2502.13595)) | Embedder audit | 500+ tasks, 250+ languages; MTEB(Indic) is a ready-made 23-task split. Use it **per language**, not in aggregate — [MTEB's founding result](https://arxiv.org/abs/2210.07316) is that no single embedding method dominates across tasks. |
| [Language Confusion Benchmark](https://github.com/for-ai/language-confusion) | 5 | Its two settings **are** your two policy modes: monolingual (match the query) and cross-lingual (obey an explicit language instruction), 15 languages, released code. |
| [NeuCLIRBench](https://arxiv.org/abs/2511.14758) / [TREC NeuCLIR](https://arxiv.org/abs/2509.14355) / [RAGTIME](https://arxiv.org/abs/2602.10024) | 3, M | TREC-grade pooled judgments for the mixed-index case. NeuCLIRBench: 250,128 judgments, and it ships **a fusion baseline of strong neural retrievers** so rerankers need not start from BM25 — the community's own reference first stage for cross-lingual retrieval is a fusion, not one index. NeuCLIR 2024 MLIR: one unified list over ~2M fa + ~3M zh + ~5M ru, best nDCG@20 **0.545** vs 0.664/0.698/0.593 for the single-language CLIR tasks. RAGTIME requires **English** output, so neither measures behaviour 4. |
| [AfriQA](https://github.com/masakhane-io/afriqa) | 1–4, hard end | The reality check on 40-language claims. Pure cross-lingual mDPR: **19.0% R@10**. Google-Translate query translation: 62.4%. Human question translation: 67.6%. Hybrid sparse+dense with human translation: 73.4%. Best end-to-end XOR-Full F1 **~23.0%**. |
| [IndicGenBench / XorQA-In-Xx](https://github.com/google-research-datasets/indic-gen-bench) ([paper](https://arxiv.org/abs/2404.16816)) | 2, 4 | Exactly (Indic question, English passage, Indic answer), 28 languages, 32k examples — but **gold passages are supplied**, so there is no retrieval. Hardest task in the benchmark: PaLM-2-L reaches only **37.4 Token-F1** one-shot. |
| [DoGMaTiQ](https://arxiv.org/abs/2605.04458) | Automating grounding | QA-shaped nuggets that "decouple the information need (i.e. the question) from the potentially diverse content that satisfies it" — the only grading form that survives a Hindi answer that can never lexically match its English source. Validated on NeuCLIR and RAGTIME. |

**Missing from every harness above:** a Hindi-question-over-English-corpus benchmark that
actually requires retrieval. XOR-TyDi's Indic coverage is Bengali and Telugu only; IndicGenBench
supplies gold passages; [IndicRAGSuite](https://arxiv.org/abs/2506.01615) is explicitly
monolingual ("IndicMSMARCO supports monolingual retrieval"); [Hindi-BEIR](https://arxiv.org/abs/2408.09437)
is monolingual Hindi; [HEALTH-PARIKSHA](https://arxiv.org/abs/2410.13671) has the right setup
(English-only KB, Indic queries, explicit policy string) but only **19 Hindi pairs of 749**.

---

## 8. Research artifacts with code (adopt the architecture, not always the weights)

| Artifact | 3 | 4 | 5 | M | Note |
|---|---|---|---|---|---|
| [CORA (mDPR + mGEN)](https://github.com/AkariAsai/CORA) ([paper](https://arxiv.org/abs/2107.11976)) | Y | Y | N | Y | Covers 1–4 end to end since 2021, 26 languages incl. 9 unseen, and "answers directly in the target language without any translation or in-language retrieval modules as used in prior work". +23.4 F1 XOR-TyDi, +4.7 MKQA. A 2021 research checkpoint, not a service — adopt the argument that the translation hop is removable. Superseded by [CLASS](https://aclanthology.org/2024.emnlp-main.770/) (XOR-Full 42.4 F1 vs CORA 34.7, single encoder-decoder, no MT). |
| [DKM-RAG / LanguagePreference](https://github.com/jeonghyunpark2002/LanguagePreference) ([paper](https://arxiv.org/abs/2502.11175)) | Y | Y | N | Y | Translates the **reranked passages** into the query language and fuses them with LLM-rewritten parametric knowledge. Korean 40.60 (standard multilingual) → 55.01; Chinese 32.55 → 44.57. Both halves needed (ablation: −5.4 without model knowledge, −8.9 without translated passages). Ships **MLRS**, which scores retriever language preference by how much a document's rank improves when translated into the query language — a directly reusable diagnostic for your bug. |
| [CrossRAG / tRAG / MultiRAG](https://arxiv.org/abs/2504.03616) ([published](https://aclanthology.org/2026.findings-eacl.35/)) | Y | Y | ~ | Y | The taxonomy your design sits in. **tRAG is your mechanism** (translate the question, retrieve, answer in query language) and it places last: GPT-4o MKQA flexible-EM no-RAG ~43 → tRAG 46.5 → monoRAG 51.5 → MultiRAG 53.1 → **CrossRAG 60.4**. CrossRAG also generates in the correct language more consistently than MultiRAG (measured with OpenLID). Cost: CrossRAG translates every retrieved document on every query. |
| [QTT-RAG](https://arxiv.org/abs/2510.23070) | Y | Y | Y | Y | Translates foreign-language retrieved docs, scores each on semantic equivalence / grammatical accuracy / naturalness (0.0–5.0), attaches scores as **metadata without rewriting content**, pins the answer language in the prompt. Gains are modest and language-dependent (Korean XOR-TyDi 43.8 vs CrossRAG 42.0; near-flat on Chinese, because only 5% of Chinese retrievals were cross-lingual vs 22.7% for Korean). |
| [Bengali agricultural advisory](https://arxiv.org/abs/2601.02065) | Y | Y | N | N | The commodity stack, fully named: `all-MiniLM-L6-v2` + FAISS over English FAO/IRRI manuals, `opus-mt-bn-en` inbound, NLLB-200 outbound, 4-bit Llama-3-8B, **~15.6 s end-to-end on one Tesla T4**. That is the honest latency of an unconditioned translate-in/translate-out pipeline. |
| [Prosthetic manuals RAG](https://arxiv.org/abs/2506.23958) ([repo](https://github.com/Iykay/User-Manual-LLM)) | Y | Y | N | N | Your product story verbatim: upload English manuals, ask in your native language, get a localised answer. `marian-mt-bbc` pcm→en, `multi-qa-mpnet-base-dot-v1` + FAISS, FLAN-T5-large, marian-mt en→pcm. |
| [CORAL](https://arxiv.org/abs/2604.25676) | Y | ~ | N | Y | The published analogue of your gates: retrieve → critique evidence for relevance/cultural alignment → check sufficiency → **reselect corpora and rewrite the query** on failure. Maintains separate per-language Wikipedia indexes with query-conditioned corpus selection; +3.58pp over the best of monoRAG/tRAG/multiRAG/crossRAG on BLEnD low-resource. Gate is an LLM critic, not a threshold. |
| [Syfer](https://arxiv.org/abs/2608.13160) | Y | Y | N | ~ | The published **threshold** gate: the English pathway fires only when `cos(e(q_filled), e(Q)) < τ`, τ = 0.8. +8.91 F1 (+29.8% rel.) on MuSiQue over the strongest decomposition baseline. |
| [CroSearch-R1](https://arxiv.org/abs/2604.25182) | Y | Y | ~ | Y | Multi-turn retrieval that **prioritises the query-language collection on turn one, then expands to other-language collections** — per-language sub-search with routing, as an RL policy. mE5 + NLLB-200-distilled-600M + Qwen2.5-7B, GRPO. MKQA fEM avg 45.92 vs Search-R1 42.82. |

---

## 9. "A blog post shows you how" vs "the framework provides it"

Be precise about this, because it decides your build list.

**Genuinely provided, as a feature, by something you can install:**
- Cross-lingual retrieval from an embedding model: BGE-M3, mE5, jina-v3, Cohere. Real, commodity.
- Query-translation-before-retrieval as a product toggle: [RAGFlow only](https://ragflow.io/docs/glossary).
- Document/query language classification and routing components: [Haystack](https://haystack.deepset.ai/tutorials/32_classifying_documents_and_queries_by_language) and [Elastic](https://www.elastic.co/blog/multilingual-search-using-language-identification-in-elasticsearch) — both pointed at same-language routing.
- Cross-language-comparable scoring in one index: [ColBERT-X + MTD](https://arxiv.org/abs/2405.00977), with checkpoints.
- A language-coherent reranker: [LAMAR](https://arxiv.org/abs/2607.22042), openly released.

**Only a recipe — the framework supplies nothing:**
- Answer-language matching. Every real instance is a hardcoded prompt string; [Haystack's cookbook](https://haystack.deepset.ai/cookbook/multilingual_rag_podcast) writes "answer the question using English" literally into the template, with nothing detecting the query language to feed it.
- Cross-lingual retrieval on Elastic — [the tutorial](https://www.elastic.co/search-labs/tutorials/examples/multilingual-model-semantic-search-elasticsearch) has you upload E5, build the ingest pipeline, define the `dense_vector` field and write the kNN query. The capability is the model's.
- Mixed-language corpora on Azure — ["Create a blended index with language-specific versions of each field"](https://docs.azure.cn/en-us/search/search-language-support) is instructions, not a feature.

**Explicitly absent, and the vendor says so:**
- [Vespa](https://docs.vespa.ai/en/linguistics.html): "does not out-of-the-box support cross-lingual retrieval", and "Vespa does _not_ know the language of a document."
- [Azure](https://docs.azure.cn/en-us/search/search-language-support): no mechanism to determine the query's language.
- [LangChain](https://docs.langchain.com/oss/python/langchain/retrieval), [Vertex AI Search](https://docs.cloud.google.com/generative-ai-app-builder/docs/about-advanced-features), [kapa.ai](https://docs.kapa.ai/): nothing on any of the five behaviours.
- [RAGAS](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/): no language metric of any kind.

**Nobody ships behaviour 5.** No framework, no vector DB, no managed RAG product examined here
exposes "pin the answer language" or "match the query language" as a setting. It exists in the
research only as a fixed task property ([XOR-Full](https://aclanthology.org/2021.naacl-main.46/)),
a dataset split ([IndicGenBench](https://arxiv.org/abs/2404.16816)), a forced constant
([BordIRLines](https://arxiv.org/abs/2410.01171): "your answers should always be primarily in
English"), or an eval condition ([LCB](https://github.com/for-ai/language-confusion)). This is
your defensible product surface — and it is packaging, not science.

---

## 10. Build vs adopt, per layer

### Embedder — **ADOPT**, and test it against your translation path first
Take BGE-M3 or `multilingual-e5-large-instruct`. Do not build. Before anything else, run the
null hypothesis: the untranslated multilingual encoder against your current gated pipeline on
[XOR-Retrieve](https://github.com/AkariAsai/XORQA). Evidence it may win outright:
[BGE-M3 beat every query-translation pipeline](https://arxiv.org/abs/2608.12820) on
Sinhala/Tamil→English (96.2%/95.6% R@15 vs 92.4%/93.0%); on
[CLIRudit](https://arxiv.org/abs/2504.16264) NV-Embed-v2 scored 0.580 MAP untranslated vs 0.600
with *gold human* translation and query translation actively **degraded** several dense models
(BGE-m-gemma2 0.571 → 0.533), the failure mode being mistranslated proper nouns;
[Anveshana](https://arxiv.org/abs/2505.19494) is the counterexample — on a low-resource script
DT+BM25 hits 62.46 nDCG@10 while direct multilingual-e5-base gets 10.74, so this is
corpus-dependent, which is exactly why you measure. Audit per-language on
[MTEB(Indic)](https://arxiv.org/abs/2502.13595) rather than trusting an average, and never adopt
a language-specific embedder like [DeepRAG](https://arxiv.org/abs/2503.08213) — it optimises a
space in which behaviour 3 is impossible.

### Translator — **ADOPT, and move it off the critical path**
Replace the LLM translation call with [IndicTrans2](https://github.com/AI4Bharat/IndicTrans2)
or NLLB-200-distilled-600M for covered languages; keep the LLM only for the tail. MT quality is
load-bearing, not incidental: XOR-Retrieve R@5kt runs 72.1 (human) / 67.2 (Google MT) / **50.0**
(in-house MT); AfriQA runs 62.4% (Google) vs 16.3% F1 with NLLB end-to-end. If you keep a
translation strategy at all, prefer **document translation at index time** for mixed-corpus
tenants ([survey §2.1](https://arxiv.org/abs/2111.05988): documents give a translator context
that a short query cannot), and consider [PSQ](https://arxiv.org/abs/2404.18797) over one-best
translation — the 2003 result is that one-best throws away probability mass, and the
[2024 revisit](https://arxiv.org/abs/2404.18797) still has PSQ-HMM at 0.332 MAP over QT-BM25's
0.267. Do not build an MT model.

### Language detection — **ADOPT, and stop gating on script alone**
Bolt [GlotLID](https://github.com/cisnlp/GlotLID) (2,000+ labels) as the general detector and
[IndicLID](https://ai4bharat.iitm.ac.in/indiclid) as the Latin-script second stage. A Unicode
block regex cannot see romanized Hindi; IndicLID is 98.55% on native script but **80.40%**
romanized, so treat the romanized branch as low-confidence by construction. Take Elastic's and
Vespa's warnings seriously for short queries — prefer user locale/tenant configuration as the
primary signal and detection as the fallback, not the reverse. Score answer-language at
**sentence level**, since whole-response LID passes a code-switched answer.

### Routing — **DO NOT BUILD YET**
Three published results argue your instinct to route may be backwards.
[Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/) ablated English-only vs
user-language-only vs **concatenated** multilingual Wikipedia across 13 languages and found the
single concatenated index beneficial in most cases with one BGE-M3 retriever.
[BordIRLines](https://arxiv.org/abs/2410.01171) found multilingual retrieval beats purely
in-language retrieval on both consistency (Command-R 64.2 → 78.7) and geopolitical bias
(28.7 → 5.9) across 49 languages. [MultiRAG beats monoRAG](https://arxiv.org/abs/2504.03616)
(53.1 vs 51.5 flexible-EM). Order of work: (1) single mixed BGE-M3 index as the baseline;
(2) [SHIFT](https://arxiv.org/abs/2606.18801) index-side language-vector subtraction — training-
free, zero query-time cost, vectors precomputed once per language pair; (3) only if both fail,
the [dual-query merge](https://arxiv.org/abs/2507.07543) (search the joint corpus twice, merge
by score) which is the cheapest of the routing family at ~4–6% overhead on BGE-M3;
(4) full per-language shards with [DS@GT's weighted RRF](https://arxiv.org/abs/2607.22841)
constants last. If you reach (4), use one retriever across all shards — Savoy's **−73% MAP**
raw-score collapse happens precisely when per-language runs use different engines — and watch
the idf pathology [Lin & Chen](https://ceur-ws.org/Vol-1168/CLEF2002wn-adhoc-LinEt2002.pdf)
documented for tiny sub-collections.

### Reranking — **ADOPT, and treat it as the mixed-corpus fix**
Add [LAMAR](https://arxiv.org/abs/2607.22042) as an explicit language-aware rerank stage. Do not
assume a stock reranker is neutral: the BGE reranker puts **>70% of top-5 from English + the
query language** ([LAURA](https://arxiv.org/abs/2604.20199)), and multilingual rerankers put a
non-English document first **72.8%** of the time for English queries when equivalent documents
exist (LAMAR). Reranking is also where the largest cross-script jumps come from at all — cross-
encoder reranking took CLIRMatrix en-zh from 0.0 to 30.0 and mMARCO en-zh from 0.0 to 91.0
([What Drives Cross-lingual Ranking](https://arxiv.org/abs/2511.19324)). Retrieve wide
(top-50), rerank narrow (top-5), which is the pipeline shape LAURA and DELTA both assume.

### Generation-language control — **ADOPT the mechanism, BUILD the policy object**
If API-only: adopt the [Chirkova recipe](https://aclanthology.org/2024.knowllm-1.15/) — prompt
translated into the user's language **plus** an explicit generate-in-user-language instruction,
which is the difference between ~50% and >95% Correct Language Rate — and pick a generator that
is not catastrophic on this axis (LCB cross-lingual pass rate spans 30.3% to 95.4%). If you
self-host, add [SCD](https://github.com/WisdomShell/SCD) or [LCG](https://arxiv.org/abs/2510.17555)
at decode time; both are training-free and LCG's top-3 statistic (99.29%) means the fix is a
mask, not a model. **Build** the policy object itself — tenant default, per-query override,
detected-query-language fallback, and the precedence rules between them — because no framework
or product examined ships it. Do not rely on prompting alone as a guarantee: it demonstrably
fails 24.85% of the time on Arabic ([Qi et al.](https://arxiv.org/abs/2504.00597)).

### Evaluation — **ADOPT the harnesses, BUILD the language metric and the mixed-corpus set**
Replace the bespoke 80-query set. Run [XOR-Retrieve / XOR-Full](https://github.com/AkariAsai/XORQA)
for comparability, [XRAG](https://github.com/amazon-science/XRAG) for response-language
correctness **and** its mixed-corpus condition, [LAReQA](https://arxiv.org/abs/2004.05484) for
the mixed pool, [MLAIRE](https://arxiv.org/abs/2605.07249)'s LPR alongside nDCG so semantic
skill and language preference are separable, [NoMIRACL](https://github.com/project-miracl/nomiracl)
for the gate's abstention behaviour, and [MIRAGE-Bench](https://github.com/vectara/mirage-bench)'s
surrogate judge (τ = 0.909) to avoid paying for an LLM judge every run. Validate that judge in
Hindi specifically before trusting it — [MEMERAG](https://arxiv.org/abs/2502.17163) shows the
best judge differs by language. **Build** the language-consistency metric yourself; RAGAS ships
none and BERGEN ships none. Also build the missing dataset if you want an external claim: a
Hindi-question / English-corpus set that requires actual retrieval does not exist. And track
attribution, not just rank@1 — [XOR-AttriQA](https://arxiv.org/abs/2305.14332) found up to ~47%
of exactly-correct cross-lingual answers unattributable, with a ~100-example classifier as the
cheap guard. Expect a further ~10–13 point reasoning penalty from the language mix alone,
independent of retrieval ([Chua et al.](https://arxiv.org/abs/2406.16135): GPT-4 81.82 → 68.61
on mixup-translated MMLU) — which is evidence *for* keeping the original question in the
generation prompt rather than the translated one.
