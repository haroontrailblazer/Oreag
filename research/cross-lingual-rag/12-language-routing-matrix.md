# 12 — The Language Routing Matrix

Complete routing design for cross-lingual retrieval in Oreag. Covers the four cases the current gate does not handle, in the order they should be built.

**Evidence markers used throughout**
- `[S]` = measured on **sentences or longer**. Every published LID accuracy figure in this document is `[S]` unless marked otherwise. Assume a 3–10 word query performs materially worse.
- `[Q]` = measured at **query length** (MS MARCO / mMARCO / MKQA / Multi-EuP titles / 10-char strings). Rare and valuable.
- `[UNVERIFIED]` = the number or claim did not survive source verification, or is an inference rather than a measurement. Do not build a decision on it without re-reading the source.
- `[EXTRAPOLATED]` = a short-query figure derived by interpolation, not measured at that length by anyone.

---

## 1. The hole in the current gate, stated precisely

```python
def scripts(text) -> frozenset[str]:
    # returns which NON-LATIN writing systems appear. English/French -> EMPTY SET.

def should_consider(project, question) -> bool:
    asked = scripts(question)
    if not asked: return False          # <-- exit point
    corpus_scripts = corpus_profile(project)
    return not (asked & corpus_scripts)
```

Two independent defects:

**Defect 1 — `if not asked: return False`.** `scripts()` returns the empty set for any string containing no non-Latin codepoints. That is true of *every* English query and *every* romanized Indic query. `"what is the refund policy"` → `∅`. `"refund policy kya hai"` → `∅`. `"enna refund policy"` → `∅`. Both exit at line 1 of the predicate, before the corpus is ever consulted. The gate is not a language gate; it is a **non-Latin-codepoint detector**, and it treats "no non-Latin codepoints" as "no cross-lingual problem."

**Defect 2 — `not (asked & corpus_scripts)`.** Even for non-Latin queries, the gate fires only when the corpus *lacks* the query's script. A Hindi question over an English+Hindi corpus satisfies `asked & corpus_scripts` (devanagari ∈ both), so the gate stays silent — precisely the case where same-language attraction guarantees the query never reaches the English half. The predicate assumes that script presence in the corpus implies the query can reach everything in the corpus. It implies the opposite: script presence guarantees a same-language cluster for the query to fall into.

**Defect 3 (consequence) — the trigger is the wrong signal.** After the gate fires, remediation is conditioned on the retrieval scoring below a 0.40 cosine floor. A floor measures *confidence*, not *correctness*. In a mixed corpus the same-language distractors that outrank the correct cross-language chunk score comfortably above 0.40. LAReQA quantifies this directly: removing a single gold answer degrades retrieval far more when it was same-language (Δ 0.37 mAP) than cross-language (Δ 0.02) — the model prefers same-language answers, and those preferred answers are high-scoring. https://arxiv.org/abs/2004.05484 `[S]`

### Handled vs unhandled, exhaustively

| Query | Corpus | `scripts(q)` | `asked & corpus` | Gate fires? | Correct? |
|---|---|---|---|---|---|
| Hindi (Devanagari) | English only | `{devanagari}` | ∅ | **YES** | ✅ handled — 80/80 rank-1, 40 languages |
| Tamil, Arabic, CJK … | corpus lacking that script | non-∅ | ∅ | **YES** | ✅ handled |
| Hindi (Devanagari) | Hindi only | `{devanagari}` | `{devanagari}` | no | ✅ correct — monolingual path |
| **Hindi (Devanagari)** | **English + Hindi** | `{devanagari}` | `{devanagari}` | **no** | ❌ **Case C** |
| **English** | **Hindi / Tamil / Arabic only** | **∅** | — | **no (exits line 1)** | ❌ **Case A** |
| **English** | **English + Hindi** | **∅** | — | **no (exits line 1)** | ❌ **Case A′ (mixed)** |
| English | English only | ∅ | — | no | ✅ correct — monolingual path |
| **Hinglish / Tanglish** | **English only** | **∅** | — | **no (exits line 1)** | ❌ **Case B** |
| **Hinglish / Tanglish** | **Hindi / Tamil only** | **∅** | — | **no (exits line 1)** | ❌ **Case B′ (script mismatch)** |
| **Hinglish / Tanglish** | **English + Hindi** | **∅** | — | **no (exits line 1)** | ❌ **Case D** |
| Code-mixed native script ("refund policy क्या है") | any | `{devanagari}` | depends | sometimes | ⚠️ fires by accident on the Devanagari fragment |
| **Hindi (Devanagari)** | **Tamil only** | `{devanagari}` | `{tamil}` | YES | ⚠️ fires, but remediation targets the wrong language — the fifth, unlisted case: X→Y where neither is English |

Seven broken rows, one accidental, one unlisted. The single clean generalization: **the gate covers exactly the direction the multilingual embedding literature already optimizes for, and nothing else.** Multilingual encoders are trained predominantly on English-centric (En-X) parallel data, so X→English is the direction the training recipe targets — multi-way parallel training beats En-X bilingual training by 21.3% on bitext mining, 5.3% on STS and 28.4% on classification, which is direct evidence that En-X pivoting is the *default* recipe and a suboptimal one (https://arxiv.org/abs/2602.21543). The 80/80 result is not evidence the design is right; it is evidence Oreag built for the direction that was already working.

---

## 2. THE MASTER ROUTING TABLE

### 2a. Decision grid (action only)

Columns are corpus profiles. `|L|` = number of languages present in the project's chunks.

| Query type | Corpus: monolingual, **same** language | Corpus: monolingual, **other** language | Corpus: **mixed** (`|L| ≥ 2`) |
|---|---|---|---|
| **Native non-Latin** (Hindi Devanagari, Tamil, Arabic) | **Nothing.** Monolingual path. | **Translate query → corpus language, embed translation.** *(the one case handled today)* | **Balanced retrieval:** k per language slice → existing RRF. No query-side translation. |
| **English** (Latin, `scripts()=∅`) | **Nothing.** Monolingual path. | **CASE A — dual-query translate-and-merge.** Embedder-dependent; probe first. | **CASE A′ — balanced retrieval.** No translation. |
| **Romanized Indic** (Hinglish, Tanglish) | **CASE B′ — LLM-translate to the corpus language (native script), embed that.** Never word-by-word transliterate. | **CASE B — LLM-translate to English, embed the translation only.** Do not blend, do not embed raw. | **CASE D — translate to English *and* balanced retrieval.** The Indic slice is the exposed side. |
| **Code-mixed** (intra-sentential, either script) | Translate to the corpus language. | Translate to the corpus language. Matrix-language judgement decides which. | Same as Case D. |

### 2b. Cell detail — action, evidence, cost

| # | Cell | What should happen | Evidence | Cost |
|---|---|---|---|---|
| 1 | Native non-Latin → same-language corpus | Nothing. | Monolingual is the ceiling in every study: BGE-M3 AR→AR Hit@20 92±3% vs 56±5% cross-lingual (https://arxiv.org/html/2507.07543v2). `[S]` | 0 |
| 2 | Native non-Latin → other-language corpus | Current path: cosine floor → LLM-translate the question → embed the translation; original still drives generation. **Keep it, but stop gating it on script.** | Already at 80/80 rank-1 in-house across 40 languages. Independently: LAReQA translate-test 0.72 mAP beat every direct multilingual encoder (best 0.66) on XQuAD-R (https://arxiv.org/abs/2004.05484). Note this direction was *already* healthy for BGE-M3 (AR→EN 90±3%), so the translation is belt-and-braces, not the load-bearing fix. `[S]` | 1 LLM call (already made) |
| 3 | Native non-Latin → **mixed** corpus (**Case C**) | **Balanced retrieval.** Retrieve top-k from each language slice independently; fuse with the existing rank-only RRF k=60. **No translation** — translation is the wrong tool here. | Language-oracle ablation: restricting the index to the language holding the gold doc "achieves nearly identical performance across all query and document language pairs, suggesting there are essentially no failures related to the query-document language mismatch challenge… the main source of failure lies in the document-document language mismatch challenge, namely the retriever's ability to rank documents across languages" (https://arxiv.org/html/2507.07543v2). Magnitude: >70% of top-5 comes from English + query language alone across 13 languages with BGE-M3 (https://arxiv.org/abs/2604.20199); mE5-large returns a query-language passage 99.92% of the time on XQuAD even when a parallel passage exists in every other language (https://arxiv.org/abs/2605.07249) `[UNVERIFIED — that paper's MLQA figure is 96.15%, not 99.92%; its bge-m3 per-language breakdown could not be located and must not be cited]`. Parallel passages land a mean **410 ranks apart** on XQuAD-R (https://arxiv.org/abs/2408.10536), so a top-20 cannot contain both. `[S]` | 1 extra filtered pgvector scan + 1 extra FTS scan per additional language. 0 API calls. "balanced incurs no additional cost beyond retrieving documents from the index" |
| 4 | English → same-language corpus | Nothing. | — | 0 |
| 5 | **English → other-language corpus (CASE A)** | Dual-query translate-and-merge: translate the English query into the corpus language, retrieve with both embeddings, fuse by **rank** (not score). Gate on the per-embedder probe (§7 step 0), not on script. | BGE-M3 EN→AR Hit@20 **56±5%** against EN→EN 86±4%, AR→EN 90±3%, AR→AR 92±3%; end-to-end accuracy 31±5% vs 68±5% (https://arxiv.org/html/2507.07543v2). mE5-large is worse and breaks both ways (EN→AR 41%, AR→EN 51%). Script distance sizing at query length: mMARCO zero-shot mMiniLM MRR@10 EN→DE 24.0 vs DE→DE 25.9 (−7%, same script) but EN→AR 14.0 vs AR→AR 23.9 (**−41%**, different script) — https://arxiv.org/abs/2305.05295 `[Q]`. Mitigation measured: EN→AR Legal Hit@20 56% → ~85–86% (BGE-M3) and 41% → ~63% (mE5), with **"no statistically significant loss relative to the direct retriever in same-language cases."** | 1 translation call (~300–800 ms) + 1 extra embedding + 1 extra scan |
| 6 | English → **mixed** corpus (**Case A′**) | **Balanced retrieval, no translation.** English is already in the index; a translated query buys nothing. | Ratio-controlled mMARCO interpolation study, 105 conditions: with English documents present, mixing the query embedding gives mean Δ **−0.04** nDCG@10; with no English present, mean **+0.95** (max +2.92, EN-AR on AR docs) — https://arxiv.org/pdf/2606.13537v1 `[Q]`. The gap is the ranking, not the matching: SHIFT's motivating measurement is 10 of 14 top results English for an English query on Belebele despite gold passages existing in all 14 languages (https://arxiv.org/abs/2606.18801). | 1 extra scan per language |
| 7 | **Romanized Indic → same-language corpus, native script (CASE B′)** | LLM-translate the query into the corpus language **in native script**, embed that. **Do not** run word-by-word transliteration. Optionally RRF-fuse the transliterated and translated variants. | Leaving it alone destroys the dense half: BGE-M3 on uroman-Latinized Chinese queries against native-script docs falls MRR@10 0.2342 → **0.0078** and Recall@1000 0.894 → **0.055**; Russian 0.2444 → 0.1244 and 0.900 → 0.659 (https://arxiv.org/pdf/2505.08411) `[Q]`. Transliteration back to Devanagari is lossy: Dakshina single-word Latin→native WER Hindi 50.0–53.1, Bengali 50.6–54.7, Punjabi 59.1–60.6 (https://arxiv.org/pdf/2007.01176); IndicXlit top-1 accuracy averages **60.58%** over 12 languages (hi 60.56, ta 68.10, bn 55.49, ur 42.12) — https://arxiv.org/pdf/2205.03018. At ~60% per word, a 6-word query is rarely fully correct. `[S]` | 1 LLM call |
| 8 | **Romanized Indic → other-language (English) corpus (CASE B)** | Detect via the LLM call you already make, then **translate to English and embed the translation alone.** Do not embed a blend of the two; do not embed the raw code-mixed string. | MiLQ, MAP@100 on English documents: low-resource Mono-Distill 36.34 (mixed query) → **56.92** with NMT; BM25 38.35 → 48.10; high-resource BM25 34.92 → 47.08 (https://arxiv.org/pdf/2505.16631). Authors: *"NMT on mixed-language queries (Mixed→EN) surpassed NMT on native queries (XX→EN). This suggests English terms in mixed queries aid translation."* Embedding-level mixing beats word-level code-mixing, and pure English beats both when English docs are in the index (https://arxiv.org/pdf/2606.13537v1) `[Q]`. Why it degrades rather than collapses today: romanized Hindi sits *closer* to English than Devanagari does in a Latin-heavy space — Llama-2 last-token cosine En↔Native 0.40 vs En↔Romanized 0.50 for Hindi, 0.39/0.47 Gujarati, 0.44/0.48 Marathi — **but not for Tamil (0.44/0.43)** — https://arxiv.org/pdf/2401.14280v3. So Case B fails *silently and partially* for Indo-Aryan and harder for Dravidian; the 0.40 cosine floor may not fire. `[S]` | 1 LLM call (fold into the existing one) |
| 9 | **Romanized Indic → mixed corpus (CASE D)** | Translate to English **and** run balanced retrieval. The English half is already partly reachable; the Indic half is the exposed side. | MiLQ, retrieving **English** documents, BM25 MAP@100: native query 10.07 vs mixed query **36.29** — a code-mixed query is 3.6× better at reaching English content than a native-script one. Retrieving **native** documents, nDCG@20: monolingual query 32.19 vs mixed query **11.94** (https://arxiv.org/pdf/2505.16631). Balanced retrieval covers exactly that exposure and is script-agnostic, so it works without detecting that the query is Hinglish at all. `[S]` | 1 LLM call + 1 extra scan per language |
| 10 | Code-mixed, native script, → same-language corpus | Translate/normalize to the corpus language. Matrix language decides the target. | Matrix Language Identification is the exact primitive: gpt-4o **98.1 F1 zero-shot**, command-a 98.3, claude-3.5-sonnet 90.0 zero-shot / 98.8 one-shot (https://arxiv.org/pdf/2503.21670v3). `[S]` | 0 marginal (fold into existing call) |
| 11 | Code-mixed → other-language corpus | Same as cell 8, target = corpus language. | As cell 8. | 1 LLM call |
| 12 | Code-mixed → mixed corpus | Same as cell 9. | As cell 9. | 1 LLM call + extra scans |
| 13 | *(unlisted fifth case)* Non-Latin X → monolingual non-Latin Y corpus | Translate X→Y. The current gate fires but remediation must target Y, not English. | This is the direction with the weakest guarantee — En-X pivoted training aligns every language to English, not to each other (https://arxiv.org/abs/2602.21543). Reciprocity between two Indic languages exceeds EN-X for Gemini (Hi-Bn 0.339 vs En-Hi 0.253) and Qwen (0.268 vs 0.163) but is **below** En-Ar for both OpenAI models and ties for Mistral (https://arxiv.org/abs/2605.26575) `[UNVERIFIED — that paper's own prose claims "every model except Mistral"; its Table 6 contradicts this for both OpenAI models. Do not repeat the paper's overclaim.]` | 1 LLM call |

### 2c. Cross-cutting: the Postgres FTS half is a hidden, unintended language router

Migration `0039_per_project_text_search.sql` already stores a per-row `chunks.ts_config` (a `regconfig`) that feeds the generated `content_tsv`, written today from the **project's** document language. In a mixed English+Hindi project, the Devanagari half is being stemmed and stopword-filtered under `english` rules — a language filter nobody installed, applied at ingest, before any vector search runs.

- Lexical retrieval is where mixed-corpus bias is worst. Multi-EuP indexes 22K EU Parliament docs in 24 languages as one pool: English queries MRR@100 **62.79%**, Polish **4.80%** (BM25 k1=0.9, b=0.4). Their mitigation: *"using a whitespace tokenizer for both the collection and queries reduces language bias"* while maintaining similar overall performance — https://arxiv.org/html/2311.01870v1 `[Q]` (headline-length queries).
- Sparse retrieval is structurally weak cross-lingually: BGE-M3 MIRACL nDCG@10 dense 69.2 vs sparse 53.9; on MKQA cross-lingual, *"there are only very limited co-existed terms for cross-lingual retrieval"* (dense 75.1, sparse 45.3) — https://arxiv.org/html/2402.03216v4.
- **PostgreSQL does support per-row configurations.** The docs describe it explicitly: `CREATE INDEX pgweb_idx ON pgweb USING GIN (to_tsvector(config_name, body))` … *"This allows mixed configurations in the same index while recording which configuration was used for each index entry. This would be useful, for example, if the document collection contained documents in different languages."* — https://www.postgresql.org/docs/current/textsearch-tables.html. The real constraint is narrower: the configuration must be named explicitly (two-arg `to_tsvector` is IMMUTABLE; the one-arg form reads a GUC and is only STABLE), and the tsquery must be constant across an index scan — hence one FTS scan per distinct language, not one scan with a variable config. `[UNVERIFIED — an earlier draft of this research cited a quote from textsearch-intro.html claiming separate tsvector columns are required per language. That quote does not exist in the PostgreSQL documentation and the docs describe the opposite as a supported pattern. Do not design around it.]`
- Snowball coverage decides who benefits: **Hindi, Tamil and Nepali have stemmers; Bengali, Telugu and Marathi do not** (https://snowballstem.org/algorithms/ lists 38 algorithms over ~35 languages; `backend/app/services/text_search.py` maps 28 regconfigs, of which 17 are marked MEASURED and the rest merely available). For Bengali/Telugu/Marathi the lexical half cannot help and the vector half must carry the case.

---

## 3. Case A — reverse direction. Is it actually a problem?

**Short answer: yes, and it is the *only* direction that broke for the embedder most likely to be a default. But the size is a property of the user's chosen embedding model, not a constant, and it has never been measured for any Indic language.**

### The one paper that runs all four cells

The Cross-Lingual Cost (ArabicNLP 2025) is the closest published analogue to Oreag's architecture: domain corpora (390 UAE laws, ~1.3K QA pairs; ~2K travel), 50/50 language assignment at corpus construction, 100-token passages, hybrid-shaped stack. https://arxiv.org/html/2507.07543v2

| Embedder | Benchmark | AR→AR | AR→EN | EN→EN | **EN→AR** |
|---|---|---|---|---|---|
| BGE-M3 | Legal, Hit@20 | 92±3 | 90±3 | 86±4 | **56±5** |
| BGE-M3 | Legal, end-to-end acc. | 68±5 | 67±5 | 68±5 | **31±5** |
| BGE-M3 | Travel, Hit@20 | — | 91.0 | — | **80.0** |
| M-E5-large | Legal, Hit@20 | 87±4 | 51±5 | 88±4 | **41±5** |
| M-E5-large | Legal, end-to-end acc. | 67±5 | 37±5 | 70±5 | **22±4** |

The paper's own words: *"the reverse cross-lingual setting does not exhibit any statistically significant degradation for BGE-M3."* Read the row Oreag's gate covers (AR→EN, 90%) against the row it ignores (EN→AR, 56%). **The gate fires on the healthy direction and stays silent on the broken one.**

Two distinct failure profiles exist, and neither matches Oreag's gate:
- **English-attractor** (BGE-M3): pulls toward English docs whenever the query is English. X→EN fine, EN→X broken.
- **Same-language-attractor** (mE5): pulls toward the query's own language regardless. Both directions broken.

No embedder was found with the profile Oreag's gate assumes (X→EN hard, EN→X easy).

### Sizing at query length

The only genuinely query-length script-distance measurement (mMARCO, real Bing queries): zero-shot mMiniLM MRR@10 — same-script cross-lingual EN→DE 24.0 against the DE→DE ceiling of 25.9 (**−7%**); different-script EN→AR 14.0 against AR→AR 23.9 (**−41%**). https://arxiv.org/abs/2305.05295 `[Q]`. Devanagari and Tamil are as script-distant from Latin as Arabic, so **plan for ~40% relative first-stage retrieval loss on Case A at query length.** (Caveat: mMARCO's non-English corpora are machine translations of English, so this is English-query-vs-MT-Arabic-corpus.)

### The honest counter-evidence, and why it does not rescue Case A

NeuCLIRBench (TREC NeuCLIR 2022–24 consolidated, 250,128 judgments) shows English queries against Chinese/Persian/Russian documents reaching **parity** with multi-monolingual retrieval: Rank-K nDCG@20 ZH 0.653 mono vs 0.655 cross; FA 0.659 vs 0.671; RU 0.642 vs 0.636. https://arxiv.org/abs/2511.14758

Two disqualifiers:
1. **Query length.** *"Queries in NeuCLIRBench are the concatenation of the title and description"* — multi-sentence TREC topics, an order of magnitude longer than a 3–10 word query.
2. **The parity is produced by a 32B-parameter LLM listwise reranker over an already-fused candidate set, not by a dense first stage.** First-stage bi-encoders in the same table still show a gap (e5-large mono avg 0.318 vs cross avg 0.289; BGE-M3-Sparse collapses to 0.061 cross). BM25 mono ZH 0.391 / RU 0.408 / FA 0.391 vs BM25-with-document-translation 0.439 / 0.400 / 0.447.

The correct reading is narrower and more useful: **given a good candidate set and a strong reranker, the cross-language penalty is recoverable.** That localizes Case A to first-stage recall — the same place the Cross-Lingual Cost localized it. Two papers agree once you separate the stages. Practical consequence: **Case A cannot be fixed by tuning the cosine floor or the RRF constant.** Both are ranking-stage knobs. It must be fixed at candidate generation.

### Recommendation for Case A

Do **not** do nothing — but do not build it first, and do not hard-code a policy.

1. Because the failure profile flips between BGE-M3 and mE5 on identical data, and because MLAIRE measures a 24%→~99% same-language-preference spread across 31 retrievers on identical pools, **the correct gate is model-dependent.** With 22 selectable embedders, run a per-project probe (§7 step 0) rather than a global rule.
2. The mitigation is safe to run unconditionally: both query-translation and balanced retrieval showed *"no statistically significant loss relative to the direct retriever in same-language cases."* A strategy with no measured downside does not need a precise gate.
3. **The Indic reverse direction has never been published.** BGE-M3's own evaluation is X→EN by construction (MKQA: *"it needs to retrieve the passages containing answers from the English Wikipedia corpus"*) or strictly monolingual (MIRACL: *"designed to support… monolingual retrieval, where the queries and the corpora are in the same language"* — https://arxiv.org/abs/2210.09984). The nearest Indic-specific benchmark reports cross-lingual transfer as a single aggregate (E5-Large-Instruct Recall@1 27.4% monolingual → 20.7% cross-lingual, 8 embedders, 12 Indian languages, https://arxiv.org/abs/2601.10205) with **no directional decomposition**, and its task is persona/instruction alignment, not document retrieval — do not quote 27.4% as a retrieval number. **Build the mirror-image eval in-house** by reusing the existing 40-language fixtures with query and corpus swapped. It is cheap and it is genuinely novel measurement.

---

## 4. Case B — romanized Indic

### 4a. Detection options, with short-query accuracy

**Every figure in this table is `[S]` (sentence-level) unless marked.** The benchmarks systematically *exclude* query-length text: IndicLID's authors filtered ~7% of the Dakshina test set, specifically *"sentences shorter than 5 words"* that were named entities and English loanwords, as *"not useful for romanized text LID evaluation."* GlotLID's evaluation *"discard[s] the 35% shortest sentences for each language."* The Language Confusion Benchmark applies fastText *"only to sequences of more than 4 words as its LID predictions are less precise for shorter sequences."* **There is no published evaluation of any LID system on 3–10 word romanized Indic queries. That absence is itself a finding.**

| Detector | Has romanized Indic labels? | Accuracy on romanized Indic | Size / speed | Verdict |
|---|---|---|---|---|
| **OpenLID** (201 langs) | **No — zero.** Every Indic label is native-script (`hin_Deva`, `tam_Taml`, `urd_Arab`); 126 `_Latn` labels, none Indic. https://arxiv.org/pdf/2305.13820 | n/a — categorical failure | fastText, sub-ms | **SKIP.** Its 0.93 macro-F1 is irrelevant here. Fine for the native-script corpus profile; note the HF repo is **GPL-3.0**. |
| **CLD3** | **hi-Latn only.** No `ta-Latn`/`bn-Latn`/`te-Latn`/`mr-Latn`. https://github.com/google/cld3 | No published hi-Latn figure found. 4,861 sent/s, 98.03 F1 on *native* script (IndicLID Table 3). `[UNVERIFIED — the "0.187 ms/sample / 5,356 per second" figure circulating in earlier drafts is fabricated; it appears in no source.]` | tens of MB | **SKIP.** Silently returns `en` for Tanglish, romanized Bengali/Telugu/Marathi. |
| **franc** | No romanized variants (UDHR-trained). | Babel-670 native script: 81.05 acc / 66.28 F1 over 216 langs. Own README: *"franc supports many languages, which means it's easily confused on small samples. Make sure to pass it big documents to get reliable results."* default `minLength` 10 chars. https://github.com/wooorm/franc | tiny | **SKIP.** Self-disqualifying for queries. |
| **langdetect / langid.py** | No. | 10-char strings, 20 Latin-script languages: langid.py acc@1 **61.73%** (UD) / **53.47%** (OpenSubtitles); pretrained fastText lid.176 **70.45% / 67.73%** (acc@3 85.84 / 84.15). Confusion shows *"a strong bias towards some languages like English (en), French (fr), or Dutch (nl)."* https://aclanthology.org/2021.eacl-srw.6.pdf **`[Q]` — the only true short-string measurement in this literature** | tiny | **SKIP.** The English bias is exactly the failure mode: a short Latin string defaults to English, which is what makes Hinglish invisible. |
| **GlotLID v3** | **Yes** — `hin_Latn`, `tam_Latn`, `ben_Latn`, `tel_Latn`, `mar_Latn`, `guj_Latn`, `kan_Latn`, `mal_Latn`, `npi_Latn`, `pan_Latn`, `urd_Latn`. | Self-reported `hin_Latn` F1 **0.9856** — but that is a held-out split of GlotLID's own web corpus (1,943 of 2,102 labels sit ≥0.97). **Independently, on real LinCE Hinglish: 17/29 exact on monolingual romanized Hindi and 5/253 on code-switched Hinglish** (https://arxiv.org/pdf/2406.06263v1). Authors' own FAQ: *"primarily trained on longer sentences, avoid using it on very short sentences."* | **model_v3.bin = 1,687,094,687 bytes (1.69 GB)** | **SKIP as a positive Hinglish signal.** Usable only as a cheap **negative** pre-filter (high-confidence `eng_Latn` ⇒ skip the LLM language judgement). |
| **IndicLID** (the only purpose-built one) | **Yes**, 22 languages × 2 scripts. | Ensemble 80.40% acc / 74.72 macro F1 — but **romanized Hindi F1 63.06 (recall 53.32)**, Urdu 60.41, Nepali 52.98, Maithili 29.25. Versus **Kannada 96.03, Tamil 95.01, Bengali 94.44, Malayalam 93.30, Telugu 92.58, Marathi 88.92**. Synthetic vs human romanization: 95.96% vs 80.40%. Own Fig. 3: *"The LID is most confused for short inputs (<10 words)"* (plot only, no numbers). https://arxiv.org/pdf/2305.15814 | FTR 357 MB @ 37,037/s; **ensemble 1.4 GB @ 10 sent/s** (low-confidence inputs route to a 1.1 GB IndicBERT — a short query hits the slow path almost every time) | **SKIP for Hinglish** (misses ~half of true romanized Hindi on full sentences). **CONSIDER FTR-only for Tanglish/Telugu/Kannada/Malayalam**, where romanized F1 is 92–96 and it is a genuine cheap win. |
| **Google 2025 SOTA** (synthetic spelling variation + fastText) | Yes, 20 Indic languages. | **88.2 macro F1 / 92.2 acc** on Bhasha-Abhijnaanam, beating mT5-large (87.1). Hindi F1 65.5 → **83.4** (recall 59.9 → 85.7), Urdu 56.3 → 74.3, Punjabi 78.0 → 90.7. https://arxiv.org/abs/2504.21540v3 | would be a fastText linear model, sub-ms | **NOT AVAILABLE.** The repo ships only data-generation scripts (`create_supplementary_lexicons.sh`, `train_pair_lm.sh`) — **no trained binary** — and needs OpenFst + OpenGrm Baum-Welch + OpenGrm Ngram. This is a research week, not an afternoon. Keep it as proof that a small model *can* reach ~83 F1 on romanized Hindi. |
| **MaskLID** on top of GlotLID | Training-free multi-label. | Hindi-English exact-match 5/253 → **29/253** (11.5%). But English monolingual exact match drops **486 → 459** of 490 — you start mislabelling plain English, a regression on the 95%+ of queries that are fine today. https://arxiv.org/pdf/2406.06263v1 | a few extra fastText passes | **SKIP at query time.** Chunk-time flag only (its min-span parameter is 20–25 word features). |
| **Fine-tuned encoder** (mBERT / XLM-R / MuRIL) | Yes with in-domain supervision. | LinCE HIN-ENG token-level LID: ML-BERT **96.44**, ELMo 96.21 (4,823 posts / 95,224 tokens ≈ 19.7 tokens/post). https://arxiv.org/pdf/2005.04322v1. **Do NOT cite GLUECoS's 96.6** — its FIRE En-Hi LID corpus is marked "(D)" for Devanagari: *"we report LID results for Hindi in Devanagari."* https://arxiv.org/pdf/2004.12376 | 110–278M params | **SKIP for v1** (needs labelled Hinglish queries you do not have). This is the ceiling if you ever accumulate query logs — MuRIL is the natural base, being the one widely available checkpoint with transliterated Indic in its pretraining mixture (https://arxiv.org/abs/2103.10730). |
| **LLM you already call** | n/a | **Matrix Language Identification — literally the routing decision:** gpt-4o **98.1 F1 zero-shot / 98.1 one-shot**; command-a-03-2025 98.3 / 98.3; claude-3.5-sonnet 90.0 zero-shot / **98.8 one-shot**. Token-level LID (a harder, different task): gpt-4o 92.7/93.8, claude-3.5-sonnet 92.1/92.5, vs Microsoft's dedicated LID-tool at **74.4**. https://arxiv.org/pdf/2503.21670v3 (COMI-LINGUA, 125K expert-annotated Hinglish instances, LID IAA 0.834, MLI IAA 0.976, mean CMI 20.87) | 0 marginal if folded into an existing call | **✅ RECOMMENDED.** |

### 4b. Recommended detector: the LLM call you already make

Ask for `{language, script: native|romanized|mixed, matrix_language}` in the JSON of the call the gate already performs. Four operational riders:

1. **Ask for the MATRIX LANGUAGE, not token-level tagging.** MLI is the task that scores 98; token tagging is the task that scores 92, and a fine-tuned XLM-R-560M still edges GPT-3.5 there (86.65 vs 80.19 — https://arxiv.org/pdf/2305.14235v2).
2. **Do not route this to a small/fast model.** gemini-1.5-Flash scores **33.7 F1** on MLI zero-shot (56.4 one-shot) against gpt-4o's 98.1. The flagship-vs-mini choice is worth ~60 F1 points. Open-weight models are worse still: LLaMA-3.3-70B 73.1 zero-shot MLI, mistral-instruct 42.4 zero-shot LID.
3. **Weigh the counter-evidence correctly.** "Fumbling in Babel" shows GPT-4 lagging dedicated tools on 670-language open-set identification (CLD3 96.02 acc vs GPT-4 93.65; Latin-script average F1 **17.64%** across 670 languages — https://arxiv.org/pdf/2311.09696v2). That is a *breadth* result. Oreag needs a two-way, in-distribution, semantically-loaded judgement over a handful of languages the project already declares — the regime where the LLM wins.
4. **Short-query behaviour is an inference, not a measurement.** `[UNVERIFIED]` The argument that the LLM degrades gracefully on short input — because it uses lexical semantics ("kya hai" is unambiguous to a model that knows Hindi) rather than character-n-gram statistics that need volume — is plausible and is why this recommendation stands, but **COMI-LINGUA publishes no length ablation**, and its data is Hindi-English social media at mean CMI 20.87, not queries. Measure it in-house on your own query logs before trusting a number.

Optional cheap pre-filter: GlotLID or fastText at ~0.166 ms/sample as a **negative** filter only — high-confidence `eng_Latn` ⇒ skip the LLM judgement. Never as the positive Hinglish signal.

### 4c. What to do once detected

The evidence is unusually clean. **Translate to the corpus language. Do not transliterate to Devanagari. Do not leave alone. Do not blend.**

| Action | Verdict | Evidence |
|---|---|---|
| Leave alone | ❌ unsafe for the dense half | BGE-M3 romanized-query collapse: MRR@10 0.2342→0.0078, R@1000 0.894→0.055 (ZH); 0.2444→0.1244, 0.900→0.659 (RU). https://arxiv.org/pdf/2505.08411 `[Q]` |
| Translate to corpus language, embed translation | ✅ **the action** | MiLQ: Mono-Distill low-resource mixed→EN 36.34 → **56.92**; BM25 38.35 → 48.10. *"English terms in mixed queries aid translation."* https://arxiv.org/pdf/2505.16631. Your LLM can do it: GPT-3.5 zero-shot Hinglish→English 27.64 BLEU vs a fine-tuned M2M100-418M's 28.53 (https://arxiv.org/pdf/2305.14235v2). |
| Transliterate to Devanagari | ❌ wrong direction **and** lossy | Dakshina Hindi single-word WER 50.0–53.1; IndicXlit top-1 60.58% avg. Wrong direction because an English corpus contains no Devanagari. Only consider for cell 7, and even there prefer LLM translation. |
| Embed a blend of both variants | ❌ | With English documents in the index, mixing gives mean Δ −0.04 nDCG@10; embedding-level mixing beats word-level mixing, and pure English beats both. https://arxiv.org/pdf/2606.13537v1 `[Q]` |
| Fine-tune the retriever ("transliterate-train") | ❌ impossible | Recovers ZH-T to 0.1382/0.6807 and RU-T to 0.2633/0.8895 while keeping native performance — but requires fine-tuning the retriever. BYOK across 22 provider-hosted embedding models forecloses this. Only the diagnosis is usable. |

**Exploit the loanword property.** Dakshina documents that English loanwords keep English spelling — the Tamil lexicon has `temple` attested 3× against `tempil` 1×, *"to the extent that the standard English orthography is typically the most commonly attested romanization of the word."* `"refund policy kya hai"` already contains the literal tokens `refund` and `policy`. MiLQ quantifies the rescue: BM25 against English docs, 10.07 (native query) → 36.29 (mixed query). **Your Postgres FTS half is already doing partial work on Case B while the pgvector half does nearly nothing** — which is consistent with the 0.40 cosine floor being a reasonable trigger even with no detector at all, and with keeping the FTS half meaningfully weighted in the RRF fusion for these queries.

Production evidence that this input class is real: HEALTH-PARIKSHA, 749 genuine questions to a deployed Indian health chatbot (666 English, 19 Hindi, 27 Tamil, 14 Telugu, 23 Kannada), lists code-mixing as one of five recurring themes, with examples like *"Agar operation ke baad pain ho raha hai, to kya karna hai?"* and *"Can I eat before the kanna operation?"*. Their routing rule is the one recommended here: *"For code-mixed and Romanized queries, we determined whether they were English or non-English based on the matrix language of the query."* https://arxiv.org/pdf/2410.13671v3

Note the sub-case: a single romanized Indic word inside an otherwise-English query ("the kanna operation", "take Karwat"). A sentence-level detector labels this English; a token-level one catches it. Decide explicitly whether you care — the recommendation here is that you do not, in v1.

---

## 5. Cases C and D — mixed corpus

### 5a. The null hypothesis, treated explicitly

**H0: a good multilingual embedder needs no routing at all.**

**H0 survives for BGE-M3.** Chirkova et al. indexed English Wikipedia, the user-language Wikipedia, their concatenation, and all 13 languages concatenated, then measured RAG answer quality (character 3-gram recall):

| Language | No retrieval | En-wiki only | Native-wiki only | **En + native** | All 13 languages |
|---|---|---|---|---|---|
| Arabic | 26.4 | 45.9 | 36.3 | **49.0** | 48.2 |
| French | 48.4 | 62.6 | 56.3 | **65.0** | 66.2 |
| Korean | 21.5 | 32.2 | 31.5 | **38.4** | 38.1 |
| Russian | 38.1 | 55.0 | 51.0 | **61.0** | 59.4 |

*"BGE-m3 also successfully manages to retrieve from the concatenated multilingual Wikipedia and thus dynamically choose the more appropriate datastore, often reaching performance higher than with any of the two monolingual Wikipedias."* https://arxiv.org/html/2407.01463v1 `[Q]` (MKQA = Natural Questions, real search queries). Note honestly: going from 2 languages to 13 in the index is roughly a wash — it *loses* slightly on Korean, Russian, Japanese and Arabic. The win is over the *monolingual* indexes, not over adding more languages.

**H0 is refuted for multilingual-e5.** SHIFT measures Target-Languages Recall@20 (fraction of gold **non-query-language** docs surfaced) on the 24-language MultiEuP-v2 pool: multilingual-e5-large scores **0.095** while its ordinary Recall@20 is 0.302 — standard metrics hide a ~3× bias. The same index-side de-biasing lifts mE5 by +0.104 average nDCG@20 (0.633 → 0.737; Belebele 0.816 → 0.910, MLQA 0.494 → 0.649, XQuAD 0.855 → 0.944) and lifts **bge-m3 by +0.002** (0.715 → 0.717). https://arxiv.org/abs/2606.18801

**Verdict on H0: "no routing needed" is a property of the embedding model, not of the problem.** The identical intervention is transformative for one encoder and noise for another, and the two encoders show *opposite* directional biases on identical data. With 22 selectable embedders — including `all-MiniLM-L6-v2`, which is tagged `language: en`, 384-dim, trained at sequence length 128 and truncating past 256 word pieces (https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) — **Oreag cannot hard-code one policy.** And no amount of model-card diligence resolves it: every headline multilingual benchmark measures monolingual retrieval or X→English, so nothing published tells you which profile a given embedder has.

Also note the mechanism, which explains why this is expected rather than a bug: contrastive training rewards language clustering, so the objective that makes an encoder good at multi-monolingual retrieval is what makes it bad at mixed-pool ranking. *"[Conventional] contrastive learning to MLIR can exacerbate language clustering."* https://arxiv.org/html/2605.31171v2 `[UNVERIFIED — result tables in this entry were extracted from rendered HTML, not hand-checked; use the diagnosis, not the numbers.]`

### 5b. Diagnosis: Case C is a ranking problem, not a matching problem

The single most important result for Cases C and D. A **language-oracle retriever** restricts the index to the language actually holding the gold document. If the embedder could not match across languages, the oracle would also fail. It does not:

> *"the language-oracle retriever achieves nearly identical performance across all query and document language pairs, suggesting there are essentially no failures related to the query-document language mismatch challenge."*
> *"the gap between the direct and language-oracle retrievers can be substantial in many cross-lingual cases. This indicates that the main source of failure lies in the document-document language mismatch challenge, namely the retriever's ability to rank documents across languages."*
> — https://arxiv.org/html/2507.07543v2

**The Hindi question already matches the English chunks semantically. It loses the ranking comparison to the Hindi chunks.** Case C is therefore not a translation problem, and translation is the wrong tool for it. Fix the pooling.

Corroborating magnitudes:
- **>70% of top-5** comes from English + query language alone, averaged across 13 languages, with BGE-M3 + BGE-reranker. https://arxiv.org/abs/2604.20199
- Parallel (semantically identical) passages land a mean **rank distance of 410.2** apart on XQuAD-R with XLM-R. https://arxiv.org/abs/2408.10536 — a top-20 cannot contain both, so no amount of RRF over two already-monolingual result lists recovers it. The fix must be at candidate generation.
- The mono → cross-lingual → mixed-pool cascade: XLM-R 0.798 → 0.705 → **0.593** mAP on XQuAD-R; LaBSE 0.817 → 0.767 → 0.682. **Case C costs a further ~11 mAP points on top of the cross-lingual penalty, on identical content.** Oreag's mixed-corpus case is the worst of the four, not the mildest.
- LAReQA's framing: Oreag's gate implicitly assumes **weak** alignment ("nearest neighbour across languages is the relevant one"). All four cases are **strong** alignment problems ("all relevant items are closer than all irrelevant items, *regardless of language*; relevant items in different languages are closer than irrelevant items in the same language"). Off-the-shelf encoders do not have that property: 0.85–0.88 average mAP on monolingual retrieval → **0.23** on the same content once the pool is mixed. https://arxiv.org/abs/2004.05484
- The headroom is already in your candidate pool. Oracle selection from the *existing* top-k lifts 3-gram recall from 48.9 to 63.6 average (English 70.1 → 79.3), *"substantial improvements ranging from +12.9 to +20 points."* https://arxiv.org/abs/2604.20199

### 5c. Strategies, measured

| Strategy | Query-time cost | Setup | Measured effect |
|---|---|---|---|
| **Balanced retrieval** (equal k per language slice, then fuse) | 1 extra scan per language (~+10–30 ms). **0 API calls.** *"balanced incurs no additional cost beyond retrieving documents from the index."* | `chunks.lang` column + backfill | Overall *"around 4–6% for BGE-M3 and approximately 20% for M-E5."* Travel cross-lang Hit@20: BGE-M3 86±3 → **93±2**; M-E5 59±4 → **94±2**. Legal BGE-M3 cross-lang 73% → **~85–86%** (Overall 80.5 → 85.7). `[UNVERIFIED — an earlier draft claimed Legal 73% → ~93%; that figure is from the Travel benchmark. The Legal balanced values were read off Figure 1(a), not a table.]` **Crucially: "no statistically significant loss relative to the direct retriever in same-language cases."** Stable across 25%/50%/75% English corpus ratios (89/93/94 for BGE-M3), so it does not need to know the mix. https://arxiv.org/html/2507.07543v2 |
| **Dual-query translate-and-merge** | 1 translation call (~300–800 ms) + 1 extra embedding | none | Statistically indistinguishable from balanced. *"translation requires an expensive and time-consuming call to a translation service."* Merge is by raw score in the paper — **do not copy that**; use rank-only RRF. |
| **Index-side de-biasing (SHIFT)** | **0** | per-(model, language) mean offset vector from parallel pairs (paper uses 533k mMARCO pairs); mutates stored embeddings ⇒ re-index | mE5 +0.104 avg nDCG@20; **bge-m3 +0.002**. TLR@20 0.095 → 0.268 on MultiEuP-v2. https://arxiv.org/abs/2606.18801 |
| **CSLS instead of raw cosine** | ~7% marginal per query after gallery precomputation | one float column per chunk; **no parallel corpus, no per-model calibration** | Closes 63.5% of the mutual-nearest-neighbour reciprocity gap across 5 production APIs. Root cause is hub mass (49.5% dominance share, partial R² 0.302 vs 0.003 for anisotropy). OpenAI `text-embedding-3-large` EN-HI reciprocity 0.200 → 0.300; `text-embedding-3-small` 0.076 → 0.242. https://arxiv.org/abs/2605.26575 `[UNVERIFIED — corpus is 6,518 idioms and proverbs, deliberately non-compositional; absolute magnitudes are an upper bound on the damage. The paper's "Hi-Bn easiest for every model except Mistral" claim is contradicted by its own Table 6.]` `[Q — BPE token lengths 7.1–11.8, the only genuinely query-length item in this literature]` |
| **Per-language sub-search + weighted RRF** (the only published end-to-end deployment) | \|L\| scans + routing | language metadata | +0.68 to +1.00 pp accuracy. `[UNVERIFIED — the weighted-RRF branch was never exercised in the final system; all six languages routed to dedicated shards, gains are confounded with a ~20× corpus expansion, and query language came from an ID prefix (oracle metadata), never from detection.]` https://arxiv.org/html/2607.22841v1 |
| **Over-retrieve then rerank** | cross-encoder over 2–4× candidates | none | ❌ **The reranker is the biased component.** Ranking gains are real (BGE +4.3 P@5 / +8.7 nDCG@5; Qwen3 +8.4 / +15.2) but convert to only **+1.0 / +1.95** downstream 3-gram recall against a 14.7-point oracle gap. A trained reranker recovers ~a tenth of the available headroom. https://arxiv.org/abs/2604.20199 |
| **Multi-query LLM expansion + RRF** | 5 LLM calls + 5 embeddings + 5 scans; **16.6 s measured** | none | ❌ Recall@1 **0.8693 → 0.8693** (zero). Recall@5 0.8512 → 0.8530 (+0.2%). https://arxiv.org/html/2512.12694v1 |
| **Index-side document translation (CrossRAG)** | 0 (if pre-translated) | translate whole corpus | Best in class, but the user's tokens. MultiRAG (pure H0) still beats no-retrieval by +5.4 to +7.1. Low-resource languages gain ~1.8–2× more than high-resource (+6.6% vs +3.6%). https://arxiv.org/abs/2504.03616 |
| **Hard language filter on the query's language** | cheap | — | ❌ **No published evaluation exists.** Given the language-oracle result, filtering to the *query's* language is likely actively harmful for Case A — it filters away exactly the chunks you need. |

### 5d. Oreag's structural advantage: rank-only RRF k=60

The classical objection to per-language sub-search + merge is score incomparability: *"differences in collection statistics result in incompatible scores that require normalization prior to late fusion. Unfortunately, normalizing scores for collections across languages has been shown to be challenging."* https://arxiv.org/html/2209.01335v2

**Oreag already fuses by rank, not score.** Rank-only RRF is immune to this by construction. Balanced retrieval's per-language sub-lists drop straight into the existing fusion stage with no new normalization logic. This is a real advantage that should not be given up.

### 5e. `|L| ≥ 3` is unsolved

The authors are explicit: *"applying such approaches in practical settings with non-uniform language distributions or more than two languages remains an open challenge and warrants further investigation."* Untested extrapolation only: allocate `k_i` proportional to each language's chunk share with a floor (min ~3 chunks per language present), or balance only the top-2 languages by chunk count and let the tail compete globally. **Ship behind a flag, measure, do not claim it works.**

### 5f. The chunk-language column: what it costs and what it unlocks

Per-chunk LID at ingest is a solved problem for native-script text, because accuracy is a monotonic function of input length and a 200–1000 char chunk sits far above the hard regime.

| Detector | single words (~9 chars) | word pairs (~18 chars) | sentences (~111 chars) |
|---|---|---|---|
| PyCLD2 | 34 | 68 | 94 |
| GCLD3 | 48 | 67 | 93 |
| langdetect | 65 | 82 | 98 |
| langid | 48 | 65 | 90 |
| Lingua (low-accuracy) | 64 | 82 | 94 |
| **Lingua (high-accuracy)** | **74** | **89** | **96** |
| Simplemma | 34 | 49 | 73 |

75 languages × 1000 items per cell — https://github.com/pemistahl/lingua-py/tree/main/tables `[Q at 9 and 18 chars — the only published per-detector accuracy-vs-length curve.]` Per-language at sentence length: Hindi 99/95/99/92/93, Tamil 100/99/100/100/100, Bengali 99/99/100/97/100, Marathi 99/98/98/91/95. The same languages at single-word length collapse: Hindi 56/34/44/41/64, English 12/22/23/84/55.

**A 3–10 word query is ~20–60 chars, between the word-pair and sentence rows: expect 70–90% at best `[EXTRAPOLATED — nobody has measured this length].` This is the quantitative reason to run LID on chunks and never on the question.** Elastic, with production telemetry, reaches the same conclusion and declines query-side LID outright: *"search queries tend to be short. Like, really short!"* (citing a ~2.4-term average), recommending implicit context or an explicit user locale instead — https://www.elastic.co/blog/multilingual-search-using-language-identification-in-elasticsearch. That is external validation of the split Oreag already has (script gate on the query, LID on the corpus).

Five caveats that matter more than the headline accuracy:

1. **Clean benchmarks overstate real corpora.** GlotLID falls 93.3 F1 (FLORES) → 71.8 (TweetLID) → 64.6 (SMOL); five-domain averages: GlotLID 77.8, ConLID 77.3, fastText 68.5, OpenLID 68.4, Franc 52.8, CLD3 48.2. https://arxiv.org/html/2509.17768v1 Calibrate to the 70–90 band, not to 0.978.
2. **Code-switched chunks are unsolved, not merely hard.** DIVERS-CS full-match (both languages correctly returned from top-2 softmax) on English-Hindi: ConLID 0.44, OpenLID **0.00**, GlotLID **0.00**, langdetect 0.01. Partial match sits at 48–50 — models reliably find one language and silently drop the other, biased toward English. *"the limitations of softmax-based LID models in handling intra-sentential multilingual inputs."* **Never model a chunk as one language plus a confidence score and assume low confidence flags mixing. It does not.** Store a top-k label vector; treat "second label above a floor" as the mixed signal. MaskLID raises En-Hi exact detection 5/253 → 29/253 for a few extra fastText passes on an already-loaded model — good enough to set a *flag*, not to produce a trustworthy second label.
3. **Romanized Indic in a chunk is the worse problem.** IndicLID: 98.62% native-script vs 80.40% real romanized (95.96% on synthetic — a ~15-point overpromise for anyone evaluating on transliterated data).
4. **Thresholds are per-language.** FineWeb2 uses `max{0.3, min{0.9, Med(X) − σ(X)}}`; *"Arabic or Russian prefer high thresholds (>0.8), while for Swahili a lower threshold around 0.3 performs best"* — https://arxiv.org/abs/2506.20920. mC4 used a flat cld3 0.7: *"we detect each page's primary language using cld3 and remove those with a confidence below 70%"* — https://arxiv.org/abs/2010.11934. Store an explicit `und` when below threshold; never force a label. `[UNVERIFIED — an earlier draft attributed a 0.5 threshold and a zxx_Zxxx class to "OpenLID-v3"; the zxx/und label series belongs to GlotLID v3, and the 0.5 figure traces to CC-100 as a baseline FineWeb2 argues against.]`
5. **Document-level LID is stronger per decision but only valid for monolingual documents** — Baldwin & Lui found *longer* EuroGov documents scoring *worse* because *"longer documents [are] more likely to be 'contaminated' with either data from a second language or extra-linguistic data, such as large tables of numbers or chemical names."* https://aclanthology.org/N10-1027.pdf Best macro-F1 on Wikipedia (67 languages, ~1.5 KB docs) is **0.671** (COS1NN, byte bigrams), rising to 0.729 only with hybrid 1–5-grams and feature selection. `[UNVERIFIED — earlier drafts credited 0.729 to COS1NN bigrams and ~0.87 to a hybrid; 0.869 is COS1NN bigrams' micro-F, not a macro-F.]` **Design: chunk-level label + document-level vote.** If ≥90% of a document's chunks agree, snap the minority chunks to the document label unless their own confidence is high.

**Recommended detector for chunks: GlotLID v3, in the ingest worker only.** 0.978 F1 / 0.0051 FPR on FLORES-200 at threshold 0 (vs CLD3 0.753, lid.176 0.775, OpenLID 0.923, NLLB 0.947); 0.868 on UDHR (CLD3 0.544). Apache-2.0-plus-notices, unlike OpenLID's GPL-3.0. Cost: **1.69 GB resident** — a real number on a Render dyno, and the reason to keep it out of the request path. https://arxiv.org/abs/2310.16248

**Storage.** `chunks.lang` as an ISO-639-3 + ISO-15924 label matching GlotLID's own format (so the column natively holds `und` and `zxx`), plus the confidence score, plus an index on `(project_id, lang)`. Derive `ts_config` from the *chunk's* language instead of the project's. Backfill is one GlotLID pass per chunk — **no re-embedding**. Migration 0039 already built and tested the per-row `regconfig` mechanism; only the value's source changes.

**Gate the whole feature on embedder coverage.** Join `chunks.lang` against a per-embedder language-coverage table maintained alongside the 22-model registry, and derive three states: (1) embedder covers all chunk languages → use `lang` only for FTS config and balanced retrieval; (2) covers some → route uncovered-language chunks to the lexical half and consider translation; (3) covers none of a chunk's language → **warn at ingest, before the user pays to embed a corpus their chosen model cannot read.** An English-only encoder will happily embed a Hindi query and return a confident-looking vector; the 0.40 floor (`backend/app/config.py`, `cross_lingual_similarity_floor`) is the only thing catching that today, and it catches it for the wrong reason. State (3) is a product fix no retrieval cleverness substitutes for.

**Honest negative on prior art:** two arXiv abstract queries (`retrieval-augmented` ∧ `multilingual` ∧ `language identification` → 0 results; `multilingual` ∧ `chunk` ∧ `retrieval` → 14 results, none storing chunk-level language) found **no published RAG system that stores a per-chunk language tag for retrieval routing.** The published per-language-tag routers are search engines (Elasticsearch per-field/per-index; Azure AI Search `LanguageDetectionSkill`) and pre-training pipelines (mC4, FineWeb2). Treat this as "two narrow abstract queries surfaced none," not as a survey result — but note it means no baseline to beat and no prior art to copy: measure your own before/after.

---

## 6. The generation half

Retrieval decides what reaches the context window. It does not decide what language comes back out. That is a separate failure mode with its own measured rates.

### 6a. What language should a Hinglish question be answered in?

**Doing nothing means answering in English, nearly always.** Indi-RomCoM measures a **Register Defection Rate** — the share of responses written in English when the input was romanized code-mixed:

| Model | RDR |
|---|---|
| Qwen2.5-1.5B | 99.8% |
| LLaMA-3.1-8B | 99.7% |
| Qwen3-4B | 98.8% |
| GPT-3.5-Turbo | 54.4% |
| Claude Opus 4.6 | 35.9% |
| Sarvam-30B | 26.1% |
| TamilLLaMA-7B | 19.9% |
| Airavata-7B | 16.5% |

RDR rises monotonically with code-mixing density (GPT-3.5: 48.3 / 53.7 / 61.2 at 25/50/75% CM). *"The only models that genuinely maintain CM register are Indic-trained."* https://arxiv.org/html/2606.30790v1 `[S — inputs are structured instruction prompts, not queries; defection on a terse query is plausibly higher but unmeasured.]`

**The only user-preference evidence: mirror the register.** A CSCW 2020 mixed-method study (N=91 bilingual users, three chatbot policies) found *"multilingual users strongly prefer chatbots that can code-mix"*, that *"self-reported language proficiency is the strongest predictor of user preferences"*, and that of the two mixing policies, reciprocating the user's own mixing is *"a low-risk low-gain policy which is equally acceptable to all users."* https://www.microsoft.com/en-us/research/publication/do-multilingual-users-prefer-chat-bots-that-code-mix-lets-nudge-and-find-out/ Caveat: open-ended chit-chat, 2020, pre-LLM. A factual RAG answer with policy terms and numbers may pull preferences toward the source language.

**Recommendation:** default to **nudge/reciprocate** — a romanized Hinglish question gets a romanized Hinglish answer, **not Devanagari and not forced English**. Because proficiency predicts preference and Oreag cannot observe proficiency, expose a per-project/per-user override: `Auto | Match my question | Always English | Always <corpus language>`.

**Because the romanized detector is the least reliable component in the chain, do not let it hard-switch the answer language.** Use it only to *relax* the constraint (permit code-mixed output, stop penalizing Hindi words) rather than to *force* Hindi. A false positive then costs nothing, and a false negative degrades gracefully to English — which the model was going to do anyway.

### 6b. Enforcing the output language

**An explicit prompt instruction is not sufficient.** With an explicit target-language instruction **and** four in-language ICL exemplars already in the prompt, language consistency still collapses when the retrieved context is in a different language (HotpotQA, LLaMA3-8B):

| Target | Same-language context | English context |
|---|---|---|
| Chinese | 92.0% | **68.4%** |
| Arabic | 95.4% | **85.4%** |
| Russian | 89.5% | **80.2%** |

`[UNVERIFIED — earlier drafts reported AR 99.2→85.4 and RU 99.1→89.5; those "before" values are the no-ICL baselines and double-count the ICL penalty. Use 95.4 and 89.5.]` Drift *"often emerges mid-generation"*, drifted outputs stay semantically faithful, and English is *"the most frequent fallback language"* — for LLaMA3-8B on MuSiQue >90% of drifted output lands in English (Qwen2.5-7B falls as low as 45.0% in one condition). https://arxiv.org/html/2511.09984v1

Baseline wrong-language rates vary enormously by model, which matters for BYOK. Language Confusion Benchmark, monolingual line-level pass rate: Command R+ 99.2, Llama 3.1 70B-I 99.0, GPT-4o 98.9, **Mistral Large 69.9, Llama 2 70B-I 48.3.** Cross-lingual LPR: Command R+ Refresh 95.4, GPT-4o 92.4, Llama 3.1 70B-I 81.4, Llama 2 70B-I 38.4. https://arxiv.org/html/2406.20052v3 `[S — LCB deliberately filters out short completions ("less than 5 words") and applies fastText only to sequences of more than 4 words. None of it is evidence about LID on a query.]`

| Mechanism | Available in BYOK? | Effect |
|---|---|---|
| Prompt instruction alone | ✅ | Insufficient — the 68.4% figure above is *with* an instruction. |
| **Few-shot in-language exemplars** | ✅ | **The strongest prompt-only lever measured:** Command R Base cross-lingual LPR **1.1% → 95.0%** with 5 shots. Costs a few hundred input tokens per request. |
| **Lower temperature** | ✅ free | WPR loss from T=0.3 → T=1.0 is ~10 points overall and ~22 for CJK (96.3 → 86.5 avg; ja 74.5, zh 74.7). `[UNVERIFIED — the paper's own prose beside that table reports 83.5 avg and 72.0/69.5 for ja/zh; cite the table and expect the prose to disagree.]` |
| **Instruction placed LAST, after the evidence** | ✅ free | Drift emerges mid-generation, so the constraint should be the most recent thing in context. |
| **Suppress chain-of-thought in the answer channel for cross-lingual cases** | ✅ free | Language locks must never apply to intermediate reasoning (see below). |
| **Post-hoc language check + one retry** | ✅ | **The only enforcement layer compatible with 12 providers — and completely unmeasured in the literature.** |
| Soft Constrained Decoding | ❌ needs logits | ZH-target LC 68.4 → 90.6 with ROUGE 0.182 → 0.306; AR 85.4 → 96.4. |
| Language Confusion Gate | ❌ needs logits + per-model training | Qwen3-8B Latin-script confusion 12.1% → 2.0%, CJ 4.5% → 0.1%; BLEU 13.2 → 13.4. https://arxiv.org/html/2510.17555v1 |
| ReCoVeR steering vectors / Smoothie-Qwen | ❌ needs hidden states or weight edits | LCB cross-LC: Llama 3.1 91.0 → 97.0, Qwen 2.5 92.3 → 97.0, Gemma 2 81.8 → 96.6 (all ReCoVeR+, the *trainable* variant). `[UNVERIFIED — earlier drafts cited Qwen 98.2, which is from a different benchmark table.]` https://arxiv.org/html/2509.14814v1 |

**The ceiling is ~95–98% LPR, and prompt + few-shot already reaches ~95%.** The entire prize for going model-internal is 2–3 points, which is not worth breaking BYOK for.

**Recommended enforcement stack (build order):**
1. Answer-language instruction placed **last**, after the retrieved evidence.
2. 2–5 tiny in-language exemplars when the project's model shows drift.
3. Cap generation temperature for cross-lingual answers.
4. **Post-hoc check:** run `lingua` on the *answer* and compare to the intended answer language. This is exactly XRAG's validated metric — *"we apply a language detection tool, lingua, to verify whether the response is in the same language as the corresponding input question"* (https://arxiv.org/html/2505.10089v1), with LLM-judge/human agreement κ=0.71. Cite it as precedent rather than inventing a metric.
5. **One retry** with the instruction restated and temperature lowered. Cap at 1; on second failure return the first answer with a language warning rather than looping. Rationale that a retry usually succeeds: the language-consistent token is in the top-3 **99.29%** of the time (it is merely top-1 only 56.74% of the time, which is why greedy decoding fails).
6. Log LC (language consistency) per project as a first-class metric alongside the cosine floor, and instrument retry rate + post-retry success with the existing Langfuse metering.

**CRITICAL asymmetry:** the *check* runs on the **answer** (long, reliable LID) while the register *decision* runs on the **query** (3–10 words, unreliable LID). **Never reuse one detector's confidence for the other job.**

**Honest gap:** no paper measures detect-then-regenerate for output language. Guardrails AI documents the mechanism (`on_fail=REASK` — *"Reask the LLM to generate an output that meets the correctness criteria specified in the validator"*, with a `num_reasks` budget — https://www.guardrailsai.com/docs/concepts/validator_on_fail_actions) but ships no language validator and publishes no effectiveness numbers. Oreag can build this in a day and publish the first per-model retry-rate figures.

### 6c. Do not over-enforce

Hard language locks cost accuracy:
- Forcing monolingual decoding on a bilingual reasoning model *"reduces accuracy by 5.6 percentage points on MATH500."* https://arxiv.org/abs/2507.15849 (Note the scope: this is a Chinese-English reasoning model where mixing was induced by RLVR; a BYOK RAG generator that never went through that pipeline may have no such behaviour to suppress.)
- The Language Confusion Gate suppresses legitimate code-switching by **17–44% relative** (Llama3.1-8B 42.51 → 31.60; Qwen3-8B 46.34 → 25.90; Gemma3-12B 30.94 → 25.57), landing between the human ground-truth rate of 38.36% and Claude Sonnet 4's 23.29%. `[UNVERIFIED — earlier drafts said "30–40%"; the real spread is 17–44%, averaging ~29%.]`

**Hinglish answers *are* code-switching.** Any "one language only" constraint must be applied to the **final answer only, never to intermediate reasoning**, and must be **disabled entirely when the user's register is code-mixed**. Also `[UNVERIFIED]`: a claim circulating in this research that RL methods prevent language-consistency collapses "up to ~27 percentage points" carries no citation and could not be located in any source — drop it.

### 6d. Citations the user cannot read

Case A/C answers cite chunks in a script the reader may not know. Two conclusions:

**Verify, do not merely display.** On XOR-AttriQA, only **31.7%–50.9% of answers are attributable to at least one passage provided to the generator** — i.e. **49.1%–68.3% are not**. `[UNVERIFIED — an earlier draft inverted this and reported non-attributable as 31.7–50.9%, understating the problem by roughly half.]` Of exact-match-*correct* answers, attributable rates run ja 53.1 / bn 67.3 / ru 67.5 / fi 80.4 / te 93.1. Only 0.3%–4.0% of answers (Telugu, Finnish) are attributable to an *English* passage while not attributable to any same-language passage — which is an independent argument that query translation alone is not sufficient. A PaLM-2 attribution detector fine-tuned on **250 examples** reaches 92.3%–96.4% accuracy / 95.0–98.2 ROC-AUC; reranking with it improved top-1 attribution by 55.9% relative. https://arxiv.org/html/2305.14332v2 **At minimum, run an NLI entailment check between the answer sentence and the cited chunk whenever citation language ≠ answer language, and flag on failure.**

**Display: translate the snippet, label it, keep the original one click away.** Two strong precedents, no research literature:
- Google Search: *"Sometimes Google may translate the title link and snippet of a search result for results that aren't in the language of the search query"*; clicking yields *"a page that's been machine translated"*; and *"Users also have an option to view the original search result, and access the entire page in the original language."* Supported languages include Bengali, Gujarati, Hindi, Kannada, Malayalam, Marathi, Tamil, Telugu, Urdu — a useful scope guide. https://developers.google.com/search/docs/appearance/translated-results
- Wikipedia:Verifiability: *"a translation into English should accompany the quote"*; *"translations by Wikipedians are preferred over machine translations"*; *"The original text is usually included with the translated text."* https://en.wikipedia.org/wiki/Wikipedia:Verifiability

Render as: **[translated snippet] + [original chunk] + a "machine-translated" badge.** Never silently substitute the translation for the source in a UI whose whole purpose is verifiability.

### 6e. Generation-side language preference persists after retrieval is fixed

Balanced retrieval guarantees Hindi chunks reach the context window. It does not guarantee the model reads them.

- **Citation nepotism.** Varying only the language of the document that must be cited, holding the rest of the context in English: citation accuracy drops **−23.9% average / −37.6% worst (Swahili)** and **−18.0% / −32.8% (Bengali)**, with Spanish −8.08% and French −8.82%. *"Models preferentially cite English sources when queries are in English."* With one *relevant* target-language doc and one *irrelevant* English doc, *"accuracies consistently drop below the baseline, indicating that irrelevant English content more easily mislead the model."* The gap is **largest when the cited document sits mid-context**. https://arxiv.org/html/2509.13930v3
- **English-document dominance.** A k-voting experiment: *"When k reaches 3, the scores for English answers and voting answers are comparable for Qwen2-7B-Instruct. We also see the same trend with GPT-3.5-Turbo when k is 4."* — i.e. roughly 3–4 non-English documents are needed to offset one English document. https://arxiv.org/abs/2410.21970 `[UNVERIFIED — the "3–4 documents needed to offset one English document" phrasing is a derived reading of a 2-model voting experiment, not a quotation. The paper contains no such sentence.]`

**Actions (all free):** enforce citations by chunk ID and validate that every cited ID was actually retrieved; do not place English chunks first; do not bury Indic chunks mid-context — interleave or order by language balance; expect over-citation of English sources and consider a light prompt instruction.

**Counterweight — mixed evidence is not inherently harmful.** BordIRLines (49 languages) found *"incorporating perspectives from diverse languages can in fact improve robustness"*, that *"retrieving multilingual documents best improves response consistency"*, and that it *"decreases geopolitical bias over RAG with purely in-language documents."* https://arxiv.org/abs/2410.01171 XRAG independently finds *"LLMs rarely have issues with Response Language Correctness in the multilingual retrieval setting"* — language correctness is **worse** when all retrieved docs are in one foreign language (Case A) than when the context is mixed (Case C). **So: do not partition mixed projects by language, and do not force a single-language context.**

### 6f. Case A generation is the easy direction

MTM-Bench disentangles instruction / content / response language across 27 triplets, 20 models, 2,430 instances each. Response language dominates (JointSuccess Δ 0.113) over content language (Δ 0.029) and instruction language (Δ 0.018).

| Response language | SemanticCorrect | LangCorrect | ContaminationRatio | JointSuccess |
|---|---|---|---|---|
| English | 0.942 | **0.965** | **0.023** | 0.819 |
| Spanish | 0.885 | 0.890 | 0.039 | 0.711 |
| Chinese | 0.851 | 0.860 | 0.067 | 0.706 |

Configuration classes: all-matched 0.829; **content-only mismatch (Oreag's Case A shape — English question, English answer, foreign evidence) 0.746**; instruction-only 0.795; response-only **0.694** (worse than full mismatch at 0.705). https://arxiv.org/html/2605.27649v1

**So: budget ~8 points of answer-quality loss for Case A from reading foreign evidence, not a language failure.** Corollary for the leakage policy: **do not penalize retained proper nouns, IDs and numerals** — the benchmark explicitly allowlists them and the observed "contamination" is mostly this. Reserve real enforcement effort for the non-English-answer directions. XRAG corroborates the accuracy cost: English → non-English average accuracy GPT-4o 62.4% → 55.5%, Command-R+ 45.7% → 37.3%, Mistral-large 43.3% → 31.4%.

**Case D (Hinglish query over a mixed corpus) is register defection + drift + citation nepotism stacked, and is measured jointly nowhere.** Expect the English attractor to win twice.

---

## 7. CONSOLIDATED RECOMMENDATION

Ordered by (cases closed) ÷ (work). Each step has a kill criterion — a condition under which you stop and do not proceed.

### Step 0 — Build the mirror-image eval. *(half a day. Do this first; everything else is unfalsifiable without it.)*

Reuse the existing 40-language fixtures with query and corpus **swapped**, plus a mixed-corpus set where gold answers are deliberately placed in the *non-query* language.

Three fixtures:
- **A**: English questions → Hindi/Tamil/Arabic-only corpora.
- **C**: Hindi and English questions → one index containing both halves, gold in the other language.
- **B**: Hinglish/Tanglish questions → English corpus, and → Hindi corpus.

Two metrics beyond rank-1:
- **TLR@20** (Target-Languages Recall) — of the gold documents in languages *other* than the query's, how many surfaced. Oreag's 80/80-at-rank-1 is exactly the kind of aggregate that hides Case C; mE5 scores Recall@20 0.302 while TLR@20 is 0.095 on the same data (https://arxiv.org/abs/2606.18801).
- **Language mix of the top-k** — alert when the fraction sharing the query's language approaches 1.0 on a mixed corpus.

**This is genuinely novel measurement.** The literature has no EN→Indic dense-retrieval number, per direction, at query length. Nobody has published it.

**Kill criterion:** if Fixture A shows English→Indic recall within noise of Indic→Indic **for the project's actual embedder**, and Fixture C shows the top-k already mixed, **stop. Ship nothing.** H0 held for BGE-M3 in the published record and it may hold here.

### Step 1 — Replace the gate predicate. *(one function. Closes the query-side half of A, B and D.)*

```python
def should_consider(project, question) -> bool:
    q = llm_language_judgement(question)   # {language, script, matrix_language} — folded
                                            # into the call you already make
    return q.language not in corpus_languages(project)
```

Delete `if not asked: return False`. Delete `not (asked & corpus_scripts)`. Fire on **set non-membership of the detected query language in the corpus language set**, symmetric in both directions. Remediation is unchanged: translate the question into the corpus language and embed the translation; the original still drives generation.

- Detector: matrix-language judgement from the flagship LLM already in the loop (gpt-4o 98.1 F1 MLI zero-shot). Never a mini/flash model (gemini-1.5-Flash: 33.7).
- Optional: high-confidence `eng_Latn` from fastText as a negative pre-filter to skip the judgement.
- Keep the 0.40 cosine floor as the *trigger* for remediation on the single-language corpus path. Do **not** rely on it for mixed corpora — the same-language distractors that win clear it easily.

**Kill criterion:** if in-house measurement puts matrix-language accuracy on real 3–10 word queries below ~85%, or if false positives on plain English queries exceed ~2%, revert to the script gate for non-Latin and ship **only** the balanced retrieval of Step 2 (which needs no query-side detection at all).

### Step 2 — `chunks.lang` + balanced retrieval, always on for `|L| ≥ 2`. *(the highest-value item. Closes C and the corpus-side half of D.)*

1. Add `chunks.lang` (GlotLID-format ISO-639-3 + ISO-15924, holding `und`/`zxx`) + confidence + index on `(project_id, lang)`. Detect with GlotLID v3 **in the ingest worker only** (1.69 GB resident; never in the request path). Backfill = one pass per chunk, **no re-embedding**.
2. Derive `ts_config` from the chunk's language instead of the project's. Issue one FTS scan per language present (constant regconfig per scan preserves the Bitmap Index Scan).
3. Retrieve top-k from each language slice independently; feed all sub-lists into the **existing rank-only RRF k=60**. No new normalization logic — this is the one place Oreag's architecture is already ahead of the literature.
4. **Ungated.** The licence to run it unconditionally is the measured result that both mitigations show *"no statistically significant loss relative to the direct retriever in same-language cases"* — a strategy with no measured downside cannot mis-fire, so it needs no gate and you cannot be wrong about firing it. It is also stable across 25/50/75% corpus ratios, so it does not need to know the mix.

Expected: overall +4–6% (BGE-M3) to ~+20% (mE5); cross-lingual Travel 86→93 (BGE-M3) and 59→94 (mE5). Cost: one extra scan per language, **zero API calls**.

For `|L| ≥ 3`: allocate `k_i` proportional to chunk share with a floor of ~3 per language, **behind a flag** — the published work explicitly stops at 2 languages.

**Kill criterion:** if Step 0's Fixture C shows the top-k already language-balanced for the project's embedder (the BGE-M3 profile), skip balanced retrieval for that project — but **still ship the `lang` column**, because Step 3 and the FTS fix both require it and it costs one pass at ingest.

### Step 3 — Fix the FTS half for mixed projects. *(a config change. Closes a bug nobody installed deliberately.)*

Today a mixed English+Hindi corpus is stemmed and stopword-filtered under `english` for both halves. Two options, in order of preference:
1. **Per-chunk `ts_config` from `chunks.lang`** (Step 2 already delivers the value). Real stemmers exist for Hindi, Tamil and Nepali; **not for Bengali, Telugu or Marathi** — be honest in the UI about which languages this helps.
2. For languages with no Snowball stemmer, or as a simpler v1: index under **`simple`** for `|L| ≥ 2` projects — the Postgres analogue of Multi-EuP's whitespace-tokenizer finding, which *"reduces language bias"* at similar overall quality against a 62.79% vs 4.80% MRR@100 spread.

Do **not** weight FTS heavily for cross-lingual matching — sparse retrieval structurally cannot do it (BGE-M3 MKQA sparse 45.3 vs dense 75.1). Rank-only RRF already caps the blast radius.

**Kill criterion:** if A/B on Fixture C shows no change from `english` → per-chunk config, revert. Two of Oreag's own measured configs already showed no difference against `english` on Bengali and Polish, so this is a real possibility for non-stemmed languages.

### Step 4 — Generation-side hygiene. *(free. Applies to all four cases.)*

1. Answer-language instruction placed **last**, after the evidence.
2. Cap temperature for cross-lingual answers.
3. Do not place English chunks first; interleave language slices in the assembled context (mid-position amplifies English preference).
4. Enforce citations by chunk ID; validate every cited ID was actually retrieved.
5. **Nudge policy** for Case B: reply in the register the user wrote in. Expose an override (`Auto | Match my question | Always English | Always <corpus language>`).
6. **Post-hoc `lingua` check on the answer + at most one retry**, restating the instruction and lowering temperature. Log LC per project.
7. Never apply a language lock to intermediate reasoning, and disable it entirely for code-mixed register.

**Kill criterion:** if the measured retry rate for a project's generation model is under ~2%, disable the retry for that model and keep the check as a logged metric only.

### Step 5 — TEST, do not adopt yet: CSLS scoring. *(the highest-ceiling experiment.)*

Replace raw cosine with `2·cos(q,d) − r_k(q) − r_k(d)` before RRF, where `r_k(d)` is a chunk's mean similarity to a sample of queries, stored as one float column alongside the pgvector embedding.

Why it is worth an experiment: it is training-free, **model-agnostic across all 22 embedders**, needs **no parallel corpus and no per-(model, language) calibration** (unlike SHIFT), attacks the measured root cause (hub mass, 49.5% dominance share, partial R² 0.302 vs 0.003 for anisotropy) rather than a symptom, and **needs no language detection at all** — so it improves A, B, C and D simultaneously with no gate. Oreag's likely defaults are tested directly: `text-embedding-3-large` EN-HI reciprocity 0.200 → 0.300, `text-embedding-3-small` 0.076 → 0.242.

**Kill criterion:** the source is `[UNVERIFIED]` (single paper, idiom/proverb corpus, one interpretive claim contradicted by its own table). **Validate on a held-out monolingual set first.** If CSLS degrades the monolingual path at all, drop it — 95%+ of traffic is monolingual and Step 2 already delivers most of the available gain at zero risk.

### Explicitly do NOT build

| Not this | Why |
|---|---|
| IndicLID / GlotLID as the primary Hinglish detector | Romanized Hindi F1 63.06 (recall 53.32); GlotLID 17/29 on real romanized Hindi and 5/253 on code-switched. 1.4 GB / 1.69 GB for a worse answer than the LLM already gives. |
| Transliteration of the query to Devanagari | Wrong direction for an English corpus; 50–53% word error, 60.58% top-1 accuracy. |
| Multi-query LLM expansion + RRF | Recall@1 +0.0000, Recall@5 +0.2%, **16.6 seconds**. This is the pattern most teams reach for first. |
| A reranker to fix language balance | The reranker is the biased component; a trained fix recovers ~1/10 of the oracle headroom. |
| Hard filter on the query's detected language | No published evaluation; the language-oracle result implies it would filter away exactly the chunks Case A needs. |
| SHIFT index-side offsets (for now) | Needs a per-(model, language) offset estimated from parallel data across 22 models, and mutating stored embeddings means re-indexing on the user's key. Balanced retrieval gets a comparable effect with no calibration. Rank behind CSLS. |
| Decoding-level language constraints | Requires logit access; Anthropic exposes none and OpenAI's `logit_bias` is token-id based and cannot express "no Devanagari". |
| Any fine-tuning of the retriever | BYOK across 22 provider-hosted embedding models forecloses it. Every "transliterate-train" / "hybrid-batch" / "MIMO" remedy in this literature is closed to Oreag; only their diagnoses are usable. |

---

## Appendix — claims that did not survive verification

Do not propagate these. Each was found circulating in the research inputs for this document.

| Claim | Status |
|---|---|
| "CLD3 0.187 ms/sample (5,356/s); fastText 0.166 ms/sample (6,019/s); UniLID 0.307 ms/s at 1,940 labels" | **Fabricated.** No cross-system latency table exists in the cited paper; the string "ms/sample" never occurs. Nearest real number: CLD3 4,861 sentences/s (IndicLID Table 3). |
| "On formal UDHR text fastText is 0.868" | **Wrong attribution.** 0.868 is UniLID's UDHR macro-F1; fastText is 0.849. |
| "multilingual-e5-large MLQA LPR 99.92%" | **Wrong.** 96.15%. The XQuAD figure was duplicated into the MLQA slot. |
| bge-m3 per-query-language LPR (German 56.05 / Spanish 60.67 / Thai 97.98 / Romanian 97.23) | **Unsupported.** bge-m3 does not appear in that paper's per-language table; the values could not be located anywhere in it. |
| "HI-BN reciprocity exceeds every EN-X pair for 4 of 5 models" | **False on the paper's own table.** True for Gemini and Qwen only; below EN-AR for both OpenAI models, ties for Mistral. The paper's prose makes the same overclaim. |
| BGE-M3 MKQA Recall@100 for Hindi 63.3 / Telugu 88.1 / Bengali 81.5 | **Cross-table contamination.** MKQA contains no Hindi, Telugu or Bengali. Those are MIRACL hybrid nDCG@10 values. Arabic MKQA Dense is 71.1, not 71.5. |
| "PostgreSQL: a single column cannot hold data processed by different language configurations; you need separate tsvector columns per language" | **Fabricated quote; the docs describe the opposite as supported** (per-row `regconfig` in an expression index / generated column). |
| "Balanced retrieval lifted Legal/BGE-M3 cross-lingual Hit@20 from 73% to ~93%" | **Wrong benchmark.** 93% is Travel. Legal balanced is ~85–86%; Overall 80.5 → 85.7, consistent with the paper's own "4–6%" claim. |
| "ColBERT-X(MTT-M) 0.453 MAP at 0.05 s/doc vs 0.375 at 0.32 s/doc" | **Inverted.** Both 0.375 and 0.453 belong to the *translation* system at 0.32 s/doc; the cheap native-language system scores 0.451 / 0.359 — 2% worse, not better. |
| "Language-routed RAG: only Greek qualified for the weighted-RRF fusion tier" | **Backwards.** All six languages routed to dedicated shards; the fusion branch was never exercised. Gains are confounded with a ~20× corpus expansion, and query language came from an ID prefix, not detection. |
| "MiLQ low-resource BM25 8.56 → 48.10 with NMT" | **Spliced cells.** 8.56 is high-resource CLIR; 48.10 is low-resource MQIR. Correct pairs: LR CLIR 12.35 → 41.07; HR CLIR 8.56 → 46.01. |
| "Approximately 3–4 matching documents needed to offset one English document" | **Not a quotation.** A defensible derivation from a 2-model k-voting experiment; the phrase appears nowhere in the source. |
| "Language drift: Arabic 99.2% → 85.4%, Russian 99.1% → 89.5%" | **Double-counts the ICL penalty.** Correct: AR 95.4 → 85.4, RU 89.5 → 80.2. |
| "XOR-AttriQA: 31.7–50.9% of answers are NOT attributable" | **Inverted.** 31.7–50.9% *are* attributable; 49.1–68.3% are not. |
| "Language Confusion Gate suppresses 30–40% of legitimate code-switching" | **Wrong range.** 17–44% relative, averaging ~29%. |
| "ReCoVeR lifts Qwen 2.5 to 98.2 LPR" | **Wrong table.** 97.0 on LCB cross-lingual; 98.2 is the MultiQ benchmark. |
| "RL work prevents language-consistency collapses of up to ~27 percentage points" | **Unsourced.** Could not be located in any cited paper. |
| "Snowball ships stemmers for 26 languages" | **Wrong count.** 38 algorithms over ~35 languages; this repo maps 28 regconfigs, 17 of them measured. |
| "Baldwin & Lui: COS1NN bigrams 0.729, hybrid ~0.87 on Wikipedia" | **Swapped.** Best macro-F1 is 0.671 (COS1NN, bigrams); 0.729 is SKEW1NN with hybrid n-grams; 0.869 is a micro-F, not a macro-F. |
| "Lui/Lau/Baldwin 2014: 0.912 macro-F on identifying the set of languages present" | **Wrong table.** 0.912 is binary English-inclusion detection on 149 documents. The real language-set numbers are FM .957 (WikipediaMulti) and .748 (ALTW2010). |
| "OpenLID-v3 recommends softmax thresholding at 0.5 and adds a zxx_Zxxx class" | **Conflation.** There is no public OpenLID-v3 model; the zxx/und label series belongs to GlotLID v3, and the 0.5 threshold traces to CC-100 as a baseline. |
| "The code-switching paper shows X→EN consistently underperforms EN→X" | **No such data.** That paper's cross-lingual table has no X→EN column at all (EN-DE, EN-IT, EN-AR, EN-RU, DE-IT, DE-NL, DE-RU, AR-IT, AR-RU). |
| "MuRIL was chosen over IndicBERT-v2 on coverage, not accuracy" | **Misattribution.** IndicLID selected IndicBERT *"due to its superior coverage and performance."* |
| Tanglish offensive-language weighted score 0.61 → 0.67 with MuRIL | **Unsourced.** Could not be located. |
