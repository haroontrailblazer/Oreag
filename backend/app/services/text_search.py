"""Which Postgres text-search configuration a project's keyword search uses.

ONE definition, read by both sides of a contract that has no runtime check.
services/ingestion.py stamps it onto every chunk it writes (so the generated
`content_tsv` is built with it) and services/retrieval.py passes the same
value when it parses a query. If those two ever disagree the `@@` operator
simply matches nothing - no exception, no log line, just an empty lexical half
that looks exactly like a corpus with no keyword hits.

WHY THIS EXISTS. Until migration 0039 every project on the server was indexed
with the 'english' configuration, because a generated column takes a CONSTANT
configuration and there was nowhere to put a per-project one. English stemming
knows no other language's morphology, so a query only matched when the user
typed the exact surface form the document happened to use - and inflected
languages make that the exception rather than the rule.

MEASURED on this product's own database, one sentence per language and a query
word appearing in it in a DIFFERENT grammatical form. Under 'english' the
search FAILS and under the language's own configuration it succeeds, for:

    Russian, German, Spanish, Portuguese, Italian, Dutch, Hindi, Nepali,
    Arabic, Indonesian, Greek, Hungarian, Serbian, Swedish, Catalan, Basque,
    Yiddish

Russian shows what changes - 'otchyoty' (plural) is stored as 'otchet', so the
nominative a user actually types finds it, and the stopword list drops a token
on the way. Turkish, Tamil, Finnish, Romanian, Irish and Armenian have Snowball
stemmers that did NOT rescue the pair tested, so they are offered honestly as
"available" rather than "measured to help".

WHY EVERY OTHER LANGUAGE STAYS ON ENGLISH. The alternative for a language with
no stemmer is 'simple', which lower-cases and splits and nothing else. Measured
against 'english' on Bengali and Polish it made no difference to either, and it
would COST the English stemming that a mixed corpus (a Bengali project with
English technical terms in it) still benefits from. So an unknown language maps
to 'english' - identical to today's behaviour, which makes 0039 additive rather
than a change to anything already working.
"""

from __future__ import annotations

# Language name (as stored in projects.document_language) -> Postgres config.
#
# The KEY is a display name, not a locale code, because it is the same
# vocabulary the answer-language setting uses and the two appear side by side
# in the UI. Lookup is case-insensitive and unknown names fall back to English,
# so an old row, a hand-edited value or an API caller inventing a language can
# never produce an invalid regconfig - which would be a hard SQL error on every
# subsequent query for that project.
#
# Only languages whose configuration DIFFERS from english appear here; anything
# absent resolves to english by the fallback, which is the honest encoding of
# "we have no stemmer for this and pretending otherwise would help nobody".
_CONFIGS: dict[str, str] = {
    # Measured: a query in a different grammatical form finds the document
    # under this configuration and does not under 'english'.
    "arabic": "arabic",
    "basque": "basque",
    "catalan": "catalan",
    "dutch": "dutch",
    "german": "german",
    "greek": "greek",
    "hindi": "hindi",
    "hungarian": "hungarian",
    "indonesian": "indonesian",
    "italian": "italian",
    "nepali": "nepali",
    "portuguese": "portuguese",
    "portuguese (brazil)": "portuguese",
    "russian": "russian",
    "serbian": "serbian",
    "spanish": "spanish",
    "swedish": "swedish",
    "yiddish": "yiddish",
    # Snowball stemmers that exist and are the right choice for the language,
    # but whose benefit the measurement did not demonstrate on the pair tested.
    # Offered because a stemmer built for the language beats one built for
    # English either way, and marked so nobody reads this list as all-measured.
    "danish": "danish",
    "finnish": "finnish",
    "french": "french",
    "irish": "irish",
    "lithuanian": "lithuanian",
    "norwegian": "norwegian",
    "romanian": "romanian",
    "tamil": "tamil",
    "turkish": "turkish",
    "armenian": "armenian",
    # Explicit rather than by fallback, so the intent is visible.
    "english": "english",
}

DEFAULT_CONFIG = "english"

# Every configuration this module can ever emit. retrieval.py sends the value
# as a bind parameter cast to regconfig, so a value outside this set would be
# a SQL error rather than a wrong result - and the API accepts free text.
# Checked against pg_ts_config in the tests.
ALLOWED_CONFIGS = frozenset(_CONFIGS.values())

# The language names the UI offers, for the test that keeps the two in step.
SUPPORTED_LANGUAGES = tuple(sorted(_CONFIGS))


def config_for_language(language: str | None) -> str:
    """The Postgres configuration for a document language name.

    Falls back to English for None, blank, and anything unrecognised. The
    fallback is not laziness: this value is interpolated into a regconfig cast,
    so an unknown name must not reach the database, and English is what every
    project used before this setting existed.
    """
    if not language:
        return DEFAULT_CONFIG
    return _CONFIGS.get(language.strip().lower(), DEFAULT_CONFIG)


def config_for(project) -> str:
    """The configuration for a project, tolerant of rows predating 0039.

    getattr rather than attribute access, matching the pattern in
    generation.py: tests and any caller holding a lightweight stand-in for
    Project should not have to know about this column.
    """
    return config_for_language(getattr(project, "document_language", None))
