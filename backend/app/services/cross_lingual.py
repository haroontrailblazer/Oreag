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

BOTH DIRECTIONS, NOT ONE. The gate above was written for a non-Latin question
over a Latin corpus, and it was one-directional BY ACCIDENT rather than by
design: `scripts()` encodes Latin as the ABSENCE of a script, so an English
question yielded the empty set and `should_consider` returned False before it
ever looked at the corpus. A Hindi or Tamil corpus asked a question in English
- the exact mirror of the case this file exists for - never reached the
cross-lingual path at all.

The reverse direction fires on the language the project DECLARES, not on the
corpus, and that is a deliberate cost decision rather than a shortcut. Deciding
it from the corpus would mean sampling chunks on every English question over
every English corpus, and tests/test_vector_index.py pins the retrieval path at
exactly two statements - semantic and lexical, nothing extra. The declared
language is already in memory on the Project row, so the reverse direction
costs nothing to detect. An UNDECLARED project therefore still misses it; that
is the behaviour that shipped before, preserved, and projects created since
schemas.ProjectCreate began asking at creation have the field set.

WHAT IS STILL OPEN, stated rather than hidden:

  * A ROMANIZED question - "refund policy kya hai" - is Latin script, so no
    script table can tell it from English. It needs a language judgement on the
    question itself, which is a model call, and it is not made here yet.
  * A corpus MIXING scripts satisfies the first gate for both, so a Hindi
    question there is left alone. Measured (see architecture.c4): an English
    question reached the Hindi half at rank 1 or 2 of 8 across 7 cases, and
    searching with a translation as WELL and fusing was built and measured at
    identical ranks, 5/7 either way, so it was not shipped. Closing it properly
    needs per-chunk language tags and per-language sub-searches.
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


# Languages whose writing system is NOT Latin, keyed exactly as
# services/text_search.py keys its stemmer table: a lowercased display name, the
# same vocabulary `projects.document_language` stores and the Settings picker
# offers.
#
# READ ONLY BY THE REVERSE DIRECTION, and that is the whole reason it exists as
# a name table rather than being derived from the corpus. Deciding "is this
# Latin-script question crossing a boundary" from the corpus itself would cost a
# database round trip on the hot path; the declared language is already in
# memory on the Project row.
#
# An unlisted name reads as Latin and the gate stays shut, which is precisely
# the behaviour that shipped before the reverse direction existed - so a missing
# entry costs a silent miss rather than a wrong translation. The entries are the
# languages behind the scripts in `_SCRIPTS` above, plus the common alternate
# names a user might type.
_NON_LATIN_LANGUAGES: frozenset[str] = frozenset(
    {
        # devanagari
        "hindi", "marathi", "nepali", "sanskrit", "konkani", "maithili",
        # other brahmic
        "bengali", "bangla", "assamese", "punjabi", "gujarati", "odia", "oriya",
        "tamil", "telugu", "kannada", "malayalam", "sinhala", "sinhalese",
        # southeast asian
        "thai", "lao", "tibetan", "burmese", "myanmar", "khmer", "cambodian",
        # caucasus and horn of africa
        "georgian", "armenian", "amharic", "tigrinya",
        # semitic
        "hebrew", "yiddish", "arabic", "persian", "farsi", "dari", "urdu",
        "pashto", "sindhi", "uyghur", "kurdish",
        # cyrillic
        "russian", "ukrainian", "belarusian", "bulgarian", "serbian",
        "macedonian", "kazakh", "kyrgyz", "tajik", "mongolian",
        # greek
        "greek",
        # east asian
        "korean", "japanese", "chinese", "mandarin", "cantonese",
    }
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
    with _question_lock:
        _question_languages.clear()


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

def _language_name(raw: str | None) -> str:
    """A model's reply, accepted only if it is actually a language NAME.

    Taking the first word of whatever came back is NOT enough, and a test
    caught it: asked to name a language the model can answer "I cannot tell",
    whose first word is "I" - which would then be interpolated as "write the
    entire answer in I". A language name is ONE word, so anything with a space
    in it is a sentence, not an answer.
    """
    name = (raw or "").strip().strip(".").strip()
    if not name or len(name) > 30:
        return ""
    if any(ch.isspace() for ch in name):
        return ""
    return name if name.isalpha() else ""


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

    name = _language_name(name)
    if not name:
        logger.info("Corpus language identification was not a language name")
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
    if asked:
        # The original case: a non-Latin question. Fire when the corpus does
        # not use that writing system - a Hindi corpus asked in Hindi already
        # works and is left alone.
        corpus_scripts, sample = corpus_profile(db, project)
        if not sample:
            return False
        return not (asked & corpus_scripts)
    # THE REVERSE DIRECTION. A Latin-script question has no entry in the script
    # table, and this used to return False right here - so a Hindi or Tamil
    # corpus asked a question in English never reached the cross-lingual path
    # at all. That is the exact mirror of the case the feature was built for,
    # and it stayed invisible because `scripts()` encodes Latin as "no script"
    # rather than as a script, so the absence read as "nothing to cross".
    #
    # Detecting it costs NOTHING. The corpus profile is already in hand and
    # already cached per content_version; a corpus written in a script the
    # question does not use is a language boundary by construction, and no
    # language identification and no model call is needed to see it.
    #
    # ...but it must cost NO QUERY. `corpus_profile` samples chunks, and while
    # it is cached per content_version, reaching it here would put a database
    # round trip on the hot path for every English question over every English
    # corpus - the overwhelmingly common case, and one this feature must stay
    # free for. tests/test_vector_index.py pins that: the retrieval path issues
    # exactly two statements, semantic and lexical, nothing extra.
    #
    # So the reverse direction reads the language the project DECLARES, which
    # is a column already loaded on the Project in hand. Since projects now
    # answer that question at creation (schemas.ProjectCreate), it is normally
    # set; when it is not, this returns False and the behaviour is exactly what
    # shipped before - a silent miss, not a new failure.
    declared = (getattr(project, "document_language", None) or "").strip().lower()
    return declared in _NON_LATIN_LANGUAGES


def floor_for(project) -> float:
    """The similarity below which this project counts a search as failed.

    ONE GLOBAL CONSTANT WAS THE WRONG SHAPE, and the reason is the same BYOK
    trap that bites everywhere else in this product: a cosine of 0.40 does not
    mean the same thing on two different embedders. Models differ in where they
    place their score distribution - some compress every score into 0.7-0.9,
    others spread 0.0-0.6 - so a floor tuned against `text-embedding-3-small`
    is simply a different question when asked of `gemini-embedding-001`. With
    22 selectable models there is no single number that is right for all of
    them, and no vendor publishes what would make one derivable.

    NULL means "use the global default", so every project that predates the
    column behaves exactly as it did. Read explicitly against None rather than
    with `or`, because 0.0 is a REAL setting - "never translate, the embedder
    is fine" - and `or` would silently restore the default while the UI showed
    the zero the user chose. models.py documents the same trap on
    min_similarity, and it is the same bug both times.
    """
    value = getattr(project, "cross_lingual_floor", None) if project is not None else None
    if value is None:
        return settings.cross_lingual_similarity_floor
    return float(value)


def looks_weak(rows, project=None) -> bool:
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
    return best < floor_for(project)


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
    if rows is not None and not looks_weak(rows, project):
        # The search already landed somewhere solid, so the embedder does
        # understand this language and a translation can only lose nuance.
        return question

    asked = scripts(question)
    corpus_scripts, sample = corpus_profile(db, project)

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
    # embedding the question. What "it moved" MEANS depends on the direction.
    produced = scripts(translated)
    if asked:
        # Non-Latin question: it must have LEFT the asked script.
        if produced & asked:
            logger.info(
                "Translation stayed in the question's script; using the question"
            )
            return question
    elif corpus_scripts and not (produced & corpus_scripts):
        # Reverse direction. `asked` is empty here, so the test above can never
        # fail and an echoed English question would sail straight through and
        # be embedded as though it were a translation. The corpus's own script
        # has to be PRESENT instead.
        logger.info(
            "Translation never reached the corpus script; using the question"
        )
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


# ── the language the ANSWER is written in ───────────────────────────────────
#
# A separate problem from everything above, discovered by measurement rather
# than reasoning. `system_prompt_for` tells the model to "write the answer in
# the same language the question was asked in, even when the source material
# is in another language", and that instruction is NOT reliably followed: with
# an English question and Hindi sources ranked first, gpt-4o-mini answered in
# HINDI three times out of three.
#
# Two attempts to fix it by rewording made it WORSE, and both failed the same
# way - naming the foreign script or shouting the rule made the model latch
# onto the sources harder:
#
#     current wording                       12/18
#     emphatic "SAME LANGUAGE AS QUESTION"   4/18
#     naming the question's writing system  10/18
#     naming the question's LANGUAGE        18/18
#
# The mechanism that works is the one the answer_language setting already
# uses: name the target language positively and never mention the sources.
# So this names it - which means finding out what it is.
_question_languages: dict[str, str] = {}
_question_lock = threading.Lock()


def _sources_use_another_script(question: str, sources) -> bool:
    """Do the retrieved sources contain a writing system the question lacks?

    This is the exact condition that failed. The reverse - a Devanagari
    question with Latin-only sources - was measured and answers correctly
    without help, so it deliberately does not trigger a model call.
    """
    asked = scripts(question or "")
    found: set[str] = set()
    for source in sources or ():
        if isinstance(source, dict):
            found |= scripts(source.get("content") or "")
    return bool(found - asked)


def answer_language_for(
    project, question: str, sources, llm=None, on_usage=None, fallback=None
) -> str | None:
    """Name the question's language, when leaving it implicit would not hold.

    Returns None - meaning "say nothing, keep the existing instruction" - for
    every ordinary query. It only names a language when the retrieved sources
    are written in a script the question is not, which is the case measured to
    fail, and never when the project has already pinned answer_language.

    One model call per distinct question, memoised across requests, and only
    on the queries that need it.
    """
    if not settings.cross_lingual_retrieval_enabled or not (question or "").strip():
        return None
    if not _sources_use_another_script(question, sources):
        # The sources are in the question's own writing system, and plain
        # mirroring was measured to hold there (3/3 both ways). Naming a
        # language would cost a call and buy nothing.
        return None

    key = question.strip()
    with _question_lock:
        hit = _question_languages.get(key)
    if hit is not None:
        return hit or fallback

    try:
        from .tracing import observed_generate

        if llm is None:
            # No client to ask. `fallback` is the project's house language,
            # which is a better answer than guessing and a better answer than
            # leaving the unreliable instruction in place.
            return fallback
        if not hasattr(llm, "generate_with_usage") and callable(llm):
            llm = llm()
        name, usage = observed_generate(
            llm, _IDENTIFY_SYSTEM, question, name="identify-question-language"
        )
        if on_usage is not None:
            on_usage(usage)
    except Exception:
        logger.warning("Question-language identification failed", exc_info=True)
        return fallback

    name = _language_name(name)
    with _question_lock:
        if len(_question_languages) >= _TRANSLATION_CACHE_MAX:
            _question_languages.clear()
        _question_languages[key] = name
    return name or fallback
