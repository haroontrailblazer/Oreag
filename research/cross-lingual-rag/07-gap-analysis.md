# 07 — Gap Analysis: the verdict

**Question asked:** does a framework/research line exist for RAG where the corpus language and the
question language differ — retrieve semantically from a language-A corpus with a language-B question,
answer in language B, with explicit answer-language policy?

**Answer: yes, comprehensively, and it has had a name since 2021.** The belief that nothing like this
exists is false at every layer. Worse for the novelty claim: Oreag's specific mechanism — embed an LLM
translation of the question, keep the original question for generation — is already named in the
standard taxonomy as **tRAG**, and in the head-to-head that named it, tRAG is the *worst* of four
strategies. And the "known open limit" (mixed-script corpus) is the single most crowded sub-problem in
the field: it is called **MLIR**, it has a TREC task, a 250k-judgment test collection, a dedicated
evaluation protocol, and at least seven published fixes — including one paper that states Oreag's setup
verbatim and evaluates both of the repairs Oreag identified as unbuilt.

Two things survive: the **gates** (conditional invocation on script presence + weak retrieval score) and
the **answer-language policy as a product control surface**. Neither is a research capability. Both are
defensible as engineering/product claims. Details below.

---

## 1. The three independent analyses

Three lenses were run over the same 176 verified papers and 120 frameworks. All three returned the same
top-level verdict. They diverge sharply on what to do next.

### Lens A — the skeptic

> "No — the framework exists, it has a name, a task definition, benchmarks, a TREC track, open-source
> implementations, and a free shipped product feature."

Core argument: the target behaviour was formalised as **XOR-Full** in NAACL 2021
([XOR QA](https://aclanthology.org/2021.naacl-main.46/), [arXiv:2010.11856](https://arxiv.org/abs/2010.11856))
and solved end-to-end *without any translation hop* by
[CORA](https://arxiv.org/abs/2107.11976) (NeurIPS 2021, 26 languages, 9 unseen). The XOR QA paper's own
strongest end-to-end baseline is Oreag's architecture — MT the question, DPR over English Wikipedia,
generate, translate back — at **18.7 F1 / 12.1 EM** against ~40 F1 for comparable monolingual English
systems ([source](https://aclanthology.org/2021.naacl-main.46/)).

The skeptic's sharpest points:
- The mechanism is prior art with a name and a loss record: **tRAG**
  ([arXiv:2504.03616](https://arxiv.org/abs/2504.03616) /
  [ACL Findings EACL 2026](https://aclanthology.org/2026.findings-eacl.35/)). GPT-4o flexible-EM on MKQA:
  no-RAG ~43 → tRAG 46.5 → monoRAG 51.5 → MultiRAG 53.1 → **CrossRAG 60.4**.
- It ships free: [RAGFlow](https://ragflow.io/docs/glossary) "Cross-language search" since v0.19.0
  (26 May 2025) does LLM query translation before matching.
- The script gate should probably be **scrapped, not fixed**, because the two studies that ablated it
  argue against it: [BordIRLines](https://arxiv.org/abs/2410.01171) finds multilingual retrieval beats
  purely in-language retrieval on consistency (Command-R 64.2 → 78.7) and geopolitical bias (28.7 → 5.9)
  across 49 languages; [Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/) find a
  *concatenated* multilingual corpus beneficial in most cases with a single BGE-m3 retriever.
- The 80/80 number is the weakest part of the claim, not the strongest.

### Lens B — the research advisor

Same verdict, but framed around what could be published. Adds:
- The gates ARE partially prior art. [Syfer](https://arxiv.org/abs/2608.13160) gates its English pathway
  on a single cosine threshold (fires only when cos(filled sub-question, original) < 0.8);
  [CORAL](https://arxiv.org/abs/2604.25676) gates on an LLM sufficiency critic;
  [Script Gap](https://arxiv.org/abs/2512.10780) proposes Uncertainty-based Selective Routing for Indic
  triage. Conditional invocation is a published design pattern; only Oreag's *signals* are unpublished.
- The most defensible open research item is a **per-query router over the published strategy space**
  (tRAG / monoRAG / MultiRAG / CrossRAG / DELTA / QTT-RAG). Precondition already proven twice and acted on
  by nobody: [arXiv:2507.22923](https://arxiv.org/abs/2507.22923) shows no universally best translation
  strategy (Qwen2.5-7B +6.6 on French, −12.8 on Hindi);
  [INDIC QA BENCHMARK](https://arxiv.org/abs/2407.13522) shows Llama-3 extractive F1 for Assamese at
  33.01 translated vs 21.29 direct, but Hindi at 46.76 direct vs 26.22 translated.
- A second real gap: **no Hindi/Indic cross-lingual RAG benchmark that requires retrieval**.
  [IndicGenBench XorQA-In-Xx](https://arxiv.org/abs/2404.16816) has the right task shape (Indic question,
  English passage, Indic answer, 28 languages, 32k examples) but *supplies the gold passage*.
  [IndicRAGSuite](https://arxiv.org/abs/2506.01615) is explicitly multi-monolingual.
  [HEALTH-PARIKSHA](https://arxiv.org/abs/2410.13671) has the exact setup but only 19 Hindi pairs of 749.
- Also says scrap the script gate, for the same reasons as Lens A.

### Lens C — the engineer

Same verdict, but the framing is "you are hand-building three things you should adopt." Adds the
production observations neither other lens leads with:

- **The 80/80 result is almost certainly a measurement artifact.** No published cross-lingual retrieval
  result is anywhere near 100% rank-1 across 40 languages, including on curated Wikipedia benchmarks:
  [AfriQA](https://arxiv.org/abs/2305.06897) best end-to-end XOR-Full F1 ~23%, pure cross-lingual mDPR
  19.0% R@10; XOR-Full SOTA is 42.4 F1 ([CLASS](https://aclanthology.org/2024.emnlp-main.770/));
  [IndicGenBench](https://arxiv.org/abs/2404.16816) XorQA-In-Xx tops out at 37.4 Token-F1 (PaLM-2-L, 28
  Indic languages); [MMed-Bench-IR](https://arxiv.org/abs/2606.24200) reports biomedical encoders at
  0.818 nDCG@10 English collapsing to 0.056 Japanese.
  [MLAIRE](https://arxiv.org/abs/2605.07249) exists precisely because standard metrics conflate
  cross-lingual semantic skill with query-language preference — on a single-script corpus those are
  indistinguishable by construction, which is exactly Oreag's test condition, and exactly why the mixed
  corpus broke.
- **Keep the gates.** Contra Lenses A and B, the engineer argues the gates are the right cost instinct:
  CrossRAG — the best-scoring published strategy — translates every retrieved document on every query
  (5 generation calls on the critical path at top-5), and the deployed unconditional pipeline
  ([Bengali agricultural advisory, arXiv:2601.02065](https://arxiv.org/abs/2601.02065)) averages ~15.6 s
  end-to-end on a T4. The fix is to move CrossRAG's insight to *index* time, not to abandon gating.
- **A second, larger hole in the gate: romanized and code-mixed input.** "mera order kahan hai" is Latin
  script; both gates stay shut. [IndicLID](https://aclanthology.org/2023.acl-short.71/) gets 98.55% on
  native script but only 80.40% romanized; [Script Gap](https://arxiv.org/abs/2512.10780) measures up to
  24 points of LLM degradation from romanization;
  [Lost in Transliteration](https://arxiv.org/abs/2505.08411) shows BGE-M3 losing 97% of MRR@10 on
  Latinized Chinese (0.2342 → 0.0078). Counterpoint worth testing first:
  [MiLQ](https://arxiv.org/abs/2505.16631) finds mixed-language queries retrieve English documents far
  *better* than native-script ones (BM25 MAP@100 38.35 vs 12.35 low-resource).
- **Grounding across the language boundary is unmeasured in Oreag's stack.**
  [XOR-AttriQA](https://arxiv.org/abs/2305.14332): up to ~47% of cross-lingual answers that exactly match
  gold are not attributable to any retrieved passage (Japanese 53.1% attributable, Telugu 93.1%). Rank-1
  retrieval plus a plausible answer proves nothing.

### Where they agree

| Point | A | B | C |
|---|---|---|---|
| The framework exists; belief is false | yes | yes | yes |
| Steps 1–4 = XOR-Full (2021), solved by CORA without translation | yes | yes | yes |
| Oreag's mechanism = tRAG, and tRAG is the dominated arm | yes | yes | yes |
| Mixed-corpus limit = MLIR, published, with the exact two fixes named | yes | yes | yes |
| Gates as *signals* are unpublished | yes | yes | yes |
| Answer-language policy as a configurable product surface is unshipped everywhere checked | yes | yes | yes |
| The 80/80 number should not be used as evidence | yes | (implied) | yes, emphatically |
| Prompt-only answer-language control is the weakest known method | yes | yes | yes |

### Where they disagree

| Question | Lens A (skeptic) | Lens B (advisor) | Lens C (engineer) |
|---|---|---|---|
| **Keep the script gate?** | Scrap it. The evidence argues cross-lingual retrieval beats in-language retrieval *even when* in-language docs exist ([2410.01171](https://arxiv.org/abs/2410.01171), [knowllm-1.15](https://aclanthology.org/2024.knowllm-1.15/)); the gate is the direct cause of the mixed-corpus bug | Scrap it; the gate provably cannot fire for romanized queries | Keep gating, fix the signal. Unconditional translation has real measured cost and real measured harm ([2407.13522](https://arxiv.org/abs/2407.13522), [2507.22923](https://arxiv.org/abs/2507.22923)) |
| **Is conditional invocation worth claiming?** | Only as a cost optimisation; "36 calls instead of 80", not a new capability | Yes, as a short systems/efficiency paper; nothing suggests it beats a strong encoder on accuracy, only on spend | Yes, and it is the one architectural instinct to protect |
| **Highest-value next move** | Run XOR-Full / XRAG; then adopt a stronger encoder and see if the whole gated path is dead weight | Build the per-query strategy router; build the missing Indic retrieval benchmark | Re-measure on LAReQA + MLAIRE; swap in BGE-M3 untranslated as the baseline; move document-side normalisation to index time |
| **Per-tenant / cold-start mixed corpora** | not raised | not raised | Raised as a real gap — every published mixed-corpus fix assumes large, static, known-language collections with parallel data (SHIFT needs ~533k pairs; DS@GT keys on τ=20 native exemplars). A tenant with 12 English PDFs + 3 Hindi has none of that. Confidence medium; partially dissolved because SHIFT vectors are per *language pair*, precomputable globally |
| **Attribution / grounding** | not raised | not raised | Raised as the thing rank-1 structurally cannot see ([2305.14332](https://arxiv.org/abs/2305.14332), [2406.16135](https://arxiv.org/abs/2406.16135)) |

The disagreement that matters operationally is the first one. A and B say the script gate is a design the
evidence argues against; C says the gate is the right idea with the wrong signal. Both can be satisfied:
**gate on retrieval evidence, not on script presence.** That drops the harmful heuristic while keeping
the cost control, and it happens to be the one gate signal nobody has published.

---

## 2. Consolidated capability table

Status key: **SOLVED** = published and shipped/released, adopt it. **PARTIAL** = solved as a research
capability but not as a usable control surface. **OPEN** = no prior art found. Novelty confidence is
confidence that *Oreag's version is new*, not that it is valuable.

| # | Capability | Status | Prior art | Novelty conf. | Evidence |
|---|---|---|---|---|---|
| 1 | The whole target behaviour as a formal task (ask in B, evidence in A, answer in B) | **SOLVED, 2021** | [XOR QA / XOR-Full](https://aclanthology.org/2021.naacl-main.46/), [arXiv:2010.11856](https://arxiv.org/abs/2010.11856), [code](https://github.com/AkariAsai/XORQA); [MIA 2022 16-lang shared task](https://aclanthology.org/2022.mia-1.11/); [AfriQA](https://arxiv.org/abs/2305.06897) | none | 40k questions, 7 languages chosen *because* no same-language answer exists; 3 sub-tasks; public leaderboard; MIA best constrained system 31.6 avg F1 over 16 languages |
| 2 | End-to-end system doing 1–4 with **no translation hop at all** | **SOLVED, 2021** | [CORA](https://arxiv.org/abs/2107.11976), [code](https://github.com/AkariAsai/CORA); superseded by [CLASS](https://aclanthology.org/2024.emnlp-main.770/) | none | CORA: +23.4 F1 XOR-TyDi, +4.7 F1 MKQA, 26 languages incl. 9 unseen; abstract states it "answers directly in the target language without any translation or in-language retrieval modules". CLASS: 42.4 F1 / 32.7 EM on XOR-Full vs CORA 34.7 / 25.8, again no MT |
| 3 | Oreag's mechanism: translate question → embed translation → retrieve → answer from original | **SOLVED, and it loses** | Named **tRAG** in [arXiv:2504.03616](https://arxiv.org/abs/2504.03616) / [findings-eacl.35](https://aclanthology.org/2026.findings-eacl.35/); used as a distillation *teacher* (i.e. too expensive to ship) by [DR.DECR](https://arxiv.org/abs/2112.08185) | none | MKQA flexible-EM GPT-4o: tRAG 46.5 < monoRAG 51.5 < MultiRAG 53.1 < CrossRAG 60.4. CrossRAG beats tRAG +13.9 (MKQA) / +9.0 (MLQA). Abstract: tRAG "suffers from limited coverage" |
| 4 | Query translation shipped as a product feature | **SOLVED, free, since May 2025** | [RAGFlow Cross-language search](https://ragflow.io/docs/glossary), v0.19.0 | none | Glossary verbatim: "an English query can be used to retrieve Chinese documents"; supported in Knowledge and Chat modules, "such as in Chinese-English datasets". Difference vs Oreag: always-on, no gate |
| 5 | Cross-script semantic retrieval with **no** translation | **SOLVED, commodity, often better than translating** | [M3-Embedding/BGE-M3](https://aclanthology.org/2024.findings-acl.137/), [mE5](https://arxiv.org/abs/2402.05672), [Contriever](https://arxiv.org/abs/2112.09118), [Cohere embed-multilingual-v3.0](https://huggingface.co/CohereLabs/Cohere-embed-multilingual-v3.0) | none | Contriever abstract: retrieves "English documents from Arabic queries, which would not be possible with term matching". Sinhala/Tamil→English ([2608.12820](https://arxiv.org/abs/2608.12820)): BGE-M3 untranslated R@15 96.2%/95.6% vs Google-Translate QT 92.4%/93.0%. [CLIRudit](https://arxiv.org/abs/2504.16264): NV-Embed-v2 0.580 MAP untranslated vs 0.600 with *gold human* translation; QT actively degraded several dense models |
| 6 | Answer returned in the query language, reliably, from foreign evidence | **SOLVED at four levels** | prompt: [Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/); decode: [SCD](https://arxiv.org/abs/2511.09984), [LCG](https://arxiv.org/abs/2510.17555), [LATB](https://arxiv.org/abs/2606.08994); steering: [ReCoVeR](https://arxiv.org/abs/2509.14814), [ITLC](https://arxiv.org/abs/2506.12450); training: [PLUG](https://aclanthology.org/2024.acl-long.379/), [ORPO](https://arxiv.org/abs/2505.19116), [TLPO](https://arxiv.org/abs/2604.26553) | none | Command-R-35B answers in English for ~50% of non-English queries by default → >95% CLR with translated prompt + explicit instruction. SCD: ZH 68.4→90.6, RU 80.2→95.4, AR 85.4→96.4. LATB: Llama3-8B Russian response-level confusion 92.50% → 0.10%. LCG: correct-language token is already top-3 99.29% of the time |
| 7 | Prompt-only answer-language control (what Oreag does) | **KNOWN INSUFFICIENT** | [arXiv:2504.00597](https://arxiv.org/abs/2504.00597) | n/a | 24.85% of Arabic queries answered *correctly but in the wrong language* despite an explicit "Please respond in Arabic". A two-step answer-then-translate prompt AND larger models (Gemma3-27B-IT, GPT-5-nano) both failed: "an inherent decoding limitation" |
| 8 | Mixed-language corpus: query collapses onto its own language half | **SOLVED — bug and both of Oreag's proposed fixes are published** | [The Cross-Lingual Cost, arXiv:2507.07543](https://arxiv.org/abs/2507.07543) | none | §3 verbatim: "The corpus includes documents in both languages, and each query is associated with a ground-truth answer found in one language only." Language-oracle ablation isolates document–document language mismatch. M-E5 Hit@20 −42% (Legal) / −33% (Travel); accuracy −40%/−37%. Fixes: (a) equal passages per language subset, (b) search the joint corpus twice — original + translated query — and merge by inner-product score. Both free in same-language cases, +4–6% (BGE-M3) / ~20% (M-E5) |
| 9 | Mixed-corpus as a named field with a TREC task | **SOLVED, 24 years of prior art** | MLIR definition [arXiv:2209.01335](https://arxiv.org/abs/2209.01335); [NeuCLIR 2024](https://arxiv.org/abs/2509.14355); [RAGTIME 2025](https://arxiv.org/abs/2602.10024); [NeuCLIRBench](https://arxiv.org/abs/2511.14758); CLEF merging [2002](https://ceur-ws.org/Vol-1168/CLEF2002wn-adhoc-LinEt2002.pdf), [2004](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf) | none | RAGTIME MLIR task verbatim: "systems search all four document collections and produce a single unified ranked list" — 13 teams, 125 runs. NeuCLIR 2024 MLIR: one list over ~2M fa + ~3M zh + ~5M ru, best nDCG@20 0.545. NeuCLIRBench: 250,128 judgments |
| 10 | Per-language sub-search + fusion (Oreag's planned repair) | **SOLVED, with copyable constants** | [DS@GT](https://arxiv.org/abs/2607.22841); [medical 50/50 fusion](https://arxiv.org/abs/2604.20531); [CroSearch-R1](https://arxiv.org/abs/2604.25182); [LAURA](https://arxiv.org/abs/2604.20199); [Savoy CLEF 2004](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf) | none | DS@GT: when a language has <τ=20 native exemplars, weighted RRF with w_global=1.0, w_lang=2.0, k=60; Hindi ran three-way RRF over global + English + Arabic proxy, final Hindi accuracy 73.5%. Medical: fixed 50/50, 10 docs, beats English-only for low-resource (Basque 76.0% vs 68.18%, Kazakh 75.73% vs 66.93%). Savoy's warning: raw-score merging −73% MAP when per-language runs use different engines; logistic regression on ln(rank)+RSV wins (+28–44%) |
| 11 | Cheaper mixed-corpus fixes needing no routing, no second index, no per-query cost | **SOLVED** | [SHIFT](https://arxiv.org/abs/2606.18801); [LangSAE](https://arxiv.org/abs/2601.04768); [LIR (2021)](https://aclanthology.org/2021.emnlp-main.470/); [MTD ColBERT-X](https://arxiv.org/abs/2405.00977); [MIMO](https://arxiv.org/abs/2605.31171) | none | SHIFT: subtract the mean parallel-pair embedding difference from *document* embeddings at index time only — zero query-time cost, no retraining; mE5-large nDCG@20 0.633 → 0.737 avg over 4 benchmarks. LangSAE: Belebele nDCG@20 0.5359 → 0.6534 (+21.9%), Chinese +104.3%, reconstructs to original dimensionality so existing vector DBs still work. LIR did the linear version in 2021 with ~100% relative MAP gain on LAReQA |
| 12 | Reranker-side control of the language composition of the context | **SOLVED** | [LAMAR](https://arxiv.org/abs/2607.22042); [LAURA](https://arxiv.org/abs/2604.20199) | none | LAMAR: existing multilingual rerankers put a *non*-English doc first 72.8% of the time for English queries when equivalent docs exist across languages; LAMAR reaches nDCG@1 96.89 (XQuAD) / 94.66 (BELEBELE) for language coherence while staying competitive on MIRACL (69.5 vs 69.7). LAURA: >70% of BGE-reranker top-5 come from English + query language alone; ~15 points of Recall@3-gram left vs oracle (48.9 vs 63.6), worst on ko 25.5/41.0, th 26.4/44.1, ja 29.2/47.9 |
| 13 | Conditional invocation of an expensive cross-lingual path (gating, in general) | **PARTIAL — pattern published, signals differ** | [Syfer](https://arxiv.org/abs/2608.13160); [CORAL](https://arxiv.org/abs/2604.25676); [Script Gap](https://arxiv.org/abs/2512.10780) | low | Syfer's English pathway fires only when cos(filled sub-question, original) < τ=0.8 (+8.91 F1 on MuSiQue). CORAL gates on an LLM sufficiency critic (+3.58pp BLEnD low-resource). None gates on the retrieval score of an already-executed search |
| 14 | **Gate on the retrieval score of a first-pass search** | **OPEN** | none found | medium | Multiple independent searches returned nothing: "conditional query translation" + retrieval, "when to translate" + retrieval, "selective translation" + retrieval, "adaptive" + cross-lingual + RAG, abs:"language confusion" AND abs:"retrieval-augmented" (0 results). Every published system translates unconditionally (tRAG, CrossRAG, DELTA, DKM-RAG, QTT-RAG). Motivating evidence exists and is unexploited ([2407.13522](https://arxiv.org/abs/2407.13522), [2507.22923](https://arxiv.org/abs/2507.22923)) |
| 15 | **Unicode script-presence as the routing signal** | **OPEN, but evidence argues against it** | none found | medium (that it is unpublished); low (that it is right) | Nothing found using writing-system presence in the corpus as a boolean gate. But: [BordIRLines](https://arxiv.org/abs/2410.01171) and [Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/) both find multilingual/concatenated retrieval beats in-language-only; [Haystack ships the same routing as its documented default](https://haystack.deepset.ai/tutorials/32_classifying_documents_and_queries_by_language) ("only documents in that language are used to generate the answer") and reproduces Oreag's bug; [Elastic advises against query-language detection](https://www.elastic.co/blog/multilingual-search-using-language-identification-in-elasticsearch) because queries are short; a script check is blind to romanized Hindi |
| 16 | **Quality-vs-translation-call-budget curve for cross-lingual RAG** | **OPEN** | none found | medium | Cost-explicit papers are all unconditional pipelines optimised by model choice: [Bengali advisory](https://arxiv.org/abs/2601.02065) ~15.6 s/query on a T4; [JobSphere](https://arxiv.org/abs/2511.08343) 89% cost reduction via 4-bit quantization; [DELTA](https://arxiv.org/abs/2601.02956) 1.13 s/query vs 3.80 for DKM-RAG. Nobody publishes retrieval quality as a function of how often the expensive path fires |
| 17 | **Answer-language policy as a configurable, enforced, measured control surface** | **OPEN as a product; solved as a mechanism** | measured by [XRAG](https://arxiv.org/abs/2505.10089), [LCB](https://aclanthology.org/2024.emnlp-main.380/), [MIRAGE-Bench](https://arxiv.org/abs/2410.13716), [LcRL CLR](https://arxiv.org/abs/2601.14896); enforced by [SCD](https://arxiv.org/abs/2511.09984)/[LCG](https://arxiv.org/abs/2510.17555)/[ReCoVeR](https://arxiv.org/abs/2509.14814); never exposed | high (as a product gap); low (as research) | Checked: [LangChain retrieval docs](https://docs.langchain.com/oss/python/langchain/retrieval) — no multilingual/translation content at all; [LlamaIndex](https://huggingface.co/llamaindex/vdr-2b-multi-v1) — cross-lingual model but no pipeline component; [Haystack cookbook](https://haystack.deepset.ai/cookbook/multilingual_rag_podcast) — hardcoded prompt string; [Azure](https://docs.azure.cn/en-us/search/search-language-support) — admits it has no mechanism to determine query language; [Vespa](https://docs.vespa.ai/en/linguistics.html) — "does not out-of-the-box support cross-lingual retrieval"; [Vertex AI Search](https://docs.cloud.google.com/generative-ai-app-builder/docs/about-advanced-features) and [kapa.ai](https://docs.kapa.ai/) — nothing; [RAGAS metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/) — no language-consistency metric |
| 18 | Per-query router over the *strategy* space (tRAG vs CrossRAG vs DELTA vs …) | **OPEN** | closest: [CORAL](https://arxiv.org/abs/2604.25676) (per-query corpus reselection), [DS@GT](https://arxiv.org/abs/2607.22841) (routes indexes and generator models, not strategies) | medium-high | Every strategy paper evaluates a fixed global policy. Precondition proven: no universally best strategy by model *and* language ([2507.22923](https://arxiv.org/abs/2507.22923)); DELTA itself notes its gains vanish when the query is already English ([2601.02956](https://arxiv.org/abs/2601.02956)) |
| 19 | Hindi/Indic cross-lingual RAG benchmark that actually requires retrieval | **OPEN** | [XOR-TyDi](https://aclanthology.org/2021.naacl-main.46/) has no Hindi split (Bn, Te only); [IndicGenBench](https://arxiv.org/abs/2404.16816) supplies gold passages; [IndicRAGSuite](https://arxiv.org/abs/2506.01615) is multi-monolingual; [Hindi-BEIR](https://arxiv.org/abs/2408.09437) monolingual; [MEMERAG](https://arxiv.org/abs/2502.17163) has Hindi but same-language corpora; [HEALTH-PARIKSHA](https://arxiv.org/abs/2410.13671) right setup, 19 Hindi pairs | high | Verified by full-text extraction that IndicRAGSuite contains zero occurrences of "cross-lingual" |
| 20 | Per-tenant, dynamically-composed, cold-start mixed-language corpora | **OPEN (probably not hard)** | all mixed-corpus work assumes static known collections: [SHIFT](https://arxiv.org/abs/2606.18801) (533k parallel pairs), [MTD](https://arxiv.org/abs/2405.00977) (training pipeline), [RAGTIME](https://arxiv.org/abs/2602.10024) (~1M docs/language), [DS@GT](https://arxiv.org/abs/2607.22841) (τ=20 in a 30k KB) | medium | The idf pathology for a 3-document shard was named in 2002: pooling "raises N in idf without raising term occurrences… it makes retrieval result preferring documents in small document collection" ([CLEF 2002](https://ceur-ws.org/Vol-1168/CLEF2002wn-adhoc-LinEt2002.pdf)). Largely dissolves because SHIFT vectors are per *language pair* and precomputable globally |
| 21 | Romanized / code-mixed query handling behind a script gate | **OPEN as a composition; components exist** | [IndicLID](https://aclanthology.org/2023.acl-short.71/); [GlotLID](https://github.com/cisnlp/GlotLID); [Lost in Transliteration](https://arxiv.org/abs/2505.08411); [CS-MTEB](https://arxiv.org/abs/2604.17632) | medium-high (as composition); this is a live bug, not a paper | IndicLID 98.55% native vs 80.40% romanized. Transliterate-train 50/50 mix is the only config that repairs the transliterated side without wrecking the native one (Chinese-T MRR@10 0.0078 → 0.1382). Code-switching costs robust multilingual retrievers up to 27%; vocabulary expansion insufficient |
| 22 | Attribution of a language-B answer to language-A evidence | **SOLVED as instrumentation; unmeasured in Oreag** | [XOR-AttriQA](https://arxiv.org/abs/2305.14332); [DoGMaTiQ](https://arxiv.org/abs/2605.04458); [MEMERAG](https://arxiv.org/abs/2502.17163) | none | Up to ~47% of exactly-correct cross-lingual answers unattributable. Cheap fix: PaLM 2 fine-tuned on ~100 attribution examples reaches 92–96% accuracy / 95–98% ROC AUC. DoGMaTiQ's QA-nuggets "decouple the information need from the potentially diverse content that satisfies it" — the only grading form that survives an answer string that can never lexically match its English source |

---

## 3. The strongest defensible claim you could make

Everything below is phrased so it survives contact with the prior art above. Anything stronger is
checkable and wrong.

**Claim 1 — the composition, scoped as engineering, not research (strongest).**

> "Oreag is, as far as we can find, the only system that invokes the cross-lingual retrieval path
> *conditionally*, on evidence from a retrieval that already ran, rather than translating every query or
> every document unconditionally — and it treats the answer language as a configurable, enforced policy
> rather than a hardcoded prompt string."

Both halves hold. No published system gates translation on a first-pass retrieval score (row 14). No
research paper or documented commercial RAG product exposes answer-language as a policy (row 17). The
claim is defensible precisely because it is a *packaging* claim, not a capability claim.

**Claim 2 — the cost result, if you measure it.**

> "Conditional invocation retains X% of the quality of an unconditional cross-lingual pipeline at Y% of
> the translation calls."

Nobody has published this curve (row 16), and the motivating evidence that unconditional translation is
sometimes actively harmful is already published and unexploited — Hindi loses 20.5 F1 to translate-test
on Llama-3 ([arXiv:2407.13522](https://arxiv.org/abs/2407.13522)) and every translation strategy hurt
Hindi on Llama-3.1-8B by up to 10.9 points ([arXiv:2507.22923](https://arxiv.org/abs/2507.22923)). This
is a short systems/efficiency contribution, not a framework.

**Claim 3 — the per-query strategy router, if you build it.**

> "Rather than fixing one cross-lingual strategy globally, route each query among the published
> strategies based on query language, script, corpus language composition and first-pass retrieval
> signal."

This is the only item on the list with genuine research shape (row 18), and it is the natural home for
the gating instinct. Bar to clear: it must beat *always* using CrossRAG, which is +17.8% over monolingual
RAG averaged across languages ([arXiv:2504.03616](https://arxiv.org/abs/2504.03616)).

**Claim 4 — a Hindi/Indic cross-lingual retrieval benchmark, if you build one.**

The gap is verifiable from the resources themselves rather than from failure to find a paper (row 19).
Real community value, and the only credible way to make Oreag's own numbers comparable to anything
published.

### What you must NOT claim

- **Not** "no framework exists." XOR-Full (2021), CORA (2021), CLASS (2024), and a shipped RAGFlow
  feature (2025) all say otherwise.
- **Not** "translating the question to reach a foreign-language corpus is new." That is tRAG, and it is
  the dominated arm of a four-way published comparison.
- **Not** "the mixed-corpus problem is unexplored." It is MLIR, it has a TREC task, and
  [arXiv:2507.07543](https://arxiv.org/abs/2507.07543) publishes your setup *and* both of your proposed
  repairs.
- **Not 80/80 at rank 1 across 40 languages, as evidence of anything.** Published SOTA on the same task
  shape is 42.4 F1 on XOR-Full and 37.4 Token-F1 on 28 Indic languages. A number that far above the field
  on a bespoke probe set is a claim about the probe set.
  [MLAIRE](https://arxiv.org/abs/2605.07249) exists because nDCG and query-language preference are
  near-orthogonal and can be anti-correlated (Pearson −0.28 to −0.47 across 31 retrievers); on a
  single-script corpus you cannot tell them apart. Re-run on
  [XOR-Retrieve](https://github.com/AkariAsai/XORQA) and
  [LAReQA](https://aclanthology.org/2020.emnlp-main.477/)'s mixed pool, and report LPR beside nDCG,
  before this number appears in anything external.

### Where Oreag is at or ahead of the published state of the art

Three places, said plainly:

1. **Conditional execution.** Every published cross-lingual RAG pipeline pays its expensive step on every
   query. Oreag does not. Syfer and CORAL gate on other signals; nobody gates on retrieval score.
2. **Answer-language as a policy object.** LangChain, LlamaIndex, Haystack, RAGFlow, Azure AI Search,
   Vespa, Weaviate, Vertex AI Search and kapa.ai were all checked, and none documents one. XRAG, LCB and
   MIRAGE-Bench measure it; nobody exposes it.
3. **Decoupling the retrieval query from the generation query.** Embedding a translation while the
   original question drives generation, so the answer language follows for free, was not found as a
   stated mechanism anywhere. Note the caveat that makes it *good* rather than merely different:
   [arXiv:2406.16135](https://arxiv.org/abs/2406.16135) measures a ~10–13 point reasoning penalty from
   language mixing in the prompt (GPT-4 81.82 → 68.61 on mixup-MMLU), which is a real argument for
   keeping the *original* question in the generation prompt.

---

## 4. What is NOT novel and should simply be adopted

Ordered by expected value per unit of work.

### Retrieval

| Adopt | Why | Source |
|---|---|---|
| **BGE-M3 / mE5-large-instruct as the untranslated baseline** — run it this week | If a stronger encoder closes the gap, the 36 model calls and both gates are dead weight. This is the single highest-leverage test available | [BGE-M3](https://aclanthology.org/2024.findings-acl.137/) MKQA R@100 75.5 vs mE5-large 70.9; [Sinhala/Tamil head-to-head](https://arxiv.org/abs/2608.12820) 96.2%/95.6% untranslated beats every QT pipeline; [MMTEB](https://arxiv.org/abs/2502.13595) names mE5-large-instruct (560M) best public model |
| **SHIFT — index-side language-vector subtraction** | The cheapest possible fix for the mixed corpus: no retraining, no routing, no second index, zero query-time cost, and the vectors are per language-pair so they precompute globally and apply to any tenant | [arXiv:2606.18801](https://arxiv.org/abs/2606.18801) — mE5-large nDCG@20 0.633 → 0.737; Target-Languages Recall@20 0.540 → 0.694 |
| **LangSAE — suppress language-identity latents** | Reconstructs to original dimensionality, so your existing vector DB keeps working; strongest exactly where you care (script-distinct languages) | [arXiv:2601.04768](https://arxiv.org/abs/2601.04768) — Belebele +21.9% nDCG@20, Chinese +104.3% |
| **The two fixes from The Cross-Lingual Cost**, verbatim | Do not re-derive your own repair. Balanced per-language retrieval, and dual search (original + translated query) merged by score. Free in same-language cases | [arXiv:2507.07543](https://arxiv.org/abs/2507.07543) |
| **DS@GT's weighted-RRF constants**, if you do build routing | w_global=1.0, w_lang=2.0, k=60, shard threshold τ=20 native exemplars; Hindi worked end-to-end | [arXiv:2607.22841](https://arxiv.org/abs/2607.22841) |
| **Savoy's merging warning**, before you pick a fusion rule | Raw-score merging collapses −73% MAP when per-language runs use different engines but gains +30% when they share one; logistic regression on ln(rank)+RSV wins in all conditions | [CLEF 2004](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf) |
| **LAMAR or LAURA at the rerank stage** | Explicit control of the language composition of the final context instead of leaving it to embedding-space luck | [LAMAR](https://arxiv.org/abs/2607.22042), [LAURA](https://arxiv.org/abs/2604.20199) |
| **Hybrid dense+sparse, not dense-only** | In multilingual settings dense retrieval barely beats BM25; fusion is where the win is | [MIRACL](https://aclanthology.org/2023.tacl-1.63/) 18-lang dev: BM25 0.393, mDPR 0.415, hybrid **0.578** nDCG@10 |

### Generation and language control

| Adopt | Why | Source |
|---|---|---|
| **Chirkova's prompt recipe** (minimum, if API-only) | Translate the *prompt* into the user's language plus an explicit "generate the response in the user language" instruction: ~50% English-leakage → >95% Correct Language Rate | [aclanthology.org/2024.knowllm-1.15](https://aclanthology.org/2024.knowllm-1.15/) |
| **SCD or LCG at decode time** (if self-hosting) | Prompting alone is measurably insufficient. Training-free, model-agnostic, and quality rises alongside | [SCD](https://arxiv.org/abs/2511.09984) ZH 68.4→90.6 with ROUGE 0.182→0.306; [LCG](https://arxiv.org/abs/2510.17555) Qwen3-8B 12.1%→2.0% |
| **Pick the generator on language-confusion numbers, not general benchmarks** | Model choice alone moves wrong-language output ~60 points | [LCB](https://aclanthology.org/2024.emnlp-main.380/): cross-lingual line-level pass rate Llama 3 70B-Instruct 30.3% vs Command R+ 95.4%, GPT-4o 92.4% |
| **Keep the original question in the generation prompt** (you already do) | Mixed-language prompts cost ~10–13 points of reasoning independent of retrieval | [arXiv:2406.16135](https://arxiv.org/abs/2406.16135) |
| **CrossRAG's insight, moved to index time** | Normalise the *context* language rather than the query language — but translating retrieved docs per query is 5 generation calls on the critical path. PSQ already made exactly this offline move and still beat both QT and DT BM25 in 2024 | [CrossRAG](https://arxiv.org/abs/2504.03616); [PSQ at index time](https://arxiv.org/abs/2404.18797) MAP 0.332 vs QT-BM25 0.267 / DT-BM25 0.302 |

### Cost

| Adopt | Why | Source |
|---|---|---|
| **IndicTrans2 or NLLB-200-distilled-600M instead of an LLM call** for the 22 scheduled Indian languages | Local, cheap, keeps the LLM for the tail | [IndicTrans2](https://github.com/AI4Bharat/IndicTrans2); NLLB used this way in [CroSearch-R1](https://arxiv.org/abs/2604.25182) and the [Bengali advisory system](https://arxiv.org/abs/2601.02065) |
| **The classic index-architecture rule**, before choosing query- vs document-side handling | "Query translation has advantages… many possible query languages, but only one document language… Symmetrically, document translation has advantages when all the queries are in one language, but there are many document languages." Your single-language tenants are case 1; your mixed tenants are case 2 | [Cross-language IR survey §2.1](https://arxiv.org/abs/2111.05988) |

### Gating (fix the signal, keep the mechanism)

| Adopt | Why | Source |
|---|---|---|
| **Replace the script gate with a retrieval-evidence gate** | Satisfies all three lenses: drops a heuristic the evidence argues against, keeps the cost control, and lands on the one gate signal nobody has published | rows 14–15 above |
| **IndicLID (or GlotLID for the full 40-language range) behind the gate when the script is Latin** | A Unicode check cannot see Hinglish. This is a live bug in a shipped product, not a research idea | [IndicLID](https://aclanthology.org/2023.acl-short.71/), [GlotLID](https://github.com/cisnlp/GlotLID) |

### Evaluation — adopt wholesale, this is where Oreag is weakest

| Adopt | Measures | Source |
|---|---|---|
| **XOR-Retrieve / XOR-Full** | Makes your number comparable to published ones | [github.com/AkariAsai/XORQA](https://github.com/AkariAsai/XORQA) |
| **LAReQA** | Retrieval from a genuinely mixed-language pool — your open limit. Carries the key warning: training on translated data with monolingual positive pairs (X-X, mAP 0.23) is *worse* than English-only training (0.29); only X-Y fixes it (0.66) | [aclanthology.org/2020.emnlp-main.477](https://aclanthology.org/2020.emnlp-main.477/) |
| **MLAIRE (LPR, Lang-nDCG)** | Separates semantic skill from query-language preference — the distinction your 80/80 cannot make | [arXiv:2605.07249](https://arxiv.org/abs/2605.07249) |
| **XRAG** | Response-language correctness as a first-class metric, plus a ready-made mixed English+query-language condition | [github.com/amazon-science/XRAG](https://github.com/amazon-science/XRAG) |
| **MIRAGE-Bench surrogate judge** | Ranks multilingual RAG generation at Kendall τ 0.909 vs GPT-4o without paying for an LLM judge each run; its feature set already includes language detection and a separate English-detection feature | [github.com/vectara/mirage-bench](https://github.com/vectara/mirage-bench) |
| **NoMIRACL** | Whether the system correctly recognises retrieval failed — exactly what your weak-similarity gate decides | [arXiv:2312.11361](https://arxiv.org/abs/2312.11361) |
| **BERGEN** | The only general RAG eval library verified with first-class multilingual support (query-language vs datastore-language axis) | [github.com/naver/bergen](https://github.com/naver/bergen) |
| **XOR-AttriQA + a ~100-example attribution classifier** | Whether the Hindi answer actually came from the English passage. Cheap: 92–96% accuracy from ~100 examples | [arXiv:2305.14332](https://arxiv.org/abs/2305.14332) |
| **DoGMaTiQ QA-nuggets** | The only grading form that survives an answer string that can never lexically match its source | [arXiv:2605.04458](https://arxiv.org/abs/2605.04458) |
| **MEMERAG** | Validates that your LLM judge is trustworthy *in Hindi specifically*; the best judge differs by language | [arXiv:2502.17163](https://arxiv.org/abs/2502.17163) |
| **Sentence-level LID, not whole-response** | A whole-response detector scores a code-switched Hindi/English answer as a pass | [GlotLID](https://github.com/cisnlp/GlotLID); code-switching persistence noted in [knowllm-1.15](https://aclanthology.org/2024.knowllm-1.15/) |

---

## Appendix A — citations that failed verification

**The discard list returned empty (`[]`).** No citation in this sweep was proposed and then rejected as
non-existent or fabricated. All 176 papers and 120 frameworks above were verified to at least abstract
level.

That is not the same as "everything is equally solid." The following were flagged during verification and
should be treated with the stated level of care.

### A.1 — Claims that were CORRECTED during verification

These were submitted with errors that were caught and fixed. If an earlier draft of this research quoted
the original form, it was wrong.

| Item | The error | The correction |
|---|---|---|
| [XOR-AttriQA](https://arxiv.org/abs/2305.14332) | "500/4720 val/test tuples" | Not matched anywhere in the paper — treat as unsourced. Actual scale is ~10,000 human-annotated tuples across 5 languages. Answers were generated by CORA, not "an mT5-base model fine-tuned for cross-lingual RAG". "Up to 50%" is the abstract's rounding; the body says ~47% |
| [Language-Specific Neurons (Tang et al.)](https://arxiv.org/abs/2402.16438) | Credited with a fine-tuning experiment on ~400 documents giving +3.6%/+2.3% | Those numbers belong to [Zhao et al., arXiv:2402.18815](https://arxiv.org/abs/2402.18815). Tang et al. contains no such experiment. Also note the two papers *disagree* on layer localisation (top/bottom vs deeper) |
| [Multilingual RAG for Knowledge-Intensive Task](https://arxiv.org/abs/2504.03616) | Described as a two-way comparison; tRAG's weakness attributed to "translated queries shedding original context" | It is a **four-way** comparison and MultiRAG (the mixed-index condition) was the omitted arm — the one that matters most here. The paper attributes tRAG's weakness to limited retrieval scope and incorrect query translations |
| [IndicRAGSuite](https://arxiv.org/abs/2506.01615) | "26M Wikipedia triplets" | 26M is the *combined* Wiki + MS MARCO total. Wikipedia portion ~14M; MS MARCO portion 10.85M train + 1.37M val. Also: the benchmark is explicitly monolingual, not cross-lingual |
| [Agri-Query](https://arxiv.org/abs/2508.18093) | ">85% accuracy across languages" | Cleared only by the best model per language (0.880 EN / 0.870 DE / 0.852 FR). Evaluation is LLM-as-a-judge |
| [Krutrim](https://arxiv.org/abs/2502.09642) | Glossed as shipping "production RAG" | Unsupported. The paper's entire treatment of retrieval is one abstract sentence about real-time search integration — no architecture, no retriever, no retrieval evaluation, nothing about query/document language mismatch |
| [Evaluating and Modeling Attribution](https://arxiv.org/abs/2305.14332) | Title given with an "(XOR-AttriQA)" suffix | That is the dataset name, not the title |
| [MIRACL](https://aclanthology.org/2023.tacl-1.63/) | Two different titles in circulation | Both real: "Making a MIRACL…" is the arXiv preprint, "MIRACL: A Multilingual Retrieval Dataset Covering 18 Diverse Languages" is the TACL publication. Cite the TACL title |
| [MLAIRE](https://arxiv.org/abs/2605.07249) | "Protocal" | arXiv's own title carries the typo. Cite as listed or silently fix |
| [MMTEB](https://arxiv.org/abs/2502.13595) | "multilingual-e5-large is best" | It is **multilingual-e5-large-instruct** (560M) |
| [LcRL](https://arxiv.org/abs/2601.14896), [Not All Languages are Equal](https://arxiv.org/abs/2410.21970), [BordIRLines](https://arxiv.org/abs/2410.01171), [CORAL](https://arxiv.org/abs/2604.25676) | Parenthetical acronym suffixes treated as part of the title | They are dataset/method names, not titles |

### A.2 — Verified to metadata only, NOT read in full (do not quote)

- **SqCLIRIL** ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0167865525003071)) —
  paywalled, WebFetch blocked. Title, venue and description from search results only.
- **FIRE 2024 / FIRE 2025 SqCLIR** shared-task papers
  ([2024](https://dl.acm.org/doi/full/10.1145/3734947.3735669),
  [2025](https://dl.acm.org/doi/10.1145/3777867.3778262)) — ACM DL paywalled.
- **FIRE MSIR overview chapters**
  ([Springer](https://link.springer.com/chapter/10.1007/978-3-319-73606-8_3)) — paywalled.
- **Si, Callan et al. (2008)**, results merging in federated MLIR
  ([doi:10.1007/s10791-007-9036-6](https://doi.org/10.1007/s10791-007-9036-6)) — Springer redirected to
  authentication; bibliographic record only.
- **Airio et al., CLEF 2003**
  ([PDF](https://ceur-ws.org/Vol-1169/CLEF2003wn-adhoc-AirioEt2003.pdf)) — PDF downloaded, title/author
  block confirmed, results section not fully read.
- **NLLB-E5 vs BGE-M3 figures (48.57 vs 46.18)** — one angle saw these only in a search snippet; a second
  angle confirmed them in Table 2 of [arXiv:2409.05401](https://arxiv.org/abs/2409.05401). Treat as
  confirmed but single-sourced.
- **Bhashini** ([PIB release](https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2093333&reg=48&lang=2))
  — deployment details from search results only.
- **Three interpretability papers** —
  [arXiv:2402.18815](https://arxiv.org/abs/2402.18815),
  [arXiv:2402.16438](https://arxiv.org/abs/2402.16438),
  [Do Llamas Work in English?](https://aclanthology.org/2024.acl-long.820/) — reported from search-result
  snippets, not fetched abstract pages, in at least one angle. Wording approximate.
- **LiveCLKTBench** ([arXiv:2511.14774](https://arxiv.org/abs/2511.14774)),
  **Multi-FAct** ([arXiv:2402.18045](https://arxiv.org/abs/2402.18045)),
  **XLT** ([arXiv:2305.07004](https://arxiv.org/abs/2305.07004)) — snippet-only in one angle; author lists
  not captured.
- **The XOR QA abstract page itself** — `aclanthology.org/2021.naacl-main.46/` returned ECONNRESET /
  ECONNREFUSED in two separate angles. Verified via the arXiv version
  ([arXiv:2010.11856](https://arxiv.org/abs/2010.11856)) and by cross-reference from AfriQA and three
  other fetched pages. The three sub-task names (XOR-Retrieve / XOR-EnglishSpan / XOR-Full) were confirmed
  by cross-reference, not from the ACL abstract directly.
- **All ACL Anthology IDs** cited in this document were, in several angles, read from search-result URLs
  rather than fetched, because `aclanthology.org` was blocked by the fetch domain-safety policy. They are
  corroborated across angles but re-verify before external publication.

### A.3 — Product claims that could NOT be verified (absence here is unverified, not established)

- **Voyage and Jina embeddings** — multilingual coverage claims found (26 / 89 languages) but no explicit
  "query in language A retrieves documents in language B" statement on any page seen. Cross-lingual
  behaviour **unverified**.
- **OpenAI embeddings** — `openai.com` returned 403, `platform.openai.com` unreachable. Cross-lingual
  behaviour **unverified**. The one MIRACL figure seen came via a Cohere-favourable comparison snippet
  and is not treated as evidence.
- **Cohere Rerank 3.5** — the Bedrock model card fetched makes no multilingual claim (unlike the Embed
  Multilingual card, which does). Cross-lingual reranking **unverified from a primary source**.
- **RAGFlow's implementation mechanism** — the glossary and release notes confirm the feature and its
  modules, but the "default chat model translates the query into user-selected target languages" detail
  came from a search snippet, not a fetched doc page. Deeper RAGFlow doc paths 404'd.
- **kapa.ai** — the per-feature multilingual page **404s**. Recorded as a negative result on the docs
  index, not as a positive verification of absence.
- **Commercial landscape generally** — two of the ten research angles exhausted their WebSearch budget
  before reaching product documentation. Treat the commercial row of any table as *unexamined* where it
  is empty, not empty.

### A.4 — Things actively searched for and NOT found (the basis for every OPEN row above)

These are negative results from explicit queries, recorded so the novelty claims can be audited.

- `abs:"language confusion" AND abs:"retrieval-augmented"` — **0 results**. The language-confusion and
  multilingual-RAG literatures are still largely disjoint and do not cite each other's terminology.
- `"conditional query translation" AND retrieval` — 0. `"fallback" AND "cross-lingual retrieval"` — 0.
  `"query performance prediction" AND "cross-lingual"` — 0. `"selective translation" AND retrieval` —
  only e-commerce query rewriting and Lean premise selection.
- `abs:"script" AND abs:"query translation" AND abs:"retrieval"` — 0.
  `"language identification" AND "retrieval-augmented generation"` — 0.
  `abs:"script" AND abs:"language detection" AND abs:"retrieval"` — 0.
- `"multilingual retrieval-augmented generation" AND "routing"` — 0. `"language-aware routing"` — 16 hits,
  only DS@GT retrieval-related, and it routes indexes and generator models, not strategies.
- `abs:"results merging" AND abs:"multilingual"` — 0 on arXiv; the classic terminology is entirely
  pre-arXiv and lives in CLEF/NTCIR working notes and the *Information Retrieval* journal.
- **No survey of multilingual/cross-lingual RAG exists** that could be verified. Three separate query
  formulations returned only multimodal-RAG and general-RAG surveys. Closest real survey is the CLIR
  survey ([arXiv:2510.00908](https://arxiv.org/abs/2510.00908)), which is not mRAG-specific. Treat as
  "not found", not "does not exist" — one angle exhausted its budget before confirming.
- **No published cosine-similarity-by-script curves.** Degradation is always reported as nDCG/MRR/Recall.
  No comparable Lao or Burmese retrieval-degradation measurements found at all.
- **No modern neural paper re-deriving classic merging (Z-score, logistic-on-rank+score) for dense
  per-language sub-searches.** RRF is used; no ablation of RRF against Z-score or logistic merging on a
  multilingual dense pipeline was found. Narrow, real, publishable.
- **No benchmark for a small mixed-script project corpus** (a handful of English + Hindi files, queries in
  each language, required answer-language match). RAGTIME pins output to English; NeuCLIRBench uses
  English queries only; XRAG uses news, not a user-owned KB.
- **CroCoSum** ([arXiv:2303.04092](https://arxiv.org/abs/2303.04092)) was on a hunt list and verified to
  exist, but it is cross-lingual code-switched *summarization*, not retrieval. Low relevance, recorded for
  completeness.
- **Granite Embedding** low-resource claim was dropped rather than reported: the abstract page returned no
  MIRACL/MTEB detail or low-resource statement.
- **Per-language MIRACL numbers for Tamil, Telugu, Bengali, Khmer, Lao, Burmese** could not be obtained.
  The script-degradation argument therefore rests on Amharic
  ([arXiv:2605.24556](https://arxiv.org/abs/2605.24556)), Mr. TyDi's mDPR-loses-to-BM25 result
  ([aclanthology.org/2021.mrl-1.12](https://aclanthology.org/2021.mrl-1.12/)), and ALEE's tokenization
  finding ([arXiv:2607.00171](https://arxiv.org/abs/2607.00171)) — not on direct Indic or Southeast Asian
  measurements.
- **"Cross-lingual alignment gap" is not a canonical term.** The field says cross-lingual alignment,
  language bias, self language bias, query-language preference / Language Preference Rate, and monolingual
  alignment preference. No single agreed name for the gap itself.
- Several arXiv IDs appeared in one angle's search results with titles only and were **not** verified
  there — CORAL, LAMAR, M4-RAG, BordIRLines, IndicRAGSuite, CLIRudit among them. All of these were
  independently verified by other angles and appear above on that basis; two IDs seen title-only and never
  independently confirmed (2602.03992, 2605.26755) are **not** cited anywhere in this document.

### A.5 — Tooling limits that shaped coverage

- `aclanthology.org` was unreachable or blocked in at least four angles (ECONNRESET, ECONNREFUSED, and
  domain-safety refusal). Worked around via arXiv mirrors.
- The shared **WebSearch budget (200 calls)** was exhausted mid-sweep in six of ten angles. One angle
  (mixed-corpus) had zero WebSearch available and ran entirely on the arXiv API, DBLP, CEUR-WS PDFs
  extracted locally, and Semantic Scholar.
- WebFetch was blocked at the network layer for `arxiv.org`, `huggingface.co`, `semanticscholar.org`,
  `openreview.net`, `docs.cohere.com`, `learn.microsoft.com`, `github.com`,
  `raw.githubusercontent.com`, `qdrant.tech`, `weaviate.io`, and intermittently `www.elastic.co`, in
  various angles. Worked around with `curl` via Bash against the arXiv API/HTML endpoints, `docs.azure.cn`
  for Azure, AWS Bedrock model cards for Cohere, and `docs.weaviate.io` for Weaviate.
- The XRAG PDF returned unreadable compressed content; its metric details come from the arXiv HTML v1
  rendering.
- Semantic Scholar returned HTTP 429 on three of four calls in one angle. Google Scholar was never
  reachable.
