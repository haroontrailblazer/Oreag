# Cross-Lingual RAG: Prior Art, State of the Art, and What Is Actually Open

## Verdict: it exists. It has a name, a benchmark, a TREC track, open code, and a shipped product feature.

The belief that no such framework or research exists is false, and it is false at every layer of the
design — including the part described here as a "known open limit," which is the single most crowded
sub-problem in the field.

- **The task** — question in language B, evidence retrieved from a language-A corpus, answer returned
  in language B — was formalised in 2021 as **XOR-Full** in
  [XOR QA (NAACL 2021)](https://aclanthology.org/2021.naacl-main.46/). 40k questions, 7 languages,
  deliberately selected because no same-language answer exists.
- **The end-to-end system** was published the same year:
  [CORA (NeurIPS 2021)](https://arxiv.org/abs/2107.11976) retrieves cross-lingually with mDPR and
  generates with mGEN, and its abstract states it "answers directly in the target language without any
  translation or in-language retrieval modules as used in prior work" — 26 languages, 9 unseen in
  training. It was beaten in 2024 by [CLASS](https://aclanthology.org/2024.emnlp-main.770/), 42.4 F1 vs
  CORA's 34.7 on XOR-Full, again with no MT component.
- **The specific Oreag mechanism** — embed an LLM translation of the question, keep the original
  question for generation — is named **tRAG** in the standard taxonomy
  ([arXiv:2504.03616](https://arxiv.org/abs/2504.03616), published as
  [Findings of EACL 2026](https://aclanthology.org/2026.findings-eacl.35/)) and it places **last of four**
  strategies: GPT-4o flexible-EM on MKQA runs no-RAG ~43 → tRAG 46.5 → monoRAG 51.5 → MultiRAG 53.1 →
  CrossRAG 60.4. The same architecture was the losing baseline in XOR QA five years ago (18.7 F1 vs ~40
  F1 for comparable monolingual English systems).
- **It ships**: [RAGFlow "Cross-language search"](https://ragflow.io/docs/glossary) has been GA since
  v0.19.0 (26 May 2025) — "an English query can be used to retrieve Chinese documents," implemented by
  having the chat model translate the query before matching. Free, open source, no gate.
- **The mixed-language corpus limit** is published with the exact repair:
  [The Cross-Lingual Cost (arXiv:2507.07543)](https://arxiv.org/abs/2507.07543) states the setup
  verbatim ("the corpus includes documents in both languages... its goal is to generate an answer in the
  same language"), isolates the cause with a language-oracle ablation as document-document language
  mismatch inside one index, and evaluates both proposed fixes — balanced per-language retrieval, and
  searching the joint corpus twice (original + translated query) then merging ranked lists.

Two things in the Oreag design do appear unpublished, and all three independent gap analyses agree on
which: **the gate signals** (Unicode script presence in the corpus; retrieval-score threshold as the
translate/don't-translate trigger) and **answer-language policy as a configurable product surface**.
Both are engineering, not capability. Neither is a reason to keep building the rest.

---

## The problem, stated once

You have a corpus embedded in language A and users asking in language B. Three things must hold
simultaneously and they fail independently: retrieval must cross the language boundary on *meaning*
(not keyword or translation luck); generation must be grounded in the language-A evidence it was given;
and the answer must come out in language B. The field has shown that these are three separate failure
modes with three separate literatures — cross-lingual retrieval is largely commodity, grounding across
a language boundary is measurably worse than rank@1 suggests (up to ~47% of exactly-correct
cross-lingual answers are not attributable to any retrieved passage,
[XOR-AttriQA](https://arxiv.org/abs/2305.14332)), and *answering in the right language* is the hardest
of the three, not the free one ([arXiv:2504.00597](https://arxiv.org/abs/2504.00597) measures 24.85% of
Arabic queries answered **correctly but in the wrong language** despite an explicit "Please respond in
Arabic" instruction, and neither a two-step translate-after prompt nor larger models fixed it). The
mixed-language corpus — one index holding both A and B — is a fourth, named problem (MLIR) with 24 years
of prior art.

---

## What already exists

| Work | What it is | Why it matters here |
|---|---|---|
| [XOR QA / XOR-Full](https://aclanthology.org/2021.naacl-main.46/) ([code](https://github.com/AkariAsai/XORQA)) | The task definition. 40k questions, 7 languages with no same-language answer; XOR-Retrieve / XOR-EnglishSpan / XOR-Full. | XOR-Full **is** steps 1–4. Its strongest baseline is the translate-question-retrieve-English-generate pipeline at 18.7 F1 / 12.1 EM. Run your 80/80 claim here. |
| [CORA](https://arxiv.org/abs/2107.11976) ([code](https://github.com/AkariAsai/CORA)) | mDPR + mGEN, one retriever over a multilingual collection, one generator. +23.4 F1 XOR-TyDi, +4.7 MKQA, 26 languages. | Solves steps 1–4 with **no translation hop at all**, in 2021. The hop is not the invention; it is what CORA removed. |
| [tRAG / monoRAG / MultiRAG / CrossRAG](https://arxiv.org/abs/2504.03616) | The four-way taxonomy and head-to-head. CrossRAG translates the *retrieved documents* into a common language before generation. | tRAG (yours) is last. CrossRAG beats it by +13.9 on MKQA / +9.0 on MLQA, and — measured with OpenLID — generates in the correct language *more consistently*. Normalising the context language beats normalising the query language. |
| [The Cross-Lingual Cost](https://arxiv.org/abs/2507.07543) | Balanced Arabic-English corpus, real corporate Legal/Travel data. M-E5 Hit@20 −42%/−33% cross-lingually; end-to-end accuracy −40%/−37%. | Your mixed-corpus bug, diagnosed and fixed. Both mitigations cost nothing in the same-language case ("no statistically significant loss") while adding ~4–6% for BGE-M3 and ~20% for M-E5. |
| [Chirkova et al., mRAG in multilingual settings](https://aclanthology.org/2024.knowllm-1.15/) | Released 13-language mRAG pipeline; ablates English-only vs user-language-only vs **concatenated** multilingual Wikipedia. | Closest reusable reference implementation of the whole pipeline. Finds the single concatenated index beneficial in most cases with BGE-M3 — i.e. it tested your mixed-corpus case and did *not* conclude you need routing. Command-R-35B answered in English for ~50% of non-English queries by default; prompt translation + explicit instruction → >95% correct-language rate. |
| [Language Confusion Benchmark](https://aclanthology.org/2024.emnlp-main.380/) ([code](https://github.com/for-ai/language-confusion)) | 15 languages, monolingual and cross-lingual settings, LPR / WPR metrics. | Its two settings *are* your two policy modes (match the query vs obey a pinned language). Model choice alone moves this ~60 points: cross-lingual line-level pass rate 30.3% for Llama 3 70B-Instruct vs 95.4% Command R+ Refresh, 92.4% GPT-4o. |
| [Soft Constrained Decoding](https://arxiv.org/abs/2511.09984) ([code](https://github.com/WisdomShell/SCD)) | Training-free logit penalty on non-target-language tokens. AAAI'26 oral. | Swapping the retrieved context from Chinese to English drops language consistency 92.0% → 68.4% *with the instruction still in the prompt*. SCD recovers ZH 68.4→90.6, RU 80.2→95.4, AR 85.4→96.4 with ROUGE rising. Needs logit access. |
| [XRAG](https://arxiv.org/abs/2505.10089) ([code](https://github.com/amazon-science/XRAG)) | Amazon benchmark, 5 languages, news-derived, with a **monolingual-English-retrieval** and a **mixed-corpus** condition. | The only harness that scores *response language correctness* as a first-class metric. Wrong-language rates: ~5% GPT-4o and Command-R+, ~15% Claude 3.5 Sonnet, ~35% Mistral-large. Ready-made test for the open limit. |
| [BGE-M3 / M3-Embedding](https://aclanthology.org/2024.findings-acl.137/) | 100+ languages, dense+sparse+multi-vector, 8192 tokens. MKQA Recall@100 75.5 vs mE5-large 70.9 over one shared English corpus. | The no-translation alternative to your entire cross-lingual path. On Sinhala/Tamil→English ([arXiv:2608.12820](https://arxiv.org/abs/2608.12820)) it beats every query-translation pipeline: R@15 96.2%/95.6% vs Google Translate 92.4%/93.0%. |
| [TREC NeuCLIR](https://arxiv.org/abs/2509.14355) / [RAGTIME](https://arxiv.org/abs/2602.10024) | Shared tasks since 2022. NeuCLIR's MLIR task: one unified ranked list over ~2M Persian + ~3M Chinese + ~5M Russian docs. RAGTIME: 4 collections of ~1M each, 13 teams, 125 runs. | The mixed-language corpus modelled as a TREC task with pooled judgments. Best MLIR nDCG@20 0.545 vs 0.664/0.698/0.593 for the single-language CLIR tasks — the degradation is measured, not hypothetical. |

Two more that decide design questions directly. [LAReQA (EMNLP 2020)](https://aclanthology.org/2020.emnlp-main.477/)
has evaluated retrieval from a **mixed-language candidate pool** for six years and introduced the
weak-vs-strong alignment distinction that explains the bug: on XQuAD-R, training on translated data with
monolingual positive pairs (X-X, mAP 0.23) is *worse* than English-only training (0.29); only X-Y
training, which forces the model to accept a foreign-language answer as correct, fixes it (0.66).
And [MLAIRE](https://arxiv.org/abs/2605.07249) shows semantic retrieval quality and query-language
preference are near-orthogonal and often anti-correlated across 31 retrievers (nDCG/LPR Pearson −0.28
to −0.38): multilingual-e5-large 96.15% nDCG at 99.92% Language Preference Rate, Qwen3-Embedding-8B
68.64% nDCG at 53.00% LPR.

---

## What is actually still open

Ranked by how well the three gap analyses support each claim.

**1. Your 80/80-at-rank-1 across 40 languages is the weakest part of the claim, not the strongest.**
All three analyses converge on this; the third states it most directly. MLAIRE exists precisely because
standard retrieval metrics conflate cross-lingual semantic skill with query-language preference, and on a
single-script corpus the two are indistinguishable by construction — which is your test condition, and
which is why the mixed corpus broke it. No published cross-lingual retrieval result is anywhere near
100% rank-1 across 40 languages under comparable conditions: XOR-Full SOTA is 42.4 F1
([CLASS](https://aclanthology.org/2024.emnlp-main.770/)); AfriQA's best end-to-end XOR-Full is ~23.0 F1
with purely cross-lingual mDPR at 19.0% Recall@10 ([arXiv:2305.06897](https://arxiv.org/abs/2305.06897));
IndicGenBench's XorQA-In-Xx tops out at 37.4 Token-F1 for PaLM-2-L over 28 Indic languages
([arXiv:2404.16816](https://arxiv.org/abs/2404.16816)). Fix this first — it is not a gap, it is a
measurement defect with off-the-shelf instruments (XOR-Retrieve, LAReQA's mixed pool, MLAIRE's LPR).

**2. A retrieval-score-conditioned translation trigger, reported as a cost curve.**
Genuinely unpublished, per all three analyses, with clean negative searches. Published gates exist but
trigger on other signals: [Syfer](https://arxiv.org/abs/2608.13160) fires its English pathway only when
`cos(filled sub-question, original query) < 0.8` (worth +8.91 F1 on MuSiQue);
[CORAL](https://arxiv.org/abs/2604.25676) gates on an LLM sufficiency critic. Every strategy paper is
unconditional in its expensive step. The empirical justification for gating is real and measured:
[INDIC QA Benchmark](https://arxiv.org/abs/2407.13522) shows translate-test nearly *doubles* Assamese
extractive F1 (33.01 vs 21.29) while nearly *halving* Hindi (26.22 vs 46.76), and
[arXiv:2507.22923](https://arxiv.org/abs/2507.22923) finds every translation strategy degraded Hindi with
Llama-3.1-8B by up to 10.9 points. But this is a cost optimisation, not a quality gain — the honest
framing is "36 calls instead of 80," not "new capability."

**3. Answer-language policy as a configurable, enforced, measured control surface.**
The most defensible item, and the one all three analyses rate highest as a *product* gap and lowest as a
*research* one. Verified absent from every framework and eval library checked: LangChain's retrieval docs
mention no multilingual or translation handling; LlamaIndex ships no language node-postprocessor;
[Vespa states in writing](https://docs.vespa.ai/en/linguistics.html) that it "does not out-of-the-box
support cross-lingual retrieval"; [Azure AI Search](https://docs.azure.cn/en-us/search/search-language-support)
admits it has no mechanism for determining the query's language; RAGFlow ships cross-language *search*
but is silent on answer language; [RAGAS](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/)
documents no language-consistency metric at all. Worse,
[Haystack's own tutorial](https://haystack.deepset.ai/tutorials/32_classifying_documents_and_queries_by_language)
ships your bug as the documented default: "The language of a question is detected, and only documents in
that language are used to generate the answer." The research treats answer language as fixed by the task
(XOR-Full pins it; [BordIRLines](https://arxiv.org/abs/2410.01171) forces English; RAGTIME requires
English reports with no wrong-language penalty). Every component to build it exists off the shelf.

**4. A per-query router over the published strategy space.**
Analysis two rates this highest ("research problem," medium-high confidence); the others treat it as
downstream of the gate work. The precondition is proven twice — there is no universally best strategy,
and the winner flips by model *and* language (arXiv:2507.22923: Qwen2.5-7B gains +6.6 on French while
losing −12.8 on Hindi) — and [DELTA](https://arxiv.org/abs/2601.02956) notes its own gains vanish when
the query is already English. Nobody routes across *strategies*;
[DS@GT](https://arxiv.org/abs/2607.22841) routes across *indexes and generator models*. The bar is high:
CrossRAG averages +17.8% over monolingual RAG, so a router must beat always-picking-CrossRAG.

**5. Romanized and code-mixed input — a second, larger hole in the same gate.**
A Unicode script check cannot see Hinglish; "mera order kahan hai" is Latin script, so both gates stay
shut. [IndicLID / Bhasha-Abhijnaanam](https://aclanthology.org/2023.acl-short.71/) exists for exactly
this but the asymmetry is the warning: 98.55% accuracy on native script, 80.40% on romanized.
[Script Gap](https://arxiv.org/abs/2512.10780) measures up to 24 points of LLM degradation from
romanization across five Indian languages, and
[Lost in Transliteration](https://arxiv.org/abs/2505.08411) shows BGE-M3 losing 97% of MRR@10 on
Latinized Chinese (0.2342 → 0.0078). Counterpoint worth testing before "fixing" it:
[MiLQ](https://arxiv.org/abs/2505.16631) finds mixed-language queries retrieve English documents far
*better* than native-script ones (BM25 MAP@100 38.35 vs 12.35).

**6. A Hindi-question-over-English-corpus retrieval benchmark.** None exists. XOR-TyDi's only Indic
languages are Bengali and Telugu. [IndicGenBench XorQA-In-Xx](https://arxiv.org/abs/2404.16816) has the
right shape across 28 languages but *supplies* the gold English passage, so there is no index.
[IndicRAGSuite](https://arxiv.org/abs/2506.01615) is explicitly monolingual (queries translated into the
corpus language). [HEALTH-PARIKSHA](https://arxiv.org/abs/2410.13671) has exactly the right setup —
English-only knowledge base, Hindi/Tamil/Telugu/Kannada queries, an explicit answer-language instruction
in the prompt — but only 19 Hindi pairs out of 749. Dataset work, real community value, not a framework.

### Where the analyses disagree, and who is better supported

- **Keep, fix, or scrap the script gate?** Analysis two says scrap it outright; analysis one says it is
  probably a harmful heuristic; analysis three treats it as a leaky component to shore up. **Scrapping
  is better supported.** [BordIRLines](https://arxiv.org/abs/2410.01171) finds retrieving *multilingual*
  documents beats purely in-language retrieval on both response consistency (Command-R 64.2 → 78.7) and
  geopolitical bias (28.7 → 5.9) across 49 languages; Chirkova et al. find the concatenated multilingual
  corpus beneficial in most cases; [arXiv:2604.20531](https://arxiv.org/abs/2604.20531) finds a fixed
  50/50 English/target split beats English-only retrieval for low-resource languages (Basque 76.0% vs
  68.18%, Kazakh 75.73% vs 66.93%). Gating the cross-lingual path *off* because the query's script is
  present in the corpus is not an unexploited idea; it is the direct cause of the mixed-corpus bug.
- **Build per-language sub-searches and fusion, or fix the index?** Analyses one and two present routing
  as the published fix; analysis three argues against building routing before testing cheaper options.
  **Analysis three is better supported.** [SHIFT](https://arxiv.org/abs/2606.18801) subtracts a mean
  language-offset vector from document embeddings *at index time only* — zero query-time cost, no
  retraining — lifting multilingual-e5-large nDCG@20 from 0.633 to 0.737 across four benchmarks;
  [LangSAE](https://arxiv.org/abs/2601.04768) suppresses language-identity latents and reconstructs to
  the original dimensionality so existing vector DBs still work (Belebele nDCG@20 0.5359 → 0.6534,
  Chinese +104.3%). [DELTA](https://arxiv.org/abs/2601.02956) explicitly evaluated per-language
  sub-search and *rejected* it on cost, fusing one enriched query instead. And if you do build fusion,
  [Savoy & Berger (CLEF 2004)](https://ceur-ws.org/Vol-1170/CLEF2004wn-adhoc-SavoyEt2004.pdf) is the
  warning: raw-score merging collapses −73% MAP when per-language runs use different engines, while
  logistic regression on ln(rank)+RSV wins by +28–44%.
- **How novel are the gates?** Analysis one rates them medium and near-worthless; two rates the
  similarity gate medium with clean negative searches; three barely treats them as a gap. **Medium is
  right**: the searches are clean, but Syfer and CORAL are one signal away, and the contribution is a
  cost curve, not a capability.

---

## Files in this folder

| File | Covers |
|---|---|
| `README.md` | This entry point: the verdict, the ten works that matter most, the open list, the build recommendation. |
| `01-prior-art.md` | The task lineage — XOR QA, CORA, CLASS, MIA 2022, AfriQA — and the shipped/deployed systems that already implement the product shape (RAGFlow, the Nigerian Pidgin prosthetic-manual RAG, the Bengali agricultural advisory, HEALTH-PARIKSHA). Where Oreag's mechanism sits in the published taxonomy. |
| `02-retrieval-and-embeddings.md` | The retrieval layer: BGE-M3, multilingual-E5, ColBERT-X / Translate-Distill, mContriever, LaBSE. Query translation vs document translation vs shared embedding space, back to Oard 1998 / McCarley 1999 / PSQ 2003. Language identity in embedding space (self-language bias, LIR, SHIFT, LangSAE) and low-resource / script degradation. |
| `03-answer-language-control.md` | Language confusion and language drift: the benchmarks (LCB, XRAG, Language Confusion Entropy) and the full mitigation stack from prompt engineering through decoding-time constraints (SCD, LCG, LATB) to steering (ReCoVeR, ITLC) and training (PLUG, ORPO, TLPO). Why prompting alone is the weakest option. |
| `04-mixed-language-corpora.md` | The open limit as a named field: MLIR, centralized-vs-distributed indexes, the CLEF results-merging literature, TREC NeuCLIR/RAGTIME, and the modern fixes — balanced retrieval, dual-query merge, per-language RRF, reranker alignment (LAURA, LAMAR), index-side de-biasing (SHIFT, LangSAE), score-comparable training (MTD). |
| `05-benchmarks-and-evaluation.md` | What to measure and with what: XOR-Retrieve/XOR-Full, MKQA, MIRACL (monolingual control), LAReQA, MLAIRE, NeuCLIRBench, XRAG, MIRAGE-Bench, NoMIRACL, XOR-AttriQA, MEMERAG, BERGEN. Language-ID instruments and their failure on code-switched output. Why the 80/80 number is not comparable to anything published. |
| `06-frameworks-and-tooling.md` | What is buyable and what you must write: RAGFlow, Haystack, LangChain, LlamaIndex, Elastic, Azure AI Search, Vespa, Weaviate, Vertex AI Search, kapa.ai — feature by feature against the five target behaviours, including the vendor statements that disclaim cross-lingual retrieval outright. |
| `07-gap-analysis.md` | The three independent gap analyses in full, their disagreements, and the evidence weighing each. The searches that returned zero, and the tooling limits that shaped what could be verified. |

---

## If you build it, build this part

**Do not build the retriever, the mixed-corpus fix, or the language enforcer.** All three are published,
and in each case the off-the-shelf option beats what you would write.

Order of work, highest leverage first:

1. **Re-measure before anything else.** Run the current pipeline on
   [XOR-Retrieve/XOR-Full](https://github.com/AkariAsai/XORQA) and on
   [LAReQA's mixed-language pool](https://aclanthology.org/2020.emnlp-main.477/), and report
   [MLAIRE's Language Preference Rate](https://arxiv.org/abs/2605.07249) alongside nDCG. This is what
   separates "our retriever understands Hindi" from "our corpus had one script." It also makes the number
   comparable to published work for the first time.
2. **A/B the whole cross-lingual path against a stronger encoder with no translation.** Put
   [BGE-M3](https://aclanthology.org/2024.findings-acl.137/) or
   [multilingual-e5-large-instruct](https://arxiv.org/abs/2502.13595) behind the same queries with both
   gates forced shut. If the untranslated path closes the gap — as it did on Sinhala/Tamil
   ([96.2% R@15 vs 92.4% for Google-Translate query translation](https://arxiv.org/abs/2608.12820)) and
   on CLIRudit (0.580 MAP untranslated vs 0.600 with *gold human* translation, and query translation
   actively degrading dense models, [arXiv:2504.16264](https://arxiv.org/abs/2504.16264)) — then the 36
   model calls and both gates are dead weight and the rest of this list shrinks.
3. **Fix the mixed corpus at index time, not with routing.** Try
   [SHIFT](https://arxiv.org/abs/2606.18801) first: language vectors are per language *pair*, so they can
   be precomputed once globally from parallel data and applied to any tenant's index at ingest, which is
   what makes it viable for small per-tenant corpora that have no parallel data of their own. If that is
   not enough, add a language-aware reranker ([LAMAR](https://arxiv.org/abs/2607.22042), which reports
   existing multilingual rerankers putting a non-English document first 72.8% of the time for English
   queries). Only if both fail should you build per-language shards and fusion — and then copy
   [DS@GT's constants](https://arxiv.org/abs/2607.22841) (weighted RRF, `w_lang=2.0`, `w_global=1.0`,
   `k=60`) rather than inventing merge weights, and heed Savoy's warning about score comparability.
4. **Own the answer-language policy.** This is the one genuinely unserved thing on the list. Ship it as a
   real object — tenant default, per-query override, detected-query-language fallback, with explicit
   precedence — enforce it (prompt-side is the [Chirkova recipe](https://aclanthology.org/2024.knowllm-1.15/):
   translate the prompt into the user's language *and* instruct explicitly, worth >95% correct-language
   rate; decode-side is [SCD](https://arxiv.org/abs/2511.09984) or
   [LCG](https://arxiv.org/abs/2510.17555) if you self-host and can touch logits), and *measure* it with
   a sentence-level language check, not a whole-response one — a whole-response detector passes a
   code-switched Hindi/English answer.
5. **Then, if you still want the gate, publish it as a cost curve.** Retrieval quality as a function of
   how often the expensive path fires, on XOR-TyDi or XRAG's mixed condition, with call counts logged.
   That is a real, unclaimed, short systems contribution — and it is honest about being an efficiency
   result rather than a capability one. Replace the LLM translation call on the critical path with a
   local model ([IndicTrans2](https://github.com/AI4Bharat/IndicTrans2) or NLLB-200-distilled-600M)
   before measuring, or you are measuring the wrong constant.

One thing to stop asserting: that keeping the original question in the generation prompt reliably returns
the answer in the user's language. It helps — [arXiv:2406.16135](https://arxiv.org/abs/2406.16135)
measures a 10–13 point reasoning penalty from language-mixed inputs (GPT-4 81.82 → 68.61 on mixup MMLU),
which is a genuine argument for your choice — but it does not control output language.
[arXiv:2504.00597](https://arxiv.org/abs/2504.00597) calls the residual "an inherent decoding limitation"
that survived both a two-step prompt and larger models.
