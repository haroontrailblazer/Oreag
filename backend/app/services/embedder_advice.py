"""Which embedding model can actually read the documents a user uploaded.

THE MEASURED PROBLEM. This product's creation default is
`openai/text-embedding-3-small`, hardcoded in `schemas.ProjectCreate`. On
IndicCrosslingualSTS its 12-language mean is 0.041, and several pairs are
NEGATIVE - en-ta -0.037, en-as -0.095, en-or -0.123. A negative correlation is
not a weak signal, it is an anti-signal: the model places a Tamil sentence
FURTHER from its English translation than from an unrelated one.

Ranked on the case this product is actually asked to do - an English query
against a non-English corpus - Belebele nDCG@10 x100, independent MTEB runs:

    gemini-embedding-001            94.4
    cohere embed-multilingual-v3.0  87.9
    multilingual-e5-large-instruct  87.5
    voyage-3-large                  85.3
    jina-embeddings-v3              78.9
    text-embedding-3-large          78.2
    ------------------------------------  usable / not usable
    text-embedding-3-small          62.9   <- the current default
    ------------------------------------  measured failure
    mxbai-embed-large               36.9
    bge-large-en-v1.5               36.7
    nomic-embed-text-v1.5           30.5
    all-MiniLM-L6-v2                26.2

WHY THE BOTTOM FOUR FAIL, verified from the tokenizer rather than the model
card: all four share a 30,522-token bert-uncased vocabulary containing 70
Devanagari and 36 Tamil tokens, every one a bare isolated letter. Hindi is not
embedded badly, it is shredded to characters and [UNK] before embedding
starts. A user switching ollama -> fireworks -> lmstudio to fix bad Hindi
retrieval is moving between three names for the same weights.

WHY THIS IS ADVICE AND NOT ENFORCEMENT. The product is BYOK: the user brings
the key and picks the model, and that stays their decision. What this module
does is pick a better DEFAULT at creation, and say plainly when a chosen model
is measured not to work for the corpus that was actually uploaded. Every
failure here is silent otherwise - all four bottom models return a well-formed
unit vector with plausible cosines and no error, and Postgres FTS keeps doing
real work on the other leg of the hybrid, so RRF returns a half-plausible list
rather than an obviously broken one.

"unknown" IS NOT "fine". Three catalog models have no published cross-lingual
number from any source - `mistral-embed`, `voyage-3.5`, `voyage-3.5-lite`.
Absence of evidence is reported as absence of evidence and warns like a known
failure, because a user cannot act on silence.

Numbers and citations: research/cross-lingual-rag/10-model-recommendations.md
"""

from __future__ import annotations

from dataclasses import dataclass

# Tier per (provider, model), keyed exactly as `registry.CATALOG["embedding"]`
# spells them. Every catalog entry appears; `tests/test_embedder_advice.py`
# fails if one is added to the registry without a tier, because a model missing
# from this table would be recommended by omission.
#
#   strong-multilingual  measured to hold up on a non-Latin corpus
#   usable-multilingual  works, but with a documented hole - read the note
#   english-mostly       measured failure outside Latin script
#   unknown              NO published cross-lingual number exists anywhere
_TIERS: dict[tuple[str, str], str] = {
    # Belebele engQ 94.4, best in catalog. IndicCrosslingualSTS en-hi 0.754,
    # en-ta 0.705. Still fails en-ur 0.242 and en-or 0.087 - "multilingual" is
    # not one axis, and this table cannot promise per-language success.
    ("gemini", "gemini-embedding-001"): "strong-multilingual",
    # Belebele engQ 87.9. IndicSTS 12-lang mean 0.467, 3.7x text-embedding-3-large.
    ("cohere", "embed-multilingual-v3.0"): "strong-multilingual",
    # MTEB(Indic) rank 1 of 12 at 70.2. Note the caller must send e5's required
    # "query: " / "passage: " prefixes for these numbers to hold.
    ("together", "intfloat/multilingual-e5-large-instruct"): "strong-multilingual",
    # XTREME-UP MRR@10 39.2 Indic-query -> English-passage; hi 54.3, ta 36.0.
    ("voyage", "voyage-3-large"): "strong-multilingual",
    # Belebele engQ 78.9, but XTREME-UP 8.5 and Tamil is absent from Jina's own
    # best-30 language list. Fine for hi/bn/ur, not for Dravidian languages.
    ("jina", "jina-embeddings-v3"): "usable-multilingual",
    # No Belebele/MLQA/IndicSTS run exists (MTEB results repo enumerated and
    # probed per-file: 404 on every cross-lingual file for this model). Its
    # MIRACL monolingual Indic scores sit BELOW its own predecessor, so it is
    # not promoted to strong on vendor claims alone.
    ("cohere", "embed-v4.0"): "usable-multilingual",
    # Belebele engQ 62.9 - below its own monolingual 0.5896, i.e. it does worse
    # across a language boundary than within one. IndicSTS mean 0.041.
    ("openai", "text-embedding-3-small"): "english-mostly",
    ("azure", "text-embedding-3-small"): "english-mostly",
    # Belebele engQ 78.2 and genuinely fine on European pairs (STS17 es-en
    # 87.6), which is exactly why it reads as safe. IndicSTS en-ta 0.0056,
    # XTREME-UP ta 6.0 against gemini's 68.6.
    ("openai", "text-embedding-3-large"): "english-mostly",
    ("azure", "text-embedding-3-large"): "english-mostly",
    # No Hindi or Indic number exists from any source, vendor or independent,
    # and it cannot be dimension-reduced or upgraded in place.
    ("azure", "text-embedding-ada-002"): "english-mostly",
    # Retired by Google. Every multilingual benchmark Google published for this
    # name substituted a different model, so no honest number exists.
    ("gemini", "text-embedding-004"): "english-mostly",
    # Card language column: "English". BAAI ships bge-m3, genuinely
    # multilingual, five characters away in a dropdown.
    ("together", "BAAI/bge-large-en-v1.5"): "english-mostly",
    # The shared 30,522 / 70 / 36 tokenizer, under four provider names.
    ("fireworks", "nomic-ai/nomic-embed-text-v1.5"): "english-mostly",
    ("ollama", "nomic-embed-text"): "english-mostly",
    ("lmstudio", "text-embedding-nomic-embed-text-v1.5"): "english-mostly",
    # Vendor's own words: "our flagship ENGLISH embedding model". 1024 dims puts
    # it visually beside voyage-3.5 and embed-multilingual-v3.0 in a picker -
    # same width, opposite language coverage.
    ("ollama", "mxbai-embed-large"): "english-mostly",
    # MTEB(Indic) rank 12 of 12; cross-lingual STS -6.3, IndicSTS en-ta -0.210.
    ("lmstudio", "text-embedding-all-minilm-l6-v2"): "english-mostly",
    ("sentence_transformers", "all-MiniLM-L6-v2"): "english-mostly",
    # Explicitly unknown: listed so the completeness test passes, and so the
    # distinction between "we checked and found nothing" and "we forgot" is
    # recorded in the table rather than inferred from its absence.
    ("mistral", "mistral-embed"): "unknown",
    ("voyage", "voyage-3.5"): "unknown",
    ("voyage", "voyage-3.5-lite"): "unknown",
}

UNKNOWN = "unknown"

# What a new project defaults to when its documents are not in English. Chosen
# on the Belebele ranking above, at 1536 rather than the native 3072 because
# `retrieval.ANN_DIMENSIONS` has no 3072 entry - pgvector cannot HNSW-index
# above 2000 dimensions for `vector`, so a 3072 project exact-scans every chunk
# on every query. 1536 buys the index; gemini's Matryoshka sizes below 3072 come
# back UN-normalized, which `providers/gemini_provider.py` already handles.
_MULTILINGUAL_DEFAULT = ("gemini", "gemini-embedding-001", 1536)

# What an English project defaults to: exactly what it defaults to today.
# english-mostly is the CORRECT tier for an English corpus, and changing this
# would be an unrelated regression for the majority of projects.
_ENGLISH_DEFAULT = ("openai", "text-embedding-3-small", 1536)

# Matched case-insensitively against `projects.document_language`, which stores
# a display name rather than a locale code. Only English is listed: every other
# language - named or not - is better served by a multilingual model, and an
# unrecognised name falls back to English exactly as text_search.py does, so a
# hand-edited value or a newer client can never break project creation.
_ENGLISH_NAMES = frozenset({"english", "en", "en-us", "en-gb"})


@dataclass(frozen=True, slots=True)
class Recommendation:
    provider: str
    model: str
    dimensions: int


def tier_for(provider: str, model: str) -> str:
    """How well this model is measured to work across a language boundary.

    Returns UNKNOWN for anything absent from the table, so a model added to the
    registry ahead of this file degrades to "no evidence" - which warns - rather
    than to "fine", which would not.
    """
    return _TIERS.get((provider or "", model or ""), UNKNOWN)


def is_explicitly_unknown(provider: str, model: str) -> bool:
    """Was this model CHECKED and found to have no published number?

    The difference matters only to the completeness test: it separates the three
    models with a deliberate "unknown" entry from a model nobody has tiered yet.
    """
    return _TIERS.get((provider or "", model or "")) == UNKNOWN


def recommend(document_language: str | None) -> Recommendation:
    """The embedding model a new project should default to.

    English - and any name this build does not recognise - keeps the incumbent
    default, so nothing about today's behaviour changes for the common case.
    Everything else gets a model measured to survive a language boundary.
    """
    name = (document_language or "").strip().lower()
    if not name or name in _ENGLISH_NAMES:
        provider, model, dims = _ENGLISH_DEFAULT
    else:
        provider, model, dims = _MULTILINGUAL_DEFAULT
    return Recommendation(provider=provider, model=model, dimensions=dims)


def is_risky(provider: str, model: str, corpus_scripts) -> bool:
    """Should this project be warned that its model cannot read its corpus?

    `corpus_scripts` is what `cross_lingual.scripts()` returns for the corpus:
    the set of NON-LATIN writing systems present, empty for a Latin-only corpus.
    An english-mostly model on a Latin corpus is the right choice and must not
    warn; the same model on a Devanagari corpus is the measured failure this
    module exists for.

    "unknown" warns alongside "english-mostly" on purpose. A user cannot act on
    silence, and three catalog models have no cross-lingual number at all.
    """
    if not corpus_scripts:
        return False
    return tier_for(provider, model) in {"english-mostly", UNKNOWN}
