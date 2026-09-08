# Answer-Language Control: making the model reply in the question's language when the evidence is in another one

Scope: step 4 of the target design — question in language B, retrieved context in language A,
answer required in language B — plus step 5, the pin-vs-match policy.

Headline for an engineer about to build this: **retrieval is the easy half.** The published
consensus is that current LLMs read foreign-language evidence competently and then fail to
*emit* the answer in the user's language. This failure has two names, two literatures, a
benchmark with released code, at least six distinct mitigation families, and measured rates
between 5% and 50% depending on model. Keeping the original question in the generation prompt —
which is what Oreag does — is the weakest known enforcement mechanism, and it is measured as
insufficient in three independent papers.

---

## 1. The failure has a name (two, actually)

| Term | Definition | Origin |
|---|---|---|
| **Language confusion** | Model fails to generate in the user's desired language; measured monolingually (match the prompt language) and cross-lingually (obey an explicit language instruction) | [Marchisio et al., EMNLP 2024](https://aclanthology.org/2024.emnlp-main.380/) ([arXiv](https://arxiv.org/abs/2406.20052)), benchmark code at [for-ai/language-confusion](https://github.com/for-ai/language-confusion) |
| **Language drift** | The RAG-specific case: retrieved evidence in a different language from the query pulls generation into an unintended language | [Li et al., AAAI 2026 oral](https://arxiv.org/abs/2511.09984) |
| **Response language correctness** | Benchmark metric for "did the answer come back in the user's language" in cross-lingual RAG | [XRAG (Amazon), 2025](https://arxiv.org/abs/2505.10089) |
| **Correct Language Rate (CLR)** | Same thing, reported alongside accuracy in mRAG systems | [Chirkova et al. 2024](https://aclanthology.org/2024.knowllm-1.15/), [LcRL 2026](https://arxiv.org/abs/2601.14896) |
| **Language Confusion Entropy** | Graded version — degree of confusion from the output language distribution, weighted by typology | [arXiv:2410.13237](https://arxiv.org/abs/2410.13237) |

Two structural findings frame everything below:

- **The bottleneck is decoding, not comprehension.** [On the Consistency of Multilingual
  Context Utilization in RAG](https://arxiv.org/abs/2504.00597) (48 languages, 4 LLMs, XQuAD /
  MKQA / GMMLU) states that "the query language is much more predictive of accuracy than the
  passage language, suggesting that generating in the target language is the major bottleneck,"
  and shows that allowing wrong-language answers as correct *almost closes* the in-language vs
  out-language passage gap.
- **The response-language slot is the dominant axis of failure.**
  [MTM-Bench](https://arxiv.org/abs/2605.27649) crosses (instruction language, content language,
  response language) over 27 combinations and 20 models, and finds degradation is organised by
  *which role* a language occupies, with a single response-slot mismatch accounting for most of
  the loss — mismatch count is not a monotonic predictor.

---

## 2. Measured failure rates

These are the numbers to size your own risk against. Note the range: **model choice alone moves
this by ~60 percentage points.**

### 2.1 In a RAG pipeline (retrieved context in a foreign language)

| Setting | Measurement | Source |
|---|---|---|
| English-only retrieval, non-English query | Answers wrongly returned in English: **~5%** GPT-4o and Command-R+, **~15%** Claude 3.5 Sonnet, **~35%** Mistral-large | [XRAG](https://arxiv.org/abs/2505.10089) (5 languages, ~1k verified QA pairs/pair from News Crawl) |
| English Wikipedia datastore, default English prompt, Command-R-35B | Answered **in English for ~50%** of non-English queries | [Chirkova et al. 2024](https://aclanthology.org/2024.knowllm-1.15/) |
| Same, Korean queries, datastore swapped Korean → English | Correct-language rate **99.9% → 54.3%** | [Chirkova et al.](https://arxiv.org/abs/2407.01463) |
| HotpotQA, Chinese target, context swapped ZH → EN | Language consistency **92.0% → 68.4%**, with the "answer in Chinese" instruction still present | [Language Drift / SCD](https://arxiv.org/abs/2511.09984) |
| XQuAD Arabic, Aya-Expanse-8B, explicit "Please respond in Arabic" | **24.85%** of queries answered *correctly but in the wrong language* | [arXiv:2504.00597](https://arxiv.org/abs/2504.00597) |
| Same paper, Arabic query, LLM-judged | In-language passage **87.14** vs out-language passage **64.38** — most of that gap is language, not comprehension | [arXiv:2504.00597](https://arxiv.org/abs/2504.00597) |
| Mixed-language passages left in the prompt (MultiRAG) vs translated to one language (CrossRAG) | CrossRAG has consistently higher correct-output-language rate, measured with OpenLID | [arXiv:2504.03616](https://arxiv.org/abs/2504.03616) / [Findings EACL 2026](https://aclanthology.org/2026.findings-eacl.35/) |

### 2.2 Without retrieval — the model-level floor (Language Confusion Benchmark, 15 languages)

| Model | Monolingual LPR | Cross-lingual line-level pass rate |
|---|---|---|
| GPT-4 Turbo | 99.3 | — |
| GPT-4o | — | 92.4 |
| Command R+ Refresh | — | 95.4 |
| Llama 3 70B-Instruct | 46.0–48.3 (Llama family) | **30.3** |
| Llama 2 70B-Instruct | 46.0–48.3 (Llama family) | **38.4** |

Source: [Marchisio et al.](https://aclanthology.org/2024.emnlp-main.380/) /
[arXiv:2406.20052](https://arxiv.org/abs/2406.20052). Metrics are Line-level Pass Rate (LPR),
Word-level Pass Rate (WPR) and their harmonic mean LCPR. The *cross-lingual* setting — an
English instruction/context with a non-English target — is exactly the RAG shape, and it is the
hardest setting in the benchmark; even the best models only reach LPR in the low 90s.

Two aggravating factors that matter specifically for RAG, both from the same paper:

- **Confusion worsens with longer and more complex prompts.** RAG prompts are long by
  construction (retrieved chunks + instruction + question).
- **Confusion worsens with sampling temperature** — WPR falls to 83.5% average, as low as 72.0%
  at high T — and **beam search consistently hurts cross-lingual LPR.**

---

## 3. Why it happens: the latent-language findings

The mechanistic literature converges on: models compute in an English-proximate representation
space and convert to the target language late, and that late conversion is what breaks.

- [Wendler et al., ACL 2024, "Do Llamas Work in English?"](https://aclanthology.org/2024.acl-long.820/)
  — on Llama-2, intermediate-layer embeddings already decode the semantically correct next token
  but assign **higher probability to its English version** than to the input-language version;
  only in the final layers do representations move into an input-language-specific region. Framed
  as input space → concept space → output space, with the concept space closer to English.
- [Do Multilingual LLMs Think In English?](https://arxiv.org/abs/2502.15603) — logit-lens over
  French/German/Dutch/Mandarin: models "make key decisions in a representation space closest to
  English, regardless of their input and output languages," emitting English-proximate
  representations for semantically loaded words before converting. Activation steering is
  correspondingly more effective with English-derived vectors.
- [How do LLMs Handle Multilingualism?](https://arxiv.org/abs/2402.18815) — the MWork workflow:
  understand → reason in English-centric representation → **generate in the original query
  language**, with language-specific components responsible for that last step (found via PLND,
  no labelled data). Fine-tuning only those neurons on ~400 documents gives ~3.6% (high-resource)
  / ~2.3% (low-resource) improvement.
- [Language Surgery / ITLC](https://arxiv.org/abs/2506.12450) — quantifies where alignment lives
  and where it dies: Qwen2.5 cross-lingual representation similarity is **0.922 at middle layers
  but 0.375 at the last layers** (LaBSE, explicitly aligned, sits at 0.754 last).
- [Mechanistic Understanding and Mitigation of Language Confusion](https://arxiv.org/abs/2505.16538)
  — locates "confusion points" (token positions where output language switches) and attributes
  them via TunedLens to **transition failures in the final layers**.
- [Language Drift](https://arxiv.org/abs/2511.09984) — controlled experiments show the drift is
  "not comprehension failure but decoder-level collapse" toward dominant high-frequency English
  token distributions.
- Practical corollary from [Language Confusion Gate](https://arxiv.org/abs/2510.17555): at
  confusion points, the language-consistent token is **already in the top-3 predictions 99.29% of
  the time**, while the confused token is top-1 only 56.74% of the time (FLORES-NO-LATIN). The
  model knows the right token; the sampler picks the wrong one. That is why cheap logit masking
  works and why prompting alone does not.

Where the neuron literature disagrees (flag rather than reconcile):
[Tang et al.](https://arxiv.org/abs/2402.16438) find language-specific neurons (via LAPE)
concentrated in **top and bottom** layers on LLaMA-2/BLOOM/Mistral;
[Language Arithmetics](https://arxiv.org/abs/2507.22608) finds them clustered in **deeper**
layers on Llama-3.1-8B / Mistral-Nemo-12B / Aya-Expanse, across 21 languages. Both agree that
selectively activating/deactivating them steers output language, and the second adds two findings
that matter here: **non-Latin scripts show greater neuron specialisation**, and manipulation is
more successful for high-resource languages and rises with typological similarity.

---

## 4. The enforcement ladder

Ordered by cost and by what access you need. Pick the highest rung your deployment allows.

| Rung | Mechanism | Measured effect | Requires |
|---|---|---|---|
| 0 | Original question in prompt, no explicit instruction (**Oreag today**) | ~50% English answers for non-English queries with an English datastore ([Chirkova](https://aclanthology.org/2024.knowllm-1.15/)) | nothing |
| 1 | Explicit "respond in {L}" instruction | Still 24.85% wrong-language on Arabic ([arXiv:2504.00597](https://arxiv.org/abs/2504.00597)); ZH 68.4% consistency under English context ([SCD](https://arxiv.org/abs/2511.09984)) | nothing |
| 2 | **Translate the prompt itself into the user's language** + explicit instruction | CLR **>95%** in most cases; named-entity code-switching persists in non-Latin scripts ([Chirkova](https://aclanthology.org/2024.knowllm-1.15/)) | nothing |
| 3 | Few-shot exemplars in the target language | Command R Base cross-lingual LPR **1.1 → 20.9 (1-shot) → 90.7 (5-shot)** ([LCB](https://aclanthology.org/2024.emnlp-main.380/)) | context budget |
| 4 | **Normalise the context language** (translate retrieved docs into one language before generation) | CrossRAG beats MultiRAG on correct-output-language rate, measured with OpenLID; +13.9 pts MKQA / +9.0 MLQA over question-translation ([arXiv:2504.03616](https://arxiv.org/abs/2504.03616)) | 1 MT call per retrieved doc |
| 5 | **Constrained decoding** — penalise/mask non-target-language tokens | SCD: ZH 68.4→**90.6**, RU 80.2→**95.4**, AR 85.4→**96.4**, with ROUGE *rising* (ZH 0.182→0.306, RU 0.333→0.422) ([SCD](https://arxiv.org/abs/2511.09984), [code](https://github.com/WisdomShell/SCD)) | logit access |
| 5b | **Gated** decoding filter (intervene only at predicted confusion points) | LCG: Qwen3-8B Latin-script confusion **12.1%→2.0%**, CJK **4.5%→0.1%**; INCLUDE 2.21%→0.11% with accuracy held ~71%; HumanEval-XL pass@1 80.56→79.44 ([arXiv:2510.17555](https://arxiv.org/abs/2510.17555)) | logit access |
| 5c | Language-Aware Token Boosting (tuning-free logit perturbation) | Llama3-8B-Instruct on XLSum, 8 languages **including Hindi**: Russian response-level confusion **92.50% → 0.10%**, Chinese **98.90% → 0.00%**, ROUGE maintained ([arXiv:2606.08994](https://arxiv.org/abs/2606.08994)) | logit access |
| 6 | **Activation steering** with language vectors | ReCoVeR: Gemma-2 cross-lingual correct-answer-language **70.4% → 96.2%**; Llama-3.1 97.9%, Qwen-2.5 95.2%; multilingual MMLU within 0.4 pts ([arXiv:2509.14814](https://arxiv.org/abs/2509.14814)) | hidden-state access |
| 6b | Single-feature SAE steering | Up to **90%** language-shift success from modifying **one** SAE feature at **one** layer of Gemma-2B/9B, meaning preserved (LaBSE similarity), mid-to-late layers best ([arXiv:2507.13410](https://arxiv.org/abs/2507.13410)) | SAE + hidden states |
| 6c | Middle-layer latent injection (ITLC) | Qwen2.5-7B-Instruct **78.81% → 84.73%** (~26.7% cross-lingual improvement); 85.65 on LCB vs ReCoVeR's 90.29, at lower compute ([arXiv:2506.12450](https://arxiv.org/abs/2506.12450)) | hidden states |
| 6d | Neuron editing | Editing **top-100 neurons** of Llama3-8B: LCB average line-level accuracy **39.9% → 73.3%**; Chinese 23.4→64.1, Portuguese 74.5→95.4 ([arXiv:2505.16538](https://arxiv.org/abs/2505.16538)) | weight access |
| 7 | Preference tuning with code-mixed negatives (ORPO) | SmolLM2-1.7B at temperature **1.2**: 100.0% WPR / 99.9% LPR vs SFT 100.0/99.7; QA accuracy not significantly degraded ([arXiv:2505.19116](https://arxiv.org/abs/2505.19116)) | training |
| 7b | Token-level policy optimisation (TLPO) | **99.19%** average Response Pass Rate while holding 58.08% general accuracy (untouched baseline 58.35%) — vs SFT's comparable 99.14% RPR but accuracy collapsed to **50.71%** ([arXiv:2604.26553](https://arxiv.org/abs/2604.26553)) | training |
| 7c | RL with a language-consistency reward term | LcRL: **99.1% CLR** vs mSearch-R1's 95.6% on MKQA (Qwen2.5-3B-Instruct), with +3.3pp fEM ([arXiv:2601.14896](https://arxiv.org/abs/2601.14896)) | training |

Three cautions on the upper rungs:

- **Reward-only RL can make language adherence worse.** [TR-RAG](https://arxiv.org/abs/2607.02966),
  built for exactly the "users query in diverse languages but retrieved passages remain English"
  regime, reports that reward-only RL suffers **language-consistency collapses of up to ~27
  percentage points**, drifting *below the base model*; the fix is on-policy distillation on
  student-visited prefixes with a reverse-KL anchor to a frozen teacher. Its reward decomposes
  into language consistency + character 3-gram recall + LLM-judge grounded correctness — a good
  template for a scoring function even if you never train.
- **The alignment tax is real and asymmetric.** TLPO's contribution above is precisely that SFT
  buys the same language-adherence for a 7.6-point general-accuracy loss.
- **Steering methods mostly fix the cross-lingual case, not the monolingual one.** ReCoVeR's
  monolingual pass rates were already ~98% for Llama-3.1 and Qwen-2.5 and barely moved. If your
  measurements are monolingual, you will conclude nothing is wrong.

**What does *not* work:** [arXiv:2504.00597](https://arxiv.org/abs/2504.00597) tested a two-step
"answer in any language, then translate into the query language" prompt and larger models
(Gemma3-27B-IT, GPT-5-nano) and reports both failed — "the problem persists ... an inherent
decoding limitation." Do not plan on scaling out of this.

---

## 5. How published systems actually enforce output language

Verbatim, because these are copy-pasteable and because the field's answer is embarrassingly
simple at the prompt layer:

| System | Mechanism |
|---|---|
| [QTT-RAG](https://arxiv.org/abs/2510.23070) | `Always answer as briefly and accurately as possible, and respond only in {query language}` |
| [HEALTH-PARIKSHA](https://arxiv.org/abs/2410.13671) | `The provided query is in {query_lang}, and you must always respond in {response_lang}.` — English-only KB (12 doctor-curated PDFs, ada-002, top-3), queries in Indian English/Hindi/Tamil/Telugu/Kannada |
| [BordIRLines](https://arxiv.org/abs/2410.01171) | The **pin** case: `You can read documents in many languages, but your answers should always be primarily in English.` |
| [Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/) | Prompt **translated into the user language** + `generate the response in the user language` → CLR >95% |
| [CORA](https://arxiv.org/abs/2107.11976) | No instruction at all — mGEN is trained to "answer directly in the target language without any translation or in-language retrieval modules" |
| [CrossRAG](https://aclanthology.org/2026.findings-eacl.35/) | Explicit instruction to answer in the query language, *plus* the retrieved documents translated to one language first |
| [SCD](https://arxiv.org/abs/2511.09984) / [LCG](https://arxiv.org/abs/2510.17555) / [LATB](https://arxiv.org/abs/2606.08994) | Decode-time token-level enforcement, no prompt dependency |

Note what nobody ships: a **policy object**. Answer language is a task constant (XOR-Full),
a dataset split ([IndicGenBench](https://arxiv.org/abs/2404.16816)'s XorQA-In-Xx vs XorQA-In-En),
or a hardcoded prompt string. The two settings of the
[Language Confusion Benchmark](https://github.com/for-ai/language-confusion) — monolingual (match
the query) and cross-lingual (obey an explicit language instruction) — are exactly Oreag's two
policy modes, but they exist as an *evaluation*, not a control surface. This is the single most
defensible product-differentiation claim in the whole design, and it is packaging, not research.

---

## 6. Prompting strategies: XLT, cross-lingual prompting, pivots

These are **reasoning-quality** methods that happen to route through English. They are not
language-control methods, and none of them reports a language-consistency metric. Use them for
accuracy; use §4 for language.

| Method | What it does | Measured |
|---|---|---|
| **XLT** ([EMNLP 2023 Findings](https://aclanthology.org/2023.findings-emnlp.826/), [arXiv](https://arxiv.org/abs/2305.07004)) | One generic zero-shot template that instructs the model to **retell the request in English** first, then reason step by step | MKQA open-domain QA zero-shot: text-davinci-003 29.0 → **40.2**, gpt-3.5-turbo 31.6 → **42.7**; MGSM 23.3 → **70.0**; >10 pts average over 7 benchmarks, and it **narrows the gap between average and best per-language performance** (raises the floor for low-resource languages) |
| **CLP / CLSP** ([EMNLP 2023](https://aclanthology.org/2023.emnlp-main.163/)) | Two-stage: cross-lingual alignment prompting, then task solver prompting; CLSP ensembles reasoning paths across languages | MGSM, gpt-3.5-turbo: Direct 48.6 → Native-CoT 51.0 → En-CoT 57.8 → **Translate-En 68.4** → CLP 70.6 → **CLSP 76.7**. Blunt lesson: naive translate-to-English is already a very strong baseline; alignment prompting adds only +2.2 over it; the real gain (+6.1) is **ensembling across languages** |
| **PLUG** ([ACL 2024](https://aclanthology.org/2024.acl-long.379/)) | Instruction tuning that processes the instruction in an English pivot **and then** produces the response in the target language | **+29%** average instruction-following on X-AlpacaEval (zh/ko/it/es, professionally translated); also tests non-English pivots |
| **CCL-XCoT** ([arXiv:2507.14239](https://arxiv.org/abs/2507.14239)) | Curriculum contrastive alignment, then cross-lingual CoT: reason in a high-resource language, emit in the target low-resource one | Hallucination reduced **up to 62%**, "without relying on external retrieval or multi-model ensembles" |

And the negative result that should temper all of the above for Indic deployments:
[How and Where to Translate?](https://arxiv.org/abs/2507.22923) systematically evaluates
pre-translation vs cross-lingual prompting for RAG-enhanced classification and finds **no
universally best strategy** — the winner flips by model *and* by language. On **Hindi with
Llama-3.1-8B, baseline 38.6% and every translation strategy made it worse, by up to 10.9
points**; on French with BLOOMZ-7b1, translating the prompt gained +13.4; Qwen2.5-7B-Instruct
gained +6.6 on French while losing 12.8 on Hindi. Same shape as
[INDIC QA BENCHMARK](https://arxiv.org/abs/2407.13522): Llama-3 extractive F1 for Assamese is
33.01 translate-test vs 21.29 direct, but Hindi is **46.76 direct vs 26.22 translate-test**.

Direct consequence for Oreag: pivoting is not free, and it is *worst* on Hindi specifically.
The pivot must be gated and measured per language, not applied globally.

---

## 7. Measuring it

- **Instruments in actual use:** `lingua` (used by [XRAG](https://arxiv.org/abs/2505.10089) for
  Response Language Correctness), OpenLID (used by
  [CrossRAG](https://arxiv.org/abs/2504.03616) for "percentage of answers generated in the correct
  language"), and [GlotLID](https://github.com/cisnlp/GlotLID) (fastText, 2,000+ language labels —
  the only one with the coverage for a 40-language product).
- **Metric definitions worth adopting verbatim** from the
  [Language Confusion Benchmark](https://aclanthology.org/2024.emnlp-main.380/): Word-level Pass
  Rate, Line-level Pass Rate, and LCPR (their harmonic mean). Line-level is the honest one —
  whole-response LID hides a wrong-language paragraph inside a mostly-right answer.
- **The code-switching hole.** A whole-response LID scores a Hindi answer studded with English
  technical terms as a pass. [Chirkova et al.](https://aclanthology.org/2024.knowllm-1.15/)
  explicitly report that named-entity code-switching persists in non-Latin-script languages even
  at >95% CLR, and argue evaluation metrics need adjusting for named-entity spelling variation.
  Conversely, [CroCoSum](https://arxiv.org/abs/2303.04092) finds **>92% of 18,000 human-written
  Chinese summaries of English articles contain code-switched phrases** — so code-switching is
  partly the *correct* human behaviour, not purely a defect. Score at sentence or span level and
  decide deliberately which mixing you accept. [LCG](https://arxiv.org/abs/2510.17555) is designed
  around exactly this distinction (it predicts a language *family* and masks only when needed,
  tolerating legitimate code-switching).
- **Graded scoring:** [Language Confusion Entropy](https://arxiv.org/abs/2410.13237) scores the
  degree of confusion from the output language distribution, weighted by typological and lexical
  similarity, instead of LCB's binary pass/fail — and it shows confusion is predictable from
  typological relatedness, which tells you where a script-based heuristic will be blind
  (same-script or typologically close pairs).
- **Ready-made harnesses:** [XRAG](https://github.com/amazon-science/XRAG) scores response-language
  correctness as a first-class dimension and ships both an English-only-retrieval and a mixed
  English+query-language condition. [MIRAGE-Bench](https://github.com/vectara/mirage-bench)'s
  surrogate judge includes a `langid` language-detection feature *and* a separate English-detection
  feature, and reproduces GPT-4o pairwise judgments at Kendall τ = 0.909 across 19 multilingual
  LLMs — cheap ranking without paying for an LLM judge every run.
- **Validate your judge per language before trusting it.**
  [MEMERAG](https://arxiv.org/abs/2502.17163) (1,250 questions across en/de/es/fr/**hi**, 2,322
  expert-annotated sentences) finds the best LLM judge differs by language — GPT-4o mini best in
  English, Qwen 2.5 32B strongest elsewhere — with guidelines + CoT prompting consistently beating
  zero-shot. It also shows sentence-level human annotation is reliable when guidelines are given
  (faithfulness Gwet's AC1 0.84–0.93 vs 0.34–0.42 Fleiss κ in prior work).
- **Tooling gap to plan around:** RAGAS's documented metric set contains no language-consistency or
  answer-language metric. [BERGEN](https://github.com/naver/bergen) supports multilingual queries
  and datastores but its documented metrics (Match, EM, LLMEval) include no language check. You
  will be writing this metric yourself.

---

## 8. The quality ceiling: fluent low-resource answers from English evidence

This is the part to be honest with stakeholders about. Even with perfect retrieval and perfect
language control, generation into a low-resource language from English evidence has a ceiling well
below the English number.

**Direction asymmetry — generating *into* a low-resource language degrades far more than reading
it.** [IndicGenBench](https://arxiv.org/abs/2404.16816) (29 Indic languages, 13 scripts):
FLORES en→xx drops **56.9 → 41.9** from high- to low-resource, while xx→en drops only
**68.2 → 62.6**. Step 4 of the target design is the en→xx direction.

**The absolute ceiling on the exact task shape.** IndicGenBench's XorQA-In-Xx is literally
(Indic question, English passage, Indic answer) across 28 Indic languages, 32k examples — and it
is the hardest task in the benchmark: the best model, **PaLM-2-L, reaches 37.4 Token-F1 one-shot**,
with every model trailing its own English performance by **20+ ChrF/Token-F1 points**. Compare:
XOR-Full state of the art is **42.4 F1** ([CLASS](https://aclanthology.org/2024.emnlp-main.770/)),
CORA was 34.7, and the MT-pipeline baseline in the original
[XOR QA](https://aclanthology.org/2021.naacl-main.46/) paper — translate the question, retrieve
English, generate, translate back — scored **18.7 F1 / 12.1 EM / 16.8 BLEU** against ~40 F1 for
comparable monolingual English systems.

**Model size dominates the low-resource answer quality, more than anything you do at the prompt.**
[Better To Ask in English?](https://arxiv.org/abs/2504.20022) (IndicQuest, 200 QA pairs × 19 Indic
languages + English, factual accuracy 1–5):

| Model | English | Worst Indic |
|---|---|---|
| GPT-4o | 4.24 | 4.11 (Marathi); Hindi **4.32** — no English advantage |
| Gemma-2-9B | 3.69 | 3.16 |
| Llama-3.1-8B | 3.35 | 1.78 |
| Gemma-2-2B | 3.11 | **1.02** (Odia/Urdu flagged "Extremely Low Performance") |

Hallucination rate is also higher in the low-resource Indic responses. A small open generator will
hallucinate in Indic script *even with correct English evidence in context*.

**Fact volume, not just accuracy.** [Multi-FAct](https://arxiv.org/abs/2402.18045): GPT-4 FActScore
spans 0.487 (Chinese, Korean) to 0.633 (Spanish) with English at 0.615 — a ~15-point accuracy gap —
but the sharper deficit is that low-resource languages emit **far fewer correct facts** at
comparable FActScore. Answers get shorter and thinner, not just wronger.

**A mixed-language prompt costs reasoning accuracy independently of retrieval.**
[Crosslingual Capabilities and Knowledge Barriers](https://arxiv.org/abs/2406.16135): on
"mixup"-translated MMLU (question and options split across languages) GPT-4 falls
**81.82 → 68.61 (−13.2 pts)**; Mistral-7B −12.35, Llama3-8B −11.92, Llama2-13B −10.14. Oreag's
generation prompt is mixed by construction (Hindi question + English passages), so budget a
~10–13 point reasoning penalty from the language mix alone. Fine-tuning on out-of-domain
mixed-language text (WikiText-103) recovers only a few points (Llama3-8B 48.62 → 51.75). This is
the strongest argument for [CrossRAG](https://arxiv.org/abs/2504.03616)-style **context-language
normalisation**: translating the retrieved documents removes the mix from the prompt and
simultaneously improves output-language correctness.

**Feeding foreign-language evidence is not unconditionally a win.**
[Cross-Lingual Open-Domain QA with Answer Sentence Generation](https://aclanthology.org/2022.aacl-main.27/)
finds its cross-lingual generative system beats answer-sentence-selection baselines in **all 5**
languages but beats the **monolingual generative pipeline in only 3 of 5**. Mixing evidence
languages helps some languages and hurts others.

**Correct-looking answers are frequently ungrounded across the language boundary.**
[XOR-AttriQA](https://arxiv.org/abs/2305.14332): up to **~47%** of cross-lingual QA answers that
*exactly match the gold reference* are not attributable to any retrieved passage (Japanese 53.1%
attributable, Telugu best at 93.1%). This is invisible to a rank@1 retrieval metric. The cheap
guardrail: PaLM 2 fine-tuned on only **~100 attribution examples** reaches 92–96% accuracy /
95–98% ROC AUC at detecting attribution. For automatic grading across the language boundary,
[DoGMaTiQ](https://arxiv.org/abs/2605.04458) generates QA-shaped nuggets that "decouple the
information need from the potentially diverse content that satisfies it" — the only grading form
that survives a Hindi answer string that can never lexically match its English source.

**Abstention is a separate unsolved axis.** [NoMIRACL](https://arxiv.org/abs/2312.11361)
(18 languages, 31 native-speaker annotators): LLaMA-2 and Orca-2 exceed an **88% hallucination
rate** on the non-relevant subset, while the low-hallucination models (Mistral, LLaMA-3) swing to a
**74.9% error rate** on the relevant subset. No open model balances "admit nothing is relevant"
against "use the passage that is relevant." GPT-4 gives the best tradeoff.

**Scale does not buy cross-lingual consistency.**
[Cross-Lingual Consistency of Factual Knowledge](https://aclanthology.org/2023.emnlp-main.658/)
introduces RankC and shows model size raises factual-probing *accuracy* in most languages but does
**not** improve cross-lingual *consistency*; edited facts propagate only to languages with high
RankC to the source. Grounding both answers in the same retrieved passage is the only thing that
makes your Hindi and English answers agree.

**Do not reach for per-language fine-tunes as the default fix.**
[MILU](https://arxiv.org/abs/2411.02538) (8 domains, 41 subjects, 11 Indic languages, 42+ LLMs)
finds open multilingual models **outperform language-specific fine-tuned models**, which score only
slightly above random; GPT-4o tops out at 74% average. The counterexample is narrow and worth
knowing: [Airavata](https://arxiv.org/abs/2401.15006), Hindi instruction-tuned, scores **46.8**
one-shot on XorQA-In-Xx for Hindi (vs LLaMA's 30.3) but only 31.6 on XorQA-In-En and near-zero on
all *other* Indic languages. Language-specific tuning buys exactly one language.

Underlying cause, useful for a motivation slide:
[Krutrim](https://arxiv.org/abs/2502.09642) notes Indic languages are **~1% of Common Crawl** while
India is 18% of world population, and the
[Language Ranker](https://arxiv.org/abs/2404.11553) shows representation similarity to English
tracks pretraining share almost directly (German, 0.17% of corpus, scores 0.723; Kannada, ≤0.01%,
scores 0.236) and correlates with downstream ARC/MMLU accuracy in that language.

---

## 9. What this means for the Oreag build

Ordered, cheapest first.

1. **Measure before changing anything.** Add a Line-level Pass Rate over GlotLID (or `lingua`) to
   every generation, segmented by query language and by whether the cross-lingual path fired. The
   80/80 rank@1 number measures retrieval; it says nothing about §2's failure mode, and §2's
   failure mode is between 5% and 50% depending on the generator you happen to be calling.
2. **Move from rung 0 to rung 2.** Adding an explicit `respond in {L}` instruction is not enough
   (24.85% wrong-language on Arabic despite it). Translating the *prompt scaffold* into the user's
   language plus the instruction is what got Chirkova et al. above 95%. It costs one cached
   translation per supported language, not one per query.
3. **Treat the generator as a language-control decision, not just a quality decision.** The LCB
   spread is ~60 points between Command R+/GPT-4o and the Llama instruct family in the
   cross-lingual setting. If you self-host, you gain rungs 5–6 (SCD / LCG / LATB / ReCoVeR),
   which are training-free and move consistency 20–90 points; if you are API-only, rung 2 + rung 3
   is your ceiling.
4. **Lower the temperature and avoid beam search on the cross-lingual path.** Both are measured
   aggravators, and RAG's long prompts are the third.
5. **For mixed-language corpora, normalise the context language before generation.** This is the
   one change that improves retrieval-side consistency *and* output-language correctness *and*
   removes the ~10–13 point mixed-prompt reasoning penalty at once. It costs one MT call per
   retrieved chunk — use a local model (NLLB-200-distilled-600M or IndicTrans2 for the 22 scheduled
   Indian languages) rather than an LLM call, or do it at index time.
6. **Gate the pivot per language, not globally.** Hindi is the documented worst case for
   translate-test in two independent studies; the pivot that helps Assamese halves Hindi.
7. **Score groundedness separately from language.** Rank@1 plus a fluent Hindi answer is compatible
   with ~47% non-attribution. Nugget-based scoring or a small attribution classifier (~100 examples)
   is the cheap version.
8. **Set expectations at ~37 Token-F1, not ~90%.** That is the published ceiling on the exact task
   shape across 28 Indic languages with a frontier model.
