# Prior art: question in language B, evidence in language A, answer in language B

Scope: cross-lingual open-retrieval QA (XOR-style) and cross-lingual / multilingual RAG
systems. This file is the annotated bibliography of work that does the **exact** target
behaviour, plus the near-misses that bound what can be claimed about it.

**The target, restated for grading purposes:**

| # | Behaviour |
|---|---|
| 1 | Corpus embedded in language A |
| 2 | Question asked in language B |
| 3 | Retrieval surfaces the semantically correct language-A passage (real semantics, not keyword/MT fallback) |
| 4 | Answer generated in language B, grounded in the language-A evidence |
| 5 | Explicit language policy: pin an answer language, or match the query |

**Verdict up front.** Behaviours 1–4 are a named task with a 2021 benchmark
([XOR-Full](https://aclanthology.org/2021.naacl-main.46/)), a canonical system that solves
it end to end without any translation hop
([CORA](https://arxiv.org/abs/2107.11976), NeurIPS 2021, 26 languages), a 16-language
shared task ([MIA 2022](https://aclanthology.org/2022.mia-1.11/)), and a continuous line of
work through 2026. Oreag's specific mechanism — translate the question, embed the
translation, retrieve, generate from the original — has a published name, **tRAG**, and in
the four-way comparison that named it, it comes **last**
([arXiv:2504.03616](https://arxiv.org/abs/2504.03616)). Behaviour 5 is the only one that is
thin, and even there the measurement instruments exist. The mixed-language-corpus limit is
the *most* crowded corner, not an open frontier — see §3.

Authors are named only where the source data verified them; elsewhere the entry gives
year and venue only.

---

## 0. Papers that do the FULL target (1–4), at a glance

| Work | Year | Retrieval mechanism | Answer language | Notes |
|---|---|---|---|---|
| [XOR QA / XOR-Full](https://aclanthology.org/2021.naacl-main.46/) | 2021 | task definition; MT+DPR baseline | question's language | defines the task; the MT baseline **is** Oreag's architecture |
| [CORA](https://arxiv.org/abs/2107.11976) | 2021 | mDPR over mixed-language collection | generated directly in target language | **no translation module at all** |
| [GenTyDiQA / cross-lingual answer-sentence generation](https://aclanthology.org/2022.aacl-main.27/) | 2022 | multilingual passages incl. foreign | full-sentence, question's language | mixing evidence languages helps in 3 of 5 langs only |
| [MIA 2022 shared task](https://aclanthology.org/2022.mia-1.11/) | 2022 | CORA-style baseline + entity-aware retrieval | question's language | 16 languages, 4 teams |
| [AfriQA](https://arxiv.org/abs/2305.06897) | 2023 | mDPR vs MT query translation | question's language | hardest published setting; translation-free retrieval collapses |
| [CLASS](https://aclanthology.org/2024.emnlp-main.770/) | 2024 | single enc-dec, retrieval + generation | query language | beats CORA by ~+7.8 F1, still no MT |
| [Chirkova et al. mRAG](https://aclanthology.org/2024.knowllm-1.15/) | 2024 | BGE-m3 over concatenated multilingual Wikipedia | prompt-forced user language | 13 langs; closest thing to a reference implementation |
| [DKM-RAG](https://arxiv.org/abs/2502.11175) | 2025 | multilingual retrieval → translate passages | query language | translates the *passages*, not the query |
| [tRAG / MultiRAG / CrossRAG](https://arxiv.org/abs/2504.03616) | 2025/26 | four strategies benchmarked head-to-head | query language, measured with OpenLID | names and ranks Oreag's mechanism |
| [XRAG](https://arxiv.org/abs/2505.10089) | 2025 | monolingual-EN and multilingual retrieval | scored as Response Language Correctness | the benchmark for behaviours 4–5 |
| [Cross-Lingual Cost (Arabic–English)](https://arxiv.org/abs/2507.07543) | 2025 | mixed AR+EN corpus, one index | same language as query | **Oreag's open limit, published, with both fixes** |
| [QTT-RAG](https://arxiv.org/abs/2510.23070) | 2025 | retrieve EN, translate, tag translation quality | pinned in prompt to query language | quality metadata instead of rewriting |
| [TREC 2024 NeuCLIR, Report Generation](https://arxiv.org/abs/2509.14355) | 2025 | CLIR over ZH/FA/RU | English reports (so 1–3 only) | TREC-grade judgments |
| [Bengali agricultural advisory](https://arxiv.org/abs/2601.02065) | 2026 | translate query → EN FAO/IRRI corpus → back-translate | Bengali | full deployed pipeline, commodity parts |
| [Prosthetic-manual RAG](https://arxiv.org/abs/2506.23958) | 2025 | upload EN manuals, MT query, retrieve, MT answer | Nigerian Pidgin | Oreag's product shape, verbatim |
| [HEALTH-PARIKSHA](https://arxiv.org/abs/2410.13671) | 2024 | English-only KB, Indic queries | explicit `{response_lang}` instruction | real Hindi/Tamil/Telugu/Kannada patient queries |
| [DELTA](https://arxiv.org/abs/2601.02956) | 2026 | one fused query (EN pivot + native + title bridge) | query language | argues *against* replacing the query with its translation |
| [LAURA](https://arxiv.org/abs/2604.20199) | 2026 | utility-aligned multilingual reranker | query language | per-language grouping at rerank stage |
| [CroSearch-R1](https://arxiv.org/abs/2604.25182) | 2026 | multi-turn: local collection first, then global | query language | per-language sub-search + routing, RL-trained |
| [LcRL](https://arxiv.org/abs/2601.14896) | 2026 | language-coupled RL over search | Correct Language Rate 99.1% | language consistency as a first-class reward |
| [TR-RAG](https://arxiv.org/abs/2607.02966) | 2026 | English-evidence regime, RL + teacher anchor | query language, reward-enforced | reward = lang consistency + 3-gram recall + judge |
| [Syfer](https://arxiv.org/abs/2608.13160) | 2026 | decompose natively; English path **only if** a cosine check fails | target language | the closest published thing to Oreag's gate |
| [Cross-lingual evidence in medical QA](https://arxiv.org/abs/2604.20531) | 2026 | fixed 50/50 EN + target-language retrieval | query language | fusion beats English-only for low-resource |

---

## 1. Cross-lingual open-retrieval QA — the task and its canonical systems (2020–2024)

### [XOR QA: Cross-lingual Open-Retrieval Question Answering](https://aclanthology.org/2021.naacl-main.46/)
NAACL 2021 (Asai et al.; preprint [arXiv:2010.11856](https://arxiv.org/abs/2010.11856);
code [github.com/AkariAsai/XORQA](https://github.com/AkariAsai/XORQA)).
Defines the task of answering a question asked in one language using answer content
retrieved from another. ~40k information-seeking questions across 7 non-English languages
(Ar, Bn, Fi, Ja, Ko, Ru, Te), built by re-annotating ~5k TyDi QA questions that had **no**
same-language answer; answerable coverage in Bengali rises 42% → 82% (+22 pts averaged
over 7 languages). Three formulations: XOR-Retrieve, XOR-EnglishSpan, XOR-Full.
**Key finding:** the strongest end-to-end XOR-Full baseline — MT the question, retrieve over
English Wikipedia (Google Search + DPR), generate, translate back — reaches only
**18.7 F1 / 12.1 EM / 16.8 BLEU** against ~40 F1 for comparable monolingual English
systems. On XOR-Retrieve, query-translation quality dominates: R@5kt 72.1 with human
translations, 67.2 with Google MT, **50.0** with an in-house MT system (R@2kt 65.1 / 64.3 /
43.5).
**Bearing:** XOR-Full is behaviours 1–4 stated as a benchmark five years ago, and its
weakest published baseline is Oreag's architecture. This, not a bespoke 80-query set, is
where the 80/80-at-rank-1 number should be re-measured.

### [One Question Answering Model for Many Languages with Cross-lingual Dense Passage Retrieval (CORA)](https://arxiv.org/abs/2107.11976)
NeurIPS 2021 (Asai et al.; code [github.com/AkariAsai/CORA](https://github.com/AkariAsai/CORA)).
mDPR retrieves from a multilingual collection for a question in any language; mGEN, a
multilingual autoregressive generator, "answers directly in the target language **without
any translation** or in-language retrieval modules as used in prior work." Iterative
training mines cross-lingual positives via Wikipedia link structure.
**Key finding:** +23.4 F1 on XOR-TyDi and +4.7 F1 on MKQA over prior SOTA, 26 target
languages including 9 with zero training data (~30 F1 on unseen languages, +5.4 over
baseline).
**Bearing:** the full target, solved in 2021, by deliberately *removing* the translation hop
Oreag treats as the core mechanism. One multilingual retriever over one mixed-language
collection — i.e. it also does not route per language.

### [Cross-Lingual Open-Domain Question Answering with Answer Sentence Generation](https://aclanthology.org/2022.aacl-main.27/)
AACL 2022. Generative cross-lingual QA producing **full-sentence** answers "by exploiting
passages written in multiple languages, including languages different from the question."
Releases GenTyDiQA (Ar, Bn, En, Ja, Ru).
**Key finding:** beats answer-sentence-selection baselines in all 5 languages, but beats the
*monolingual* generative pipeline in only **3 of 5** — feeding the generator foreign-language
passages alongside same-language ones helps some languages and hurts others.
**Bearing:** the earliest direct evidence that mixing evidence languages in the prompt is not
unconditionally good. Relevant to any fusion design that ends up putting English and Hindi
passages in the same context window.

### [MIA 2022 Shared Task: Evaluating Cross-lingual Open-Retrieval QA for 16 Diverse Languages](https://aclanthology.org/2022.mia-1.11/)
MIA workshop @ NAACL 2022; task repo
[github.com/mia-workshop/MIA-Shared-Task-2022](https://github.com/mia-workshop/MIA-Shared-Task-2022).
Community evaluation over 16 typologically diverse languages, adapting XOR-TyDi and MKQA
plus new Tagalog and Tamil annotation.
**Key finding:** best constrained system 31.6 avg F1 (+4.1 over a CORA-style baseline) using
**entity-aware contextualized representations** for retrieval; best unconstrained 32.2
(+4.5). On Tamil the winner scores 20.8 F1 where most systems score near zero.
**Bearing:** catastrophic failure in low-resource scripts is predicted by missing entity /
lexical signal, not by script presence — a sharper diagnostic than Oreag's script gate.

### [AfriQA: Cross-lingual Open-Retrieval QA for African Languages](https://arxiv.org/abs/2305.06897)
2023; data [github.com/masakhane-io/afriqa](https://github.com/masakhane-io/afriqa).
12,239 questions / 8,892 answerable pairs over Bemba, Fon, Hausa, Igbo, Kinyarwanda,
Swahili, Twi, Wolof, Yoruba, Zulu, pivoting to English (8) and French (Wolof, Fon).
**Key finding:** translation-free cross-lingual dense retrieval (mDPR) gets **19.0% R@10**
average, vs 62.4% with Google-Translate query translation and 67.6% with human question
translation (hybrid sparse+dense with human translation: 73.4%). Best end-to-end XOR-Full
F1 ~23.0% (Google Translate + mDPR), ~16.3% with NLLB.
**Bearing:** the hard counterweight to "just use a multilingual embedder." At the
low-resource end, query translation is worth ~43 points of recall. Also the reason a
40-language 80/80 claim needs re-measuring: this is what the same task shape looks like on
languages that are genuinely underserved.

### [Pre-training Cross-lingual Open Domain QA with Large-scale Synthetic Supervision (CLASS)](https://aclanthology.org/2024.emnlp-main.770/)
EMNLP 2024 main. A single encoder-decoder doing "cross-lingual retrieval from a multilingual
knowledge base, followed by answer generation in the query language," trained purely on
synthetic supervision mined from Wikipedia cross-lingual links (cloze queries for retrieval,
generated natural questions for generation). **No MT component.**
**Key finding:** XOR-Full 42.4 F1 / 32.7 EM vs CORA's 34.7 / 25.8; cross-lingual retrieval
R@2kt 71.6 / R@5kt 78.2 vs CORA's 69.3 / 76.5. Its zero-shot variant beats *supervised*
CORA on MKQA across 20 unseen languages.
**Bearing:** current published SOTA shape for the full target, and it is translation-free.
Any claim that the translate-the-query path is necessary has to beat this.

---

## 2. Multilingual RAG: the pipeline taxonomy (2024–2026)

This is where Oreag's design gets named and ranked.

### [Retrieval-augmented generation in multilingual settings](https://aclanthology.org/2024.knowllm-1.15/)
Chirkova et al., KnowLLM workshop 2024 (preprint
[arXiv:2407.01463](https://arxiv.org/abs/2407.01463); library
[github.com/naver/bergen](https://github.com/naver/bergen)).
An mRAG pipeline across 13 languages where both queries and collections span languages,
released publicly.
**Key findings:** (a) they ablate corpus composition — English-only vs user-language-only vs
**concatenated multilingual** Wikipedia — and find retrieval from the *concatenated* corpus
beneficial in most cases with a single BGE-m3 retriever, i.e. one shared index rather than
per-language routing; (b) Command-R-35B with a default English prompt answered in English
for **~50%** of non-English queries when retrieving from English Wikipedia; translating the
prompt into the user language plus an explicit "generate the response in the user language"
instruction raises Correct Language Rate to **>95%**, though named-entity code-switching
persists in non-Latin scripts.
**Bearing:** the closest thing to a reusable reference implementation of Oreag's whole
pipeline, and the paper that tested the mixed-corpus question and concluded routing was not
needed. Also the source for the prompt recipe that beats bare prompt construction.

### [Investigating Language Preference of Multilingual RAG Systems (DKM-RAG)](https://arxiv.org/abs/2502.11175)
ACL 2025 Findings; code
[github.com/jeonghyunpark2002/LanguagePreference](https://github.com/jeonghyunpark2002/LanguagePreference).
Measures language preference separately in retrieval and generation. Introduces **MLRS**
(MultiLingualRankShift): how much a document's rank improves when it is translated into the
query language. Method: retrieve multilingually, **translate the reranked passages into the
query language**, and fuse them with LLM-rewritten passages carrying parametric knowledge.
**Key findings:** retriever preference English 47.70 vs 35–38 for every other language.
Char-3gram recall on MKQA/KILT with BGE-m3: Korean queries, all-language retrieval 40.60,
Korean-only 49.66, DKM-RAG **55.01**; Chinese 32.55 → 44.57. Ablation shows both halves are
needed. Scope limit: only 3 query languages (en, ko, zh) against 8 passage languages.
**Bearing:** MLRS is a directly reusable diagnostic for the mixed-corpus bug — it measures
exactly "does this document get promoted just for being in the query's language." And the
comprehension gap sits at the *generator*, not only the retriever, which Oreag's design
does not address.

### [Multilingual Retrieval-Augmented Generation for Knowledge-Intensive Task (tRAG / monoRAG / MultiRAG / CrossRAG)](https://arxiv.org/abs/2504.03616)
Ranaldi et al.; preprint 2025, published as
[Findings of EACL 2026](https://aclanthology.org/2026.findings-eacl.35/).
Names and benchmarks four designs: **tRAG** (translate the question, retrieve English),
**monoRAG** (retrieve in the query language), **MultiRAG** (retrieve from one mixed
multilingual index), **CrossRAG** (retrieve multilingually, then translate the *retrieved
documents* into a common language before generation). Evaluated on MKQA / MLQA / XOR-TyDi
with GPT-4o, Llama-3-8B, Command-R class backbones and an explicit instruction to answer in
the query language.
**Key findings:** GPT-4o flexible-EM on MKQA: no-RAG ~43% → **tRAG 46.5%** → monoRAG 51.5%
→ MultiRAG 53.1% → **CrossRAG 60.4%**. CrossRAG beats tRAG by +13.9 (MKQA) and +9.0 (MLQA),
and beats MultiRAG by +3.8 / +1.3. Averaged gains over monolingual RAG: tRAG +8.9%,
MultiRAG +14.3%, CrossRAG +17.8% (GPT-4o). Response-language correctness measured with
**OpenLID**: CrossRAG generates in the correct language consistently more often than
MultiRAG — document-side translation fixes the wrong-language failure that a mixed-language
retrieval set induces. The abstract attributes tRAG's weakness to limited retrieval scope
(English only) and to incorrect query translations causing wrong retrieval.
**Bearing:** this is the single most important paper for Oreag. Its mechanism is Oreag's
mechanism, it has a name, it loses, and the winning alternative (normalise the *context*
language, not the query language) is untried. It also supplies the correct A/B baseline and
the correct metric for step 4.

### [XRAG: Cross-lingual Retrieval-Augmented Generation](https://arxiv.org/abs/2505.10089)
2025 (Amazon Science; data/code
[github.com/amazon-science/XRAG](https://github.com/amazon-science/XRAG)).
Benchmark built from News Crawl (Jun–Nov 2024) for the setting "where the user language does
not match the retrieval results," with relevancy annotations. 5 languages (EN, DE, ES, ZH,
AR), ~1,000 verified QA pairs per language pair. Two conditions: non-English question over
English-only documents, and over a **mixed** English + question-language document set.
**Key findings:** in the monolingual-retrieval setting **all** evaluated models struggle with
**response language correctness** — a previously unreported issue. Share of answers wrongly
returned in English instead of the user's language: ~5% GPT-4o and Command-R+, ~15% Claude
3.5 Sonnet, ~35% Mistral-large. GPT-4o scores 6.3% without retrieval vs 85% human accuracy,
so the questions genuinely require the corpus. In multilingual retrieval, the harder problem
is reasoning across languages, not generating non-English text.
**Bearing:** the only benchmark that treats behaviours 4 and 5 as first-class metrics, and
its mixed-corpus condition is a ready-made harness for Oreag's open limit. Its headline
result is the direct external check on "keeping the original question in the prompt makes
the answer come back in the user's language" — that assumption fails 5–35% of the time
depending on the generator.

### [Quality-Aware Translation Tagging in Multilingual RAG (QTT-RAG)](https://arxiv.org/abs/2510.23070)
2025. Retrieves English documents, translates them into the query language, scores each
translation on semantic equivalence, grammatical accuracy, and naturalness/fluency (0.0–5.0),
and attaches those scores as **metadata without rewriting the content** — avoiding the
factual distortion that rewriting introduces. BGE-M3 as both retriever and reranker;
documents already in the query language pass through untouched. Generation prompt pins the
language verbatim: *"Always answer as briefly and accurately as possible, and respond only in
{query language}."*
**Key findings:** Wikipedia corpus (25M EN, 1.6M KO, 1.5M FI, 11M ZH), queries in KO/FI/ZH.
Best Korean XOR-TyDi 43.8% vs 42.0% for CrossRAG; MKQA-ko 40.0% vs 36.4% for DKM-RAG;
average gains 3.8–12.6% on MKQA-ko but near-flat on Chinese — because only 5% of Chinese
retrievals were cross-lingual documents vs 22.7% for Korean.
**Bearing:** the cross-lingual gain is proportional to how often the cross-lingual path
actually fires. That is the strongest published argument *for* gating — and the strongest
argument that the gain from any such path must be reported per language, not as an average.

### [CroSearch-R1](https://arxiv.org/abs/2604.25182)
2026. RL (GRPO) search-augmented framework with a **multi-turn retrieval policy that
prioritises the query-language ("local") collection on turn one, then expands to
other-language ("global") collections for complementary evidence on later turns.** Stack:
multilingual-E5 retriever + NLLB-200-distilled-600M to translate retrieved documents into a
unified space, Qwen2.5-3B/7B-Instruct generator.
**Key finding:** MKQA (en/fr/th/ar) with Qwen2.5-7B beats Search-R1 on every language —
en 72.07 vs 69.43 fEM, fr 59.67 vs 57.91, th 27.83 vs 25.29, ar 24.12 vs 18.65 (avg 45.92 vs
42.82).
**Bearing:** per-language sub-searches with routing, published and trained — the architecture
Oreag lists as the unbuilt fix. Note the routing order is the *opposite* of a script gate:
it always starts local and always expands, rather than deciding whether to expand.

### [Language-Coupled Reinforcement Learning for Multilingual RAG (LcRL)](https://arxiv.org/abs/2601.14896)
2026. Language-coupled group sampling in the rollout module plus an anti-consistency penalty
in the reward model, for multilingual search-engine interaction.
**Key finding:** reports **Correct Language Rate** alongside accuracy — 99.1% CLR vs 95.6%
for mSearch-R1 on MKQA with Qwen2.5-3B-Instruct, with 41.2% vs 37.9% flexible-EM and 57.0%
vs 53.2% c3Recall; Qwen3-8B gains +7.0pp fEM and +12.4pp c3Recall on MKQA, +10.5pp fEM on
XOR-TyDi.
**Bearing:** CLR is the metric name to adopt for behaviour 4. 95–99% is the current bar;
anything reported without a CLR number is not comparable.

### [Distill Where the Student Goes: Teacher-Regularized RL for English-Evidence Cross-Lingual RAG (TR-RAG)](https://arxiv.org/abs/2607.02966)
2026. Setting stated as "users query in diverse languages but retrieved passages remain
English" and the system must answer in the query language — i.e. Oreag's setting exactly.
Reward decomposes into **language consistency + character 3-gram recall + LLM-judge
evidence-grounded correctness**; on-policy distillation on student-visited prefixes with a
frozen teacher and reverse-KL anchor.
**Key finding:** the teacher anchor prevents language-consistency collapses of **up to ~27
percentage points** that reward-only RL suffers (it can drift *below* the base model). A
compact student sometimes beats its 70B teacher on char-3gram recall. Evaluated on
BioASQ-ENKB5, Hotpot-ENKB5, MKQA.
**Bearing:** the reward decomposition is the cleanest published statement of what "grounded
answer in the right language" means as three separable, measurable things.

### [Better Decomposition, Free Aggregation: Syfer](https://arxiv.org/abs/2608.13160)
2026. Multi-hop multilingual QA. A format-constrained decomposer generates sub-questions in
the **original** language; a quality check decides what happens next. **If the check passes,
sub-questions are answered by retrieval in the target language with no English translation.
If it fails, the English translation pathway activates** with bilingual sub-question graph
alignment. Final answers in the target language.
**Key finding:** the translation gate is a single cosine threshold — the English pathway
fires only when `cos(e(q_filled), e(Q)) < tau`, `tau = 0.8`. +8.91 F1 (+29.8% relative) on
MuSiQue over the strongest decomposition baseline across nine languages; +17.3 F1 / +20.1 EM
on 2WikiMultiHopQA.
**Bearing:** the closest published analogue to Oreag's conditional gate. It differs only in
what is scored (sub-question drift, not retrieval score), which means "conditionally invoke
the cross-lingual path" is a published design pattern, not an invention.

### [CORAL: Adaptive Retrieval Loop for Culturally-Aligned Multilingual RAG](https://arxiv.org/abs/2604.25676)
2026 (COntext-aware Retrieval with Agentic Loop). Iterative: select corpora → retrieve →
critique evidence for relevance and cultural alignment → check sufficiency → if insufficient,
reselect corpora and rewrite the query.
**Key finding:** maintains **separate per-language Wikipedia indexes** and does
query-conditioned corpus selection (e.g. Indonesian alongside Sundanese) instead of one
pooled index, beating monoRAG, tRAG, multiRAG and crossRAG: 61.83% vs 57.83% on BLEnD
low-resource (+3.58pp) and 58.88% vs 53.75% on CLIcK, with Llama-3.2-3B generating and
Qwen3-235B planning.
**Bearing:** the agentic version of Oreag's two gates — a critic decides sufficiency instead
of a similarity threshold, and the fallback is *corpus reselection*, which is the fix for the
mixed-corpus case. Marked a near-miss only because it does not report answer-language policy.

---

## 3. The mixed-language corpus — the "known open limit", already published

This is the section to read before writing any routing code.

### [The Cross-Lingual Cost: Retrieval Biases in RAG over Arabic-English Corpora](https://arxiv.org/abs/2507.07543)
Amiraz et al., 2025 (ArabicNLP). Builds benchmarks over all combinations of query language
and supporting-document language on a **combined Arabic-English collection**. Setup, §3
verbatim: *"Given a query in either language, its goal is to generate an answer in the same
language. The corpus includes documents in both languages, and each query is associated with
a ground-truth answer found in one language only."* Real corporate Legal and Travel corpora,
deliberately not Wikipedia, to avoid parametric-memory leakage.
**Key findings:** a language-oracle ablation isolates the cause as **document–document**
language mismatch: the retriever ranks fine within one language but fails when a single mixed
index forces it to compare Arabic and English passages against one query. M-E5 Hit@20 drops
42% (Legal) / 33% (Travel) cross-lingually, end-to-end accuracy down 40% / 37%; BGE-M3 drops
33% / 13% and only in the English-query → Arabic-document direction. Two mitigations:
**(a) balanced retrieval** — take an equal number of passages from each language subset;
**(b) dual search** — search the joint corpus twice, once with the original query and once
with its translation, then merge the two ranked lists by embedding inner-product score and
take the top 20. Both cost nothing in same-language cases ("no statistically significant loss
relative to the direct retriever") while adding ~4–6% overall for BGE-M3 and ~20% for M-E5.
**Bearing:** this is Oreag's open limit, published, diagnosed, and fixed — and the two fixes
are the exact two repairs named as unbuilt. Do not re-derive it; start from it.

### [All Languages Matter: Understanding and Mitigating Language Bias in Multilingual RAG (LAURA)](https://arxiv.org/abs/2604.20199)
2026. mRAG **rerankers** systematically favour English and the query's own language, and
"while optimal predictions require evidence scattered across multiple languages, current
systems systematically suppress such answer-critical documents." LAURA
(Language-Agnostic Utility-driven Reranker Alignment) trains the reranker on documents that
empirically produced better generations (utility averaged over four generator models,
threshold 0.8) rather than on semantic relevance.
**Key findings:** with the BGE reranker, **>70% of top-5 documents** (avg over 13 languages)
come from English plus the query language alone. Against an oracle-evidence upper bound,
Recall@3-gram with Llama-3-8B-Instruct averages 48.9 (BGE-Reranker-V2-M3) and 47.1
(Qwen3-Reranker-0.6B) vs **63.6 oracle** — ~15 points left on the table, and *not* a coverage
problem: the oracle evidence already sits in the top-50 candidate pool, just downweighted.
Worst cases are the non-Latin scripts (ko 25.5 vs 41.0; th 26.4 vs 44.1; ja 29.2 vs 47.9).
Gains significant at p<0.05 in 10 of 13 languages; PEER language-fairness +~7 for BGE.
Pipeline: BGE-M3 top-50 over a unified 13-language corpus, reranker picks top-5. A second
description of the same work states LAURA partitions candidates by language and ranks
independently within each group to guarantee balanced exposure, then applies absolute utility
thresholds.
**Bearing:** an independent published implementation of per-language sub-search + fusion,
placed at the rerank stage rather than the retrieval stage — cheaper than a second index.

### [Enhancing Multilingual RAG Systems with Debiased Language Preference-Guided Query Fusion (DELTA / DeLP)](https://arxiv.org/abs/2601.02956)
2026. Argues the apparent English preference of mRAG is largely an artifact of evaluation
structure (exposure bias, gold-availability prior, cultural/topic locality). After debiasing
with the **DeLP** metric, "the strongest signal consistently moves to the diagonal
(Lq = Ld)": retrievers favour query/document **language match**, not English per se.
DELTA builds **one fused query** from five labelled segments joined by ` | ` — `[GLOB]`
English pivot translation, `[LOCAL:xx]` the original native query, `[TITLE_BRIDGE]` paired
Wikipedia titles, `[ALIASES]`, `[LOCALE_HINT]` — weighted by literal **repetition**
(an LLM culture-specificity classifier emits label and confidence; `r_local ∈ {1,2,3}`,
`r_glob ∈ {1,2}`, with title-bridge and aliases duplicated once more above `tau_boost`).
One retrieval pass, BGE-m3, over English Wikipedia plus the user's local-language Wikipedia.
**Key findings:** char-3gram recall, Qwen3-235B, 8 languages: DELTA **62.88** vs English-pivot
translation 58.81, MultiRAG 51.30, CrossRAG 49.63, DKM-RAG 49.06, QTT-RAG 51.65 — and DELTA
is the **fastest** at 1.13 s/query vs 3.80 for DKM-RAG. Largest gains on languages furthest
from English (Arabic 62.55 vs 55.14). Against English-pivot over 16,828 queries in 7
languages it newly recovers gold passages for 1,235 queries at mean best rank 10.39 (median
5; 66.2% into top-10), because pivoting "degrades native surface-form anchors — titles,
aliases, and original scripts — that are critical for precise entity matching." Cue ablation
at fixed evidence: original query 63.13 → +global pivot 71.62 → all cues 72.89. No gain
(slight harm) when the query is already English.
**Bearing:** the published paper closest to Oreag's mechanism, and it argues **against**
replacing the query with its translation. It also explicitly rejects per-language
sub-searches on cost grounds, folding all languages into one enriched probe — so both sides
of Oreag's architectural choice have already been evaluated against each other.

### [Overview of the TREC 2024 NeuCLIR Track](https://arxiv.org/abs/2509.14355)
2025 (describes the TREC 2024 cycle). Chinese, Persian, Russian news plus Chinese academic
abstracts; four task types including **MLIR** (one unified ranked list over several document
languages) and **Report Generation** (English report requests, evidence in a single
non-English language, English reports with citations). 274 runs, 5 teams, 8 tasks.
**Key findings:** MLIR over ~2M Persian + ~3M Chinese + ~5M Russian documents, 51 topics,
~1,999 judgments/topic, best **nDCG@20 = 0.545** — against 0.664 / 0.698 / 0.593 for the
single-language CLIR tasks. Report Generation: 59 requests per language, top systems reached
~0.3 citation precision, <0.5 nugget recall.
**Bearing:** the mixed-corpus case measured under TREC-grade pooling, with a quantified
penalty (0.545 vs 0.59–0.70) for putting several languages in one ranked list. Report
Generation covers behaviours 1–3 but pins output to English, so it is not the full target.

### [Overview of the TREC 2025 RAGTIME Track](https://arxiv.org/abs/2602.10024)
2026. Report generation from multilingual sources: Arabic, Chinese, English and Russian
CommonCrawl News, ~1,000,095 documents **per language collection** (Aug 2021 – Jul 2024).
Three tasks, of which the MLIR task states: *"This task expects systems to search all four
document collections and produce a single unified ranked list."* 13 teams, 125 runs. Report
requests are in English and reports must be English.
**Bearing:** TREC models a mixed-language corpus as **four separate indexes fused into one
ranked list**, not one blended index — the strongest institutional endorsement of the
per-language sub-search + fusion architecture. Note the track contains no metric penalising
wrong-language output, so it does not exercise behaviour 4.

### [Language-Routed RAG and Direct Option Scoring for Multilingual Financial QA: DS@GT at FinMMEval](https://arxiv.org/abs/2607.22841)
2026. LangGraph pipeline: **detect query language**, retrieve from a 30,209-entry
multilingual KB with BGE-M3 + FAISS, and for low-resource languages "fuse per-language and
cross-lingual retrieval indices using weighted Reciprocal Rank Fusion." Generator choice is
also language-routed (Qwen3-14B for ar/zh/hi, Qwen2.5-14B for en, Llama-3.1-8B for el).
**Key finding:** when a language has fewer than `tau = 20` native exemplars in the index, the
global (cross-lingual) index is fused with the native-language shard by weighted RRF with
`w_global = 1.0`, `w_lang = 2.0`, damping `k = 60` — the native shard trusted 2x, both merged
rather than one being gated off. Hindi ran a three-way RRF over global + English + Arabic
proxy indices before earning a dedicated shard. Test accuracy: Hindi 73.5%, Arabic 76.0%,
English 69.5%, Chinese 64.5%.
**Bearing:** the closest published system to the mixed-corpus fix, with Hindi, with constants
to copy. Its answer half is multiple-choice scoring, so it is not the full target.

### [Effects of Cross-lingual Evidence in Multilingual Medical Question Answering](https://arxiv.org/abs/2604.20531)
Yeginbergen et al., 2026. Monolingual vs multilingual vs cross-lingual retrieval for medical
QA in English/Spanish/French/Italian and Basque/Kazakh.
**Key finding:** the cross-lingual setting is a fixed 50/50 per-language fusion — 10 documents
per question, "half of the documents in English and the other half in the target language."
It beats **English-only** retrieval for low-resource languages: Basque 76.0% vs 68.18%,
Kazakh 75.73% vs 66.93%, reaching accuracy comparable to the high-resource languages.
**Bearing:** the simplest possible version of per-language fusion (fixed quota, no learned
router) already beats the English-pivot path where it matters most.

### [Multilingual RAG for Culturally-Sensitive Tasks: BordIRLines](https://arxiv.org/abs/2410.01171)
2024–2025. 720 queries over 251 disputed territories, 49 languages, 19,916 query-document
pairs over 7,436 passages from 905 Wikipedia articles; five formalised retrieval modes, one
of which (`en_only`) is exactly behaviours 1–3.
**Key findings:** retrieving **multilingual** documents beats retrieving purely in-language
documents on both response consistency and geopolitical bias — Command-R consistency
64.2 → 78.7, geopolitical bias 28.7 → 5.9. The linguistic distribution of citations varies
far more widely for low-resource query languages. OpenAI text-embedding-3-large retrieved
1.72x more English documents than M3-Embedding.
**Not the full target:** the prompt states *"You can read documents in many languages, but
your answers should always be primarily in English"* — the answer half is deliberately
excluded.
**Bearing:** direct evidence against gating the cross-lingual path off when the query's
language is present in the corpus. Mixing languages in the retrieved set was *better*, not
worse.

### [Not All Languages are Equal: Insights into Multilingual RAG (Futurepedia)](https://arxiv.org/abs/2410.21970)
2024. Parallel documents plus QA in 8 languages, decomposed into monolingual knowledge
extraction, cross-lingual knowledge transfer, and **multilingual knowledge selection**
(which language does the model prefer when documents in several languages are all present).
**Key findings:** three inequalities — high-resource languages win at extraction;
Indo-European languages let the model answer directly from the document; **English wins
multilingual knowledge selection through selection bias**. The proposed fix is to add more
non-English documents and **reposition** the English ones in the context.
**Bearing:** in a mixed-language context window, *where* the English evidence sits changes
which evidence is used. A cheap, testable lever that costs nothing at retrieval time.

### [Investigating Information Inconsistency in Multilingual Open-Domain QA](https://arxiv.org/abs/2205.12456)
2022. Analyses retrieval bias on TyDi QA and XOR-TyDi.
**Key finding:** the same question asked in different languages returns **different**
passages, because same-topic documents in different languages carry different information —
the retrieved evidence set is a function of query language, not only of query meaning.
**Bearing:** the earliest statement of the mechanism behind Oreag's mixed-corpus bug, and a
warning that "fixing" it may change *which facts* the system reports, not just recall.

---

## 4. Answer language: the half Oreag's design assumes away

### [On the Consistency of Multilingual Context Utilization in RAG](https://arxiv.org/abs/2504.00597)
2025 (MRL). 48 languages, 3 QA datasets, 4 LLMs (Aya-Expanse-8B, Llama-3.2-3B-Instruct,
Gemma, Qwen2.5-7B-Instruct) over XQuAD (12), MKQA (24), GMMLU.
**Key findings:** LLMs are good at extracting information from a passage in a different
language than the query, but "much weaker" at formulating a full answer in the correct
language. XQuAD with Aya-Expanse-8B, LLM-judged: Arabic queries score 87.14 with an
in-language passage vs 64.38 with an out-language passage — but a further **24.85% of Arabic
queries are answered correctly yet in the wrong language**, despite an explicit "Please
respond in Arabic" instruction; scoring wrong-language answers as correct almost closes the
IN/OUT gap entirely. Verbatim: "the query language is much more predictive of accuracy than
the passage language, suggesting that generating in the target language is the major
bottleneck." A two-step "answer in any language, then translate" prompt **and** larger models
(Gemma3-27B-IT, GPT-5-nano) both failed to fix it — "an inherent decoding limitation."
**Bearing:** the single most load-bearing negative result for Oreag's step 4. Keeping the
original question in the prompt is not a guarantee, it is a hope, and the failure is at
decode time where a prompt cannot reach it.

### [Language Drift in Multilingual RAG: Characterization and Decoding-Time Mitigation (SCD)](https://arxiv.org/abs/2511.09984)
AAAI 2026 oral; code [github.com/WisdomShell/SCD](https://github.com/WisdomShell/SCD).
Characterises "language drift" when retrieved evidence differs in language from the query,
and locates the cause at the decoder — dominant token distributions and high-frequency
English patterns overriding the intended language — not at comprehension. Proposes **Soft
Constrained Decoding**, a training-free, model-agnostic logit penalty on non-target-language
tokens.
**Key findings:** on HotpotQA, swapping the context from Chinese to English alone drops
language consistency 92.0% → **68.4%** with the target-language instruction still present.
SCD recovers ZH 68.4 → 90.6, RU 80.2 → 95.4, AR 85.4 → 96.4, with ROUGE rising alongside
(ZH 0.182 → 0.306, RU 0.333 → 0.422). LLaMA3-8B-Instruct and Qwen2.5-7B-Instruct; HotpotQA,
MuSiQue, DuReader, 1,000 samples each, EN/ZH/AR/RU.
**Bearing:** the reliable version of what Oreag currently gets from prompt construction.
Requires logit access, so it is only available if the generator is self-hosted.

### [Understanding and Mitigating Language Confusion in LLMs](https://aclanthology.org/2024.emnlp-main.380/)
EMNLP 2024 (Marchisio et al.; preprint [arXiv:2406.20052](https://arxiv.org/abs/2406.20052);
code [github.com/for-ai/language-confusion](https://github.com/for-ai/language-confusion)).
The Language Confusion Benchmark over 15 typologically diverse languages, with **monolingual**
(match the query) and **cross-lingual** (obey an explicit language instruction) settings —
which are precisely Oreag's two policy modes. Metrics: Line-level Pass Rate, Word-level Pass
Rate, and their harmonic mean.
**Key findings:** cross-lingual line-level pass rate 30.3% for Llama 3 70B-Instruct and 38.4%
for Llama 2 70B-Instruct vs 95.4% for Command R+ Refresh and 92.4% for GPT-4o; monolingual,
the same Llama models reach only 46.0–48.3% LPR while GPT-4 Turbo hits 99.3%. Mitigation on
Command R Base, cross-lingual LPR: 1.1 (0-shot) → 20.9 (1-shot) → 90.7 (5-shot); English SFT
gives 95.0. Confusion worsens with longer prompts and higher temperature (WPR down to 72.0%
at high T); beam search consistently hurts.
**Bearing:** model choice alone moves wrong-language output by ~60 points. Before building
any language-policy machinery, measure the generator on LCB — the cheapest possible fix may
be swapping it.

Adjacent enforcement mechanisms, all training-free or cheap, all requiring logit or
activation access: [Language Confusion Gate](https://arxiv.org/abs/2510.17555) (at confusion
points the correct-language token is already in the top-3 **99.29%** of the time; Qwen3-8B
FLORES-NO-LATIN Latin-script confusion 12.1% → 2.0%),
[ReCoVeR](https://arxiv.org/abs/2509.14814) (Gemma-2 cross-lingual correct-answer-language
70.4% → 96.2%, MMLU within 0.4 points), [LATB](https://arxiv.org/abs/2606.08994) (Llama3-8B
XLSum Russian response-level confusion 92.50% → 0.10%, Chinese 98.90% → 0.00%), and
[ITLC](https://arxiv.org/abs/2506.12450) (middle-layer latent injection; Qwen2.5
cross-lingual representation similarity 0.922 mid-layer vs 0.375 last-layer).

### [Evaluating and Modeling Attribution for Cross-Lingual QA (XOR-AttriQA)](https://arxiv.org/abs/2305.14332)
EMNLP 2023. Human-annotated (query, passage, answer) attribution tuples across Bengali,
Finnish, Japanese, Russian, Telugu — roughly 10,000 tuples; answers generated by **CORA**
(mDPR over mBERT + mGEN on mT5-Base).
**Key findings:** up to **~47%** of cross-lingual QA answers that *exactly match the gold
reference* are not attributable to any retrieved passage (Japanese 53.1% attributable;
Telugu best at 93.1%). Fix: PaLM 2 fine-tuned on only ~100 attribution examples reaches
92–96% accuracy / 95–98% ROC AUC at detecting attribution.
**Bearing:** rank-1 retrieval plus a plausible answer proves nothing about grounding across a
language boundary. A ~100-example attribution classifier is a cheap guardrail.

### [MLAIRE: Multilingual Language-Aware Information Retrieval Evaluation Protocal](https://arxiv.org/abs/2605.07249)
2026 (the typo "Protocal" is arXiv's own). Purpose-built for the setting where "users issue
queries over mixed-language corpora"; disentangles cross-lingual semantic retrieval from
query-language preference via **Language Preference Rate** and Lang-nDCG.
**Key finding:** the two are near-orthogonal and can be anti-correlated. On MLQA:
multilingual-e5-large 96.15% nDCG at 99.92% LPR; Qwen3-Embedding-8B 68.64% nDCG at 53.00%
LPR; BM25 27.92% nDCG at 93.68% LPR. nDCG–LPR correlation (Pearson/Spearman): −0.28/−0.30
(MLQA), −0.38/−0.47 (XQuAD), −0.29/−0.28 (Belebele), across 31 retrievers.
**Bearing:** on a single-script corpus, semantic skill and language preference are
indistinguishable by construction — which is why an 80/80 result there could not have
detected the mixed-corpus failure. LPR is the number to track while fixing it.

### [LAReQA: Language-Agnostic Answer Retrieval from a Multilingual Pool](https://aclanthology.org/2020.emnlp-main.477/)
EMNLP 2020. Introduces **weak** vs **strong** cross-lingual alignment: weak = the nearest
neighbour in another language is the right one; strong = semantically related cross-language
pairs must be closer than unrelated *same-language* pairs. Retrieval from a mixed-language
candidate pool.
**Key finding:** mAP on XQuAD-R (11 languages, all pooled into one mixed index) / MLQA-R:
En-En 0.29/0.36, X-X **0.23**/0.26, X-X-mono 0.52/0.49, X-Y 0.66/0.49, Translate-Test
0.72/0.58. X-X scores *worse* than English-only training — training on translated data with
monolingual positive pairs actively damages mixed-pool retrieval; only X-Y, where question
and answer are translated into *different* languages, fixes it.
**Bearing:** the mixed-language pool has been an evaluated setting since 2020, and the
weak/strong distinction is the precise vocabulary for Oreag's bug: the system has weak
alignment and needs strong.

---

## 5. Product-shaped systems that already do this

### [HEALTH-PARIKSHA](https://arxiv.org/abs/2410.13671)
2024–2025. 24 LLMs evaluated on **real** Indian patient queries to a medical chatbot in
Indian English, Hindi, Tamil, Telugu and Kannada, under a uniform RAG framework.
**Key finding:** the knowledge base is **English-only** (12 doctor-curated PDFs, 1000-token
chunks, text-embedding-ada-002, top-3 retrieved); the generation prompt carries an explicit
language policy, verbatim: *"The provided query is in {query_lang}, and you must always
respond in {response_lang}."* Instruction-tuned Indic models do not always beat general
models; factual correctness is lower for Indic than English queries; code-mixed and
culturally-specific queries are hardest. Scale caveat for reuse: of 749 question/GT pairs,
666 are English and only 19 Hindi, 27 Tamil, 14 Telugu, 23 Kannada.
**Bearing:** behaviours 1–5 as a shipped configuration, including a parameterised
`{response_lang}` — behaviour 5 as a prompt variable, published, in 2024.

### [Bridging the Gap with RAG: Prosthetic Device User Manuals in Marginalised Languages](https://arxiv.org/abs/2506.23958)
2025; code [github.com/Iykay/User-Manual-LLM](https://github.com/Iykay/User-Manual-LLM).
Users upload **English** device manuals, "pose questions in their native language, and
receive accurate, localised answers in real time," demonstrated on Nigerian Pidgin.
**Key finding:** the stack, from the repo: NITHUB-AI marian-mt-bbc (pcm→en) for the query,
multi-qa-mpnet-base-dot-v1 + FAISS over the English manual, FLAN-T5-large to answer in
English, marian-mt-bbc (en→pcm) to translate back.
**Bearing:** Oreag's product story, verbatim, in an open-source repo — with the weaker
answer-side design (back-translate) rather than generate-in-language.

### [Cost-Efficient Cross-Lingual RAG for Low-Resource Languages: Bengali Agricultural Advisory](https://arxiv.org/abs/2601.02065)
2026. Bengali query → English translation with domain keyword injection → dense search over a
curated English FAO/IRRI corpus → English response → back-translation to Bengali. All
open-source, consumer hardware, no paid APIs, source-grounded, with out-of-domain rejection.
**Key finding:** all-MiniLM-L6-v2 + FAISS, Helsinki-NLP opus-mt-bn-en inbound, NLLB-200
outbound, 4-bit Llama-3-8B-Instruct, averaging **~15.6 s end-to-end** on a single Tesla T4.
**Bearing:** the honest latency cost of an unconditioned translate-in / translate-out
pipeline, and the cheapest published parts list. Also the argument for replacing an LLM
translation call on the critical path with a local MT model.

### RAGFlow "Cross-language search" — [ragflow.io/docs/glossary](https://ragflow.io/docs/glossary)
Shipped feature since v0.19.0 (26 May 2025). Glossary, verbatim: *"Cross-language search
allows users to submit a query in one language and retrieve relevant content written in other
languages. For example, an English query can be used to retrieve Chinese documents"* — it
*"reduces retrieval limitations caused by differences between the query language and the
language of the knowledge base content."* Release notes: supported in the Knowledge and Chat
modules, "such as in Chinese-English datasets." Per feature descriptions, the user selects
target languages from a dropdown and the default chat model translates the query before
matching.
**Bearing:** Oreag's retrieval mechanism, shipped free and open source for over a year. The
documented differences: it is an always-on toggle (no gate, no script check, no
weak-similarity trigger, so it pays translation cost on every query) and the docs say nothing
about the language of the generated answer.

Negative results worth recording on the vendor side, all verified from first-party docs:
[Vespa](https://docs.vespa.ai/en/linguistics.html) states outright that it *"does not
out-of-the-box support cross-lingual retrieval"* and that queries of three terms or fewer
default to English under its 0.02 confidence cutoff;
[Haystack's language-routing tutorial](https://haystack.deepset.ai/tutorials/32_classifying_documents_and_queries_by_language)
ships same-language routing as the documented default — *"The language of a question is
detected, and only documents in that language are used to generate the answer"* — which is
Oreag's mixed-corpus bug as a framework feature;
[Haystack's multilingual cookbook](https://haystack.deepset.ai/cookbook/multilingual_rag_podcast)
achieves behaviours 1–4 with a hardcoded prompt string;
[Azure AI Search](https://docs.azure.cn/en-us/search/search-language-support) offers only
manual per-language fields and admits it has no mechanism for determining the query's
language;
[LangChain retrieval docs](https://docs.langchain.com/oss/python/langchain/retrieval)
mention no multilingual, cross-lingual or translation handling at all.

---

## 6. Near-misses that bound the claims

| Work | Year | Why it is not the full target | The number that matters |
|---|---|---|---|
| [MKQA](https://aclanthology.org/2021.tacl-1.82/) | 2021 | answers are language-**independent** entity representations, decoupled from any passage, so it cannot score answer-language correctness | 10k questions x 26 languages = 260k pairs |
| [MIRACL](https://aclanthology.org/2023.tacl-1.63/) | 2023 | explicitly monolingual: "the queries and the corpora are in the same language" | 18 langs, 726k judgments; BM25 nDCG@10 0.393, mDPR 0.415, hybrid **0.578** |
| [MIRAGE-Bench](https://arxiv.org/abs/2410.13716) | 2024/25 | inherits MIRACL's monolingual design; corpus language always equals query language | surrogate judge predicts GPT-4o preferences at Kendall tau **0.909**; its feature set includes a langid "language detection" feature |
| [NoMIRACL](https://arxiv.org/abs/2312.11361) | 2023/24 | per-language, self-contained; measures abstention, not cross-lingual QA | LLaMA-2 and Orca-2 exceed **88%** hallucination rate on the non-relevant subset; low-hallucination models hit 74.9% error rate on the relevant subset |
| [MEMERAG](https://arxiv.org/abs/2502.17163) | 2025 | native-language questions over same-language corpora; does not measure answer language | includes Hindi; faithfulness Gwet's AC1 0.84–0.93 vs 0.34–0.42 kappa in prior work; best LLM judge **differs by language** |
| [IndicGenBench XorQA-In-Xx](https://arxiv.org/abs/2404.16816) | 2024 | supplies the gold English passage — no corpus, no retrieval | exactly (Indic question, English passage, Indic answer), 28 languages, ~32k examples; best model PaLM-2-L only **37.4** Token-F1 |
| [IndicRAGSuite](https://arxiv.org/abs/2506.01615) | 2025 | explicitly monolingual — queries translated into the corpus language | MRR tops out ~0.49–0.52 across 13 Indian languages (Hindi 0.52) |
| [XRAG's monolingual condition](https://arxiv.org/abs/2505.10089) | 2025 | — (it *is* the target; listed here for the metric) | Response Language Correctness measured with `lingua` |
| [LAMAR](https://arxiv.org/abs/2607.22042) | 2026 | a reranker, not a RAG system | for English queries, existing multilingual rerankers put a **non-English document first 72.8%** of the time when equivalent documents exist across languages |
| [Anveshana](https://arxiv.org/abs/2505.19494) | 2025 | retrieval only (English query, Sanskrit corpus) | Document Translation + BM25 **62.46** nDCG@10 vs Direct Retrieval (mE5-base) 10.74 and Query Translation + BM25 6.86 |
| [CLIRudit](https://arxiv.org/abs/2504.16264) | 2025 | retrieval only | NV-Embed-v2 0.580 MAP untranslated vs 0.600 with **gold human** translation; query translation *hurt* several dense models (0.580 → 0.541) |
| [Sinhala/Tamil e-government CLIR](https://arxiv.org/abs/2608.12820) | 2026 | retrieval only | BGE-M3 with no translation: R@15 **96.2%** (Si-En) / 95.6% (Ta-En) vs Google Translate query translation 92.4% / 93.0% |
| [ECLeKTic](https://arxiv.org/abs/2502.21228) | 2025 | closed-book, no retrieval | the control condition: Gemini 2.0 Pro 41.6% overall, GPT-4o 38.8%, sub-10B open models <9% — parametric knowledge does not cross languages, so putting the evidence in context is not optional |
| [Crosslingual Capabilities and Knowledge Barriers](https://arxiv.org/abs/2406.16135) | 2024 | no retrieval | mixup-translated MMLU: GPT-4 81.82 → 68.61 (**−13.2**), Llama3-8B −11.92 — a ~10–13 point reasoning penalty from the language mix alone, which supports keeping the *original* question in the generation prompt |

---

## 7. What is genuinely not in this literature

Stated narrowly, because the rest of the design is prior art.

1. **A Unicode script-presence gate as a routing signal.** No paper found that detects the
   query's writing system, checks whether that script is present in the corpus, and uses that
   as a boolean gate on the cross-lingual path. But the evidence argues it is the wrong
   heuristic rather than an unexploited one:
   [BordIRLines](https://arxiv.org/abs/2410.01171) finds multilingual retrieval beats
   in-language retrieval even when in-language documents exist;
   [Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/) find the concatenated
   multilingual corpus beneficial in most cases; and a script check is blind to romanized
   Hindi — [IndicLID](https://aclanthology.org/2023.acl-short.71/) reports 98.55% accuracy on
   native script but only 80.40% on romanized text, and
   [Script Gap](https://arxiv.org/abs/2512.10780) measures up to a 24-point LLM degradation
   from romanization across five Indian languages plus Nepali.

2. **A retrieval-score-conditioned translation trigger.** Published systems translate
   unconditionally (tRAG, CrossRAG, DKM-RAG, QTT-RAG, DELTA). The two published gates fire on
   something else: [Syfer](https://arxiv.org/abs/2608.13160) on sub-question drift
   (`cos < 0.8`), [CORAL](https://arxiv.org/abs/2604.25676) on an LLM sufficiency critic.
   The motivating evidence exists and nobody has built the gate: on
   [INDIC QA BENCHMARK](https://arxiv.org/abs/2407.13522), Llama-3 extractive F1 is 33.01
   (translate-test) vs 21.29 (direct) for Assamese but 46.76 (direct) vs 26.22
   (translate-test) for Hindi; and [How and Where to Translate](https://arxiv.org/abs/2507.22923)
   finds no universally best translation strategy — every strategy degraded Hindi on
   Llama-3.1-8B by up to 10.9 points while French on BLOOMZ-7b1 gained 13.4.

3. **A quality-vs-translation-call-budget curve.** No paper reports retrieval quality as a
   function of how often the expensive cross-lingual path is allowed to fire. The
   cost-explicit papers optimise by model choice instead
   ([Bengali advisory](https://arxiv.org/abs/2601.02065) ~15.6 s/query;
   [DELTA](https://arxiv.org/abs/2601.02956) 1.13 s/query vs 3.80 for DKM-RAG). This is a
   benchmarking contribution, not a capability.

4. **Answer-language policy as a configurable control surface.** Research fixes the answer
   language by task definition (XOR-Full), by split (IndicGenBench XorQA-In-Xx vs -In-En),
   or by hardcoded prompt string (Haystack cookbook; BordIRLines forces English; TREC RAGTIME
   requires English with no wrong-language penalty). No documented commercial RAG product
   exposes pin-vs-match as a setting, and
   [RAGAS's metric list](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/)
   contains no language-consistency metric. The mechanism is a prompt variable and the
   enforcement is published — this is a packaging gap, not a scientific one, which is exactly
   why it is the most defensible thing on this list.

5. **A per-query router over the published strategy space** (tRAG / monoRAG / MultiRAG /
   CrossRAG / DELTA-style fusion / QTT-RAG), rather than one fixed global policy. The
   precondition is proven twice over — [arXiv:2507.22923](https://arxiv.org/abs/2507.22923)
   and [arXiv:2407.13522](https://arxiv.org/abs/2407.13522) both show the winning strategy
   flipping by model and language, and DELTA notes its own gains vanish when the query is
   already English — but nobody routes on it. The bar is high:
   [CrossRAG](https://arxiv.org/abs/2504.03616) as a fixed global policy is already +17.8%
   over monolingual RAG.

---

## Reading order for someone about to build

1. [arXiv:2504.03616](https://arxiv.org/abs/2504.03616) — your mechanism has a name and it
   loses; CrossRAG is the A/B baseline.
2. [arXiv:2507.07543](https://arxiv.org/abs/2507.07543) — your open limit, diagnosed, with
   both of your proposed fixes already measured.
3. [aclanthology.org/2024.knowllm-1.15](https://aclanthology.org/2024.knowllm-1.15/) — the
   reference implementation and the prompt recipe for step 4.
4. [arXiv:2504.00597](https://arxiv.org/abs/2504.00597) +
   [arXiv:2511.09984](https://arxiv.org/abs/2511.09984) — why step 4 is not free, and the
   training-free fix.
5. [aclanthology.org/2021.naacl-main.46](https://aclanthology.org/2021.naacl-main.46/) +
   [arXiv:2605.07249](https://arxiv.org/abs/2605.07249) — the benchmark to re-measure 80/80
   against, and the protocol that would have caught the mixed-corpus failure.
