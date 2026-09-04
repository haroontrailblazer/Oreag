"""Ask in one language, search a corpus written in another.

MEASURED PROBLEM. Against this product's own default embedder
(`openai/text-embedding-3-large`), a question asked in a script the corpus is
not written in does not reliably reach the passage that answers it. Cosine of
the question against the correct English passage, versus its best competitor:

    French / Spanish / Japanese      0.54 - 0.75    margin +0.14   fine
    Russian / Arabic / Chinese       0.42 - 0.58    margin +0.09   fine
    Hindi                            0.38           margin +0.05   works
    Bengali / Thai                   0.14 - 0.28    margin +0.03   coin flip
    Tamil / Lao / Khmer / Burmese   -0.00 - 0.11    margin NEGATIVE broken

Burmese scores 0.00 against the passage that answers it while an English
control scores 0.75 - the embedder barely separates Burmese from noise. That
is a property of the embedding model, not of retrieval, and no amount of
ranking work downstream recovers a query vector that points nowhere.

The lexical half cannot rescue it either: an English `content_tsv` has no
Khmer lexemes, so it returned ZERO rows for all 28 non-English questions
measured. Cross-lingual search is carried entirely by the embedder.

WHAT THIS DOES. When the question is written in a script the corpus does not
use, embed a TRANSLATION of the question instead of the question itself. The
original question is untouched everywhere else - it is still what the answer
is generated from, so the reply still comes back in the user's own language.
Measured on the same corpus: five queries moved to rank 1, twenty-five were
unchanged, and NOTHING regressed.

TWO GATES, NOT ONE. The script check decides whether translating COULD help;
the similarity of the search that already ran decides whether it is WORTH it.
Both must open. Measured over 80 cross-lingual queries across 40 languages:

    never translate                    67/80 at first place,  0 model calls
    script gate alone                  79/80,                52 model calls
    script gate AND weak similarity    80/80,                36 model calls

The case the second gate fixes is the argument for it. A Ukrainian question
ranked the right passage FIRST as asked and SECOND once translated, because
"vidpovidalnist" - liability - came back as "responsibility", which pulls
toward a different passage. The embedder understood the Ukrainian word better
than the translation preserved it. Where an embedder already works, replacing
the user's own words can only lose nuance, so the weak-similarity check stops
doing it - and cuts a third of the model calls on the way.

WHY THE SCRIPT GATE, AND NOT ALWAYS TRANSLATING. A Hindi corpus asked a Hindi
question already works - that is the same-language path, and translating the
query to English there would embed English against Devanagari and break it.
Fusing both lists instead of choosing does not fix that: RRF gives a wrong
chunk ranked 1st by the translated vector and 2nd by the original
(1/61 + 1/62) more than a right chunk ranked 1st and 6th (1/61 + 1/66). So
the gate is a real gate, and it fires only when the question's script is
ABSENT from the corpus - the exact case measured above, and a no-op for every
project whose users write in the language their documents are written in.

KNOWN LIMIT, stated rather than hidden: a corpus mixing scripts (English and
Hindi files in one project) satisfies the gate for both, so a Hindi question
there is left alone and reaches only the Hindi half. That is today's
behaviour preserved, not a new failure - fixing it needs per-language sub-
searches, which is a larger change than this one.
"""

from __future__ import annotations

import logging
import re
import threading

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Project

logger = logging.getLogger(__name__)


# Every non-Latin writing system this product can be asked in, as an explicit
# range table rather than `unicodedata` lookups - one regex pass per script
# beats a per-character property lookup over a whole document.
#
# COMPLETENESS IS LOAD-BEARING HERE in a way it is not for a mere heuristic: a
# script missing from this table reads as "Latin only", the gate never fires,
# and the languages that need this most are the ones that silently miss out.
# Khmer, Lao and Myanmar are in the table for exactly that reason - they were
# the worst three in the measurement above.
_SCRIPTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("devanagari", re.compile(r"[ऀ-ॿ꣠-ꣿ]")),
    ("bengali",    re.compile(r"[ঀ-৿]")),
    ("gurmukhi",   re.compile(r"[਀-੿]")),
    ("gujarati",   re.compile(r"[઀-૿]")),
    ("oriya",      re.compile(r"[଀-୿]")),
    ("tamil",      re.compile(r"[஀-௿]")),
    ("telugu",     re.compile(r"[ఀ-౿]")),
    ("kannada",    re.compile(r"[ಀ-೿]")),
    ("malayalam",  re.compile(r"[ഀ-ൿ]")),
    ("sinhala",    re.compile(r"[඀-෿]")),
    ("thai",       re.compile(r"[฀-๿]")),
    ("lao",        re.compile(r"[຀-໿]")),
    ("tibetan",    re.compile(r"[ༀ-࿿]")),
    ("myanmar",    re.compile(r"[က-႟ꩠ-ꩿ]")),
    ("khmer",      re.compile(r"[ក-៿᧠-᧿]")),
    ("georgian",   re.compile(r"[Ⴀ-ჿᲐ-Ჿ]")),
    ("ethiopic",   re.compile(r"[ሀ-፿]")),
    ("armenian",   re.compile(r"[԰-֏]")),
    ("hebrew",     re.compile(r"[֐-׿]")),
    ("arabic",     re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿ]")),
    ("cyrillic",   re.compile(r"[Ѐ-ӿԀ-ԯ]")),
    ("greek",      re.compile(r"[Ͱ-Ͽἀ-῿]")),
    ("hangul",     re.compile(r"[가-힯ᄀ-ᇿ㄰-㆏]")),
    # Han and kana together: Japanese mixes them in one sentence, and telling
    # Chinese from Japanese is not something this gate needs to do.
    ("cjk",        re.compile(r"[一-鿿㐀-䶿぀-ヿ]")),
)


def scripts(value: str) -> frozenset[str]:
    """Which non-Latin writing systems appear in this text.

    Latin has no entry: an English or French string yields the empty set, and
    that is the intended encoding of "written in the default script".
    """
    if not value:
        return frozenset()
    return frozenset(name for name, pattern in _SCRIPTS if pattern.search(value))


# Chunk text is sampled to decide what the corpus is written in. TABLESAMPLE
# is deliberately NOT used: it samples PAGES of a table shared by every
# project, so a small project can sample nothing at all. A plain LIMIT over
# the project's own rows always returns rows if the project has any.
_CORPUS_SAMPLE_SQL = text(
    """
    SELECT c.content
    FROM chunks c
    WHERE c.project_id = :project_id
    ORDER BY c.id
    LIMIT :sample
    """
)

# (project_id, content_version) -> (scripts, sample text). Keyed on the content
# version so re-indexing, a new upload or a deletion re-derives it without a
# TTL to tune: the key simply stops matching.
_corpus_cache: dict[tuple[str, int], tuple[frozenset[str], str]] = {}
_corpus_lock = threading.Lock()
# Translations, memoised across requests. The agentic loop decomposes one
# question into several sub-queries and retrieves per sub-query, so without
# this a single ask pays for several translations, and a repeated ask pays
# again. Bounded and cleared wholesale rather than evicted one at a time -
# this holds short strings, and exactness of eviction order buys nothing.
_translations: dict[tuple[str, str], str] = {}
_translations_lock = threading.Lock()
_TRANSLATION_CACHE_MAX = 2048

# (project_id, content_version) -> language name. Separate from the corpus
# profile because the profile must stay free: is_active() calls it on the
# answer-cache path, where an LLM round-trip per cache lookup would be absurd.
_language_cache: dict[tuple[str, int], str] = {}
_language_lock = threading.Lock()


def reset_caches() -> None:
    """Drop the memoised corpus scripts and translations.

    Tests reach for this between cases; nothing in the request path needs it,
    because the corpus key already carries content_version.
    """
    with _corpus_lock:
        _corpus_cache.clear()
    with _translations_lock:
        _translations.clear()
    with _language_lock:
        _language_cache.clear()


def corpus_profile(db: Session, project: Project) -> tuple[frozenset[str], str]:
    """The scripts this project's indexed text uses, and a sample of it.

    The sample comes back with it because the language still has to be
    NAMED before a query can be translated into it, and a script is not a
    language - Devanagari is Hindi, Marathi or Nepali. `corpus_language`
    identifies it from this sample, once per corpus version.
    """
    key = (str(project.id), int(getattr(project, "content_version", 0) or 0))
    with _corpus_lock:
        hit = _corpus_cache.get(key)
    if hit is not None:
        return hit

    try:
        rows = db.execute(
            _CORPUS_SAMPLE_SQL,
            {"project_id": str(project.id), "sample": settings.cross_lingual_sample},
        ).scalars().all()
    except Exception:
        # Never fail a query over a profiling read. An unknown corpus profile
        # means the gate stays shut, which is exactly today's behaviour.
        logger.warning("Corpus language profiling failed", exc_info=True)
        return frozenset(), ""

    found: set[str] = set()
    for row in rows:
        found |= scripts(row or "")
    # The longest sampled chunk, capped: the reference passage only has to
    # show the model what the language looks like.
    sample = max((r or "" for r in rows), key=len, default="")
    profile = (frozenset(found), sample[: settings.cross_lingual_sample_chars])

    with _corpus_lock:
        _corpus_cache[key] = profile
    return profile


# Naming the target language beats showing an example of it, and that is
# MEASURED, not assumed. The first version of this prompt passed a sample
# passage and asked for "the same language as this reference passage" - which
# avoided having to identify the language at all. Against gpt-4o-mini it
# failed on every one of 24 cross-lingual queries: the model read the sample
# as CONTENT and answered the question in the user's own language instead of
# translating it. (The script guard below caught all 24, so the effect was a
# wasted call rather than a poisoned query - but the fix did nothing.) Naming
# the language costs one extra call per corpus version and works.
_TRANSLATE_SYSTEM = (
    "Translate the user's search query into {language}. Preserve every proper "
    "noun, number, date and technical term exactly. Do not answer the query, "
    "do not explain it, do not add anything: output only the translation. If "
    "it is already in {language}, repeat it unchanged."
)

# Deliberately not "what language is this" - a chunk of a technical manual can
# be mostly code, and a model asked an open question about it will happily
# answer "Python". Constrained to a language name, with a fallback stated.
_IDENTIFY_SYSTEM = (
    "Name the human language this text is written in, in English, as a single "
    "word. Ignore any code, markup, numbers or tables. Output only the "
    "language name."
)

def corpus_language(db: Session, project: Project, llm, on_usage=None) -> str | None:
    """What language this project's documents are written in, or None.

    One call per corpus version, so a project answering thousands of
    cross-lingual questions pays for this once. None on any failure, and the
    caller then leaves the question alone - guessing "English" here would
    quietly translate a Tamil question into English for a Hindi corpus.
    """
    key = (str(project.id), int(getattr(project, "content_version", 0) or 0))
    with _language_lock:
        hit = _language_cache.get(key)
    if hit is not None:
        return hit or None

    _scripts_found, sample = corpus_profile(db, project)
    if not sample:
        return None
    try:
        from .tracing import observed_generate

        name, usage = observed_generate(
            llm, _IDENTIFY_SYSTEM, sample, name="identify-corpus-language"
        )
        if on_usage is not None:
            on_usage(usage)
    except Exception:
        logger.warning("Corpus language identification failed", exc_info=True)
        return None

    name = (name or "").strip().strip(".").split()[0] if (name or "").strip() else ""
    # A language name, not a sentence, not a refusal, not a code language.
    if not name or not name.isalpha() or len(name) > 30:
        logger.info("Corpus language identification returned %r; skipping", name)
        name = ""
    with _language_lock:
        _language_cache[key] = name
    return name or None


def should_consider(db: Session, project: Project, question: str) -> bool:
    """Could translating this question help? Cheap - never calls a model.

    True only when the feature is on, the question is written in a non-Latin
    script, and the corpus uses none of that script. This is the same gate as
    before and it is still the FIRST gate, because it costs a cached read and
    keeps every same-script project - the common case - entirely untouched.
    """
    if not settings.cross_lingual_retrieval_enabled or not question.strip():
        return False
    asked = scripts(question)
    if not asked:
        return False
    corpus_scripts, sample = corpus_profile(db, project)
    if not sample:
        return False
    return not (asked & corpus_scripts)


def looks_weak(rows) -> bool:
    """Did searching with the question as asked land anywhere useful?

    The SECOND gate, and the one that decides whether a model call is worth
    making. An embedder with no useful representation of a language scores
    every chunk near zero - the query vector points nowhere - and that is
    visible without knowing which chunk was the right one.

    Missing or non-numeric similarities read as weak: a caller that cannot
    report similarity gets the previous always-translate behaviour rather than
    a silent skip.
    """
    best = 0.0
    for row in rows or ():
        value = row.get("similarity") if isinstance(row, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            best = max(best, float(value))
    return best < settings.cross_lingual_similarity_floor


def retrieval_query(
    db: Session,
    project: Project,
    question: str,
    rows=None,
    llm=None,
    on_usage=None,
) -> str:
    """The string to EMBED for this question - the question, or a translation.

    Returns the question unchanged unless every one of these holds:

      * the feature is enabled,
      * the question is written in a non-Latin script,
      * the corpus uses none of that question's scripts,
      * ``rows`` - the result of searching with the question AS ASKED - came
        back weak, meaning the embedder placed the query nowhere useful, and
      * the translation call succeeds and returns something usable.

    Passing ``rows=None`` skips the weakness check and translates whenever the
    script gate opens; that is for callers who cannot run a search first.

    Any failure returns the question, so the worst case is the behaviour that
    shipped before this existed. The caller keeps the ORIGINAL question for
    generation - translating what the model answers from would answer in the
    wrong language, which is the thing this must not break.

    ``llm`` is a provider OR a zero-argument factory returning one - the same
    shape ``_llm_step`` takes in services/query.py - so the request's memoized
    client is reused without resolving its key on queries where the gate never
    fires. ``on_usage`` receives the TokenUsage of the call. Neither is
    optional bookkeeping: this project meters and traces every token it spends,
    and an unmetered call here would be a silent hole in the usage table.
    """
    if not should_consider(db, project, question):
        return question
    if rows is not None and not looks_weak(rows):
        # The search already landed somewhere solid, so the embedder does
        # understand this language and a translation can only lose nuance.
        return question

    asked = scripts(question)
    _corpus_scripts, sample = corpus_profile(db, project)

    cache_key = (question, sample[:64])
    with _translations_lock:
        cached = _translations.get(cache_key)
    if cached is not None:
        return cached

    try:
        # Imported here rather than at module scope: app.providers pulls in
        # every vendor SDK, and this module is imported by retrieval, which is
        # imported by nearly everything.
        from .tracing import observed_generate

        if llm is None:
            from ..providers import registry, resolver

            llm = registry.get_llm(
                project.llm_provider,
                project.llm_model,
                resolver.resolve_llm_key(db, project),
            )
        elif not hasattr(llm, "generate_with_usage") and callable(llm):
            # A factory. Resolved HERE and not before, so a query that never
            # reaches this line never pays for the key lookup.
            llm = llm()
        language = corpus_language(db, project, llm, on_usage)
        if language is None:
            return question
        # observed_generate rather than a bare call: this is a real model call
        # and it belongs in the trace next to condense/plan/generate, not
        # hidden inside retrieval. It returns (text, usage) and never raises
        # on a tracing fault.
        translated, usage = observed_generate(
            llm,
            _TRANSLATE_SYSTEM.format(language=language),
            question,
            name="translate-query",
        )
        if on_usage is not None:
            on_usage(usage)
    except Exception:
        logger.warning(
            "Cross-lingual query translation failed; embedding the question "
            "as asked",
            exc_info=True,
        )
        return question

    translated = (translated or "").strip()
    if not translated:
        return question
    # A model that echoed the question back, or answered in the wrong script,
    # has given us nothing - and embedding its commentary would be worse than
    # embedding the question. Require that it actually left the asked script.
    if scripts(translated) & asked:
        logger.info("Translation stayed in the question's script; using the question")
        return question

    with _translations_lock:
        if len(_translations) >= _TRANSLATION_CACHE_MAX:
            _translations.clear()
        _translations[cache_key] = translated
    return translated


def is_active(db: Session, project: Project, question: str) -> bool:
    """Would this question be translated before being embedded?

    Read-only and free - no LLM call. The answer cache key uses it, because a
    cached answer computed before this feature existed was computed from
    different sources, and serving it afterwards would hide the fix for up to
    the cache TTL.

    DELIBERATELY COARSER than the real decision: whether a translation actually
    happens also depends on how the first search scored, which is not known
    when the cache key is built. So this answers "is this a cross-lingual
    question" and some questions get their own cache bucket without being
    translated. That costs a cache entry, never a wrong answer - the bucket is
    a key, not behaviour.
    """
    return should_consider(db, project, question or "")
