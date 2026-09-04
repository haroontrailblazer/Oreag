"""The index config and the query config must never drift apart.

`content_tsv` is what gets INDEXED; `websearch_to_tsquery` is what gets
SEARCHED. If one says 'english' and the other says 'simple', the terms never
meet and lexical search returns nothing at all - no error, no warning, just an
empty half of hybrid search that looks exactly like "this corpus had no keyword
matches". Nothing else in the suite would catch it, because the suite runs on
SQLite where neither expression exists.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RETRIEVAL = pathlib.Path(__file__).resolve().parent.parent / "app/services/retrieval.py"


def _query_configs() -> set[str]:
    """Configs the QUERY side can parse with.

    Since migration 0039 the config is per project, so retrieval.py no longer
    holds a literal - it binds `:ts_config` and casts it. The set of values
    that bind can ever take is services/text_search.py's table, which is what
    this returns, so the agreement test below still compares like with like.
    """
    src = RETRIEVAL.read_text(encoding="utf-8")
    literals = set(re.findall(r"websearch_to_tsquery\('(\w+)'", src))
    assert not literals, (
        f"retrieval.py hardcodes a text-search config {literals} - it must "
        "bind :ts_config so each project is parsed with the stemmer its own "
        "chunks were indexed under"
    )
    assert "CAST(:ts_config AS regconfig)" in src, (
        "retrieval.py no longer binds :ts_config as a regconfig; the query "
        "side and the index side would drift with nothing to catch it"
    )
    from app.services.text_search import ALLOWED_CONFIGS

    return set(ALLOWED_CONFIGS)


def _latest_tsv_migration() -> str:
    """Source of the LATEST migration that (re)defines content_tsv.

    Two shapes count: `generated always as` (0012, 0031) and PG17's
    `alter column ... set expression as` (0033, which avoids dropping the
    column so the SQL editor stops flagging it as destructive).
    """
    latest = None
    for path in sorted((ROOT / "supabase/migrations").glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        if "content_tsv" not in text:
            continue
        if "generated always as" in text or "set expression as" in text:
            latest = text
    assert latest, "no migration defines content_tsv"
    return latest


def _executable_sql(src: str) -> str:
    """The part of a migration Postgres actually runs.

    Everything before the first statement is commentary, which may legitimately
    contain CJK examples; only the statements have to be ASCII.
    """
    starts = [i for i in (src.find("do $"), src.find("drop index"),
                          src.find("alter table")) if i != -1]
    assert starts, "no executable statement found in the migration"
    return src[min(starts):]


def _index_source() -> str:
    """What the INDEX side builds content_tsv from: a column, or a literal.

    Before 0039 this was a quoted literal ('english'). From 0039 it is the
    per-row `ts_config` column, which is the whole point - a generated column
    may take its configuration from another column because
    `to_tsvector(regconfig, text)` is IMMUTABLE.
    """
    sql = _executable_sql(_latest_tsv_migration())
    literals = re.findall(r"to_tsvector\(\s*'(\w+)'", sql)
    columns = re.findall(r"to_tsvector\(\s*([a-z_]+)\s*,", sql)
    assert literals or columns, "no migration defines content_tsv"
    return literals[-1] if literals else columns[-1]


class TestConfigsAgree:
    """The index side and the query side must pick the same stemmer.

    Nothing at runtime checks this. A stemmed index parsed by a different
    stemmer makes `@@` match zero rows - no exception, no log line, just an
    empty lexical half indistinguishable from a corpus with no keyword hits.
    """

    def test_the_index_reads_the_per_row_column(self):
        """Migration 0039 moved the config off a literal and onto a column, so
        one project can be stemmed as Russian while another stays English."""
        assert _index_source() == "ts_config", (
            f"content_tsv is built from {_index_source()!r}; it must be built "
            "from the ts_config column, or a project's document language "
            "cannot reach the rows it owns"
        )

    def test_the_query_binds_the_same_column_values(self):
        """Both sides must draw from ONE table of configuration names."""
        from app.services import text_search

        assert _query_configs() == set(text_search.ALLOWED_CONFIGS)
        assert text_search.DEFAULT_CONFIG in text_search.ALLOWED_CONFIGS

    def test_the_write_side_stamps_what_the_read_side_binds(self):
        """Ingestion writes ts_config, retrieval binds it - from one function.

        If ingestion ever computed the config a different way, every chunk it
        wrote would be unfindable by keyword and only this test would notice.
        """
        ingestion = (ROOT / "backend/app/services/ingestion.py").read_text("utf-8")
        assert "text_search.config_for(project)" in ingestion
        assert 'row["ts_config"]' in ingestion
        assert "text_search.config_for(project)" in RETRIEVAL.read_text("utf-8")

    def test_the_default_still_stems_english(self):
        """'simple' does not stem, so "investing" never reached "invest" and
        the lexical half was close to dead weight on prose. Every project that
        has not chosen a language must keep the English stemmer, which is also
        what makes 0039 additive rather than a change to anything working."""
        from app.services import text_search

        assert text_search.DEFAULT_CONFIG == "english"
        assert text_search.config_for_language(None) == "english"
        assert text_search.config_for_language("Klingon") == "english"


class TestMigrationIsRunnableByOurOwnTooling:
    """scripts/apply_migration.py executes the file through psycopg.

    psycopg scans the whole statement - comments included - for its own
    placeholders and refuses any other percent sign. A `format('...%s...')`
    in the migration made the Supabase SQL editor happy and the repo's own
    migration runner throw, which is a split that only shows up at deploy time.
    """

    def test_no_percent_sign_anywhere(self):
        sql = _latest_tsv_migration()
        assert "%" not in sql, (
            "a percent sign makes this migration unrunnable by "
            "scripts/apply_migration.py (psycopg placeholder parsing)"
        )


class TestMigrationIsNotDestructive:
    """The SQL editor flags `drop column` / `drop index`, and it is right to.

    `content_tsv` is GENERATED STORED so nothing is lost either way, but a
    migration whose safety has to be argued gets run nervously or not at all.
    PG17's SET EXPRESSION changes it in place instead.
    """

    def test_the_latest_migration_drops_nothing(self):
        body = _executable_sql(_latest_tsv_migration()).lower()
        for phrase in ("drop index", "drop column", "drop table", "truncate"):
            assert phrase not in body, f"latest content_tsv migration runs {phrase!r}"


def _char_classes(src: str) -> list[str]:
    r"""Every ``E'([...])'`` character class in a chunk of source.

    Migration 0033 splits unspaced scripts (CJK, Thai) one character per token
    so they are searchable at all. The index side and the query side each carry
    a copy of that regexp, and they must be identical for the same reason the
    config must: transform one and not the other and lexical search returns
    nothing, silently, looking exactly like a corpus with no keyword matches.
    """
    return re.findall(r"E'\(\[([^\]]+)\]\)'", src)


class TestUnspacedScriptNormalisationAgrees:
    def test_the_migration_defines_one(self):
        classes = _char_classes(_latest_tsv_migration())
        assert len(classes) == 1, (
            f"expected exactly one character class in the migration, got {classes}"
        )

    def test_retrieval_uses_the_same_one(self):
        index = _char_classes(_latest_tsv_migration())
        query = _char_classes(RETRIEVAL.read_text(encoding="utf-8"))
        assert query, "retrieval.py no longer normalises the question"
        # retrieval.py holds one shared constant, so every occurrence is the same.
        assert set(query) == set(index), (
            f"index normalises [{index}] but the query normalises [{query}] - "
            "CJK/Thai search will silently return nothing"
        )

    def test_hangul_is_not_included(self):
        """Modern Korean is space-delimited and already tokenised correctly.

        Splitting Hangul per character would break working search rather than
        fix broken search - the regression this guards against.
        """
        cls = _char_classes(_latest_tsv_migration())[0]
        assert "AC00" not in cls.upper(), "Hangul must stay out of the split"

    def test_the_unspaced_abugidas_are_included(self):
        """Lao, Khmer and Burmese, added by 0038.

        0033 covered Chinese, Japanese and Thai and stopped one code point
        short of Lao. For these three the lexical half was dead in exactly the
        way it was for CJK before 0033: measured against the live database, a
        Khmer phrase of five words produced ONE token and a search for a word
        inside it returned nothing.
        """
        cls = _char_classes(_latest_tsv_migration())[0].upper()
        for name, start in (("Lao", "0E80"), ("Myanmar", "1000"), ("Khmer", "1780")):
            assert start in cls, f"{name} is missing from the split"

    def test_tibetan_is_not_included(self):
        """It looks like it belongs, and measurement says otherwise.

        Tibetan delimits SYLLABLES with a tsheg (U+0F0B), which the default
        parser already treats as punctuation - so a Tibetan phrase tokenises
        into four syllable tokens today, finds the word searched for, and
        rejects the same letters in a different order. Adding it would replace
        four meaningful tokens with nine letters and start matching scrambled
        text: breaking working search rather than fixing broken search, the
        same regression test_hangul_is_not_included guards against.
        """
        cls = _char_classes(_latest_tsv_migration())[0].upper()
        assert "0F00" not in cls, "Tibetan already segments on its tsheg"

    def test_the_migration_statements_are_ascii(self):
        """The executable SQL must not depend on file encoding.

        The class is written with \\u escapes precisely so a mangled encoding
        cannot silently turn it into a class that matches nothing - which would
        fail the same quiet way the original bug did.
        """
        body = _executable_sql(_latest_tsv_migration())
        offenders = [ch for ch in body if ord(ch) > 127]
        assert not offenders, f"non-ASCII in executable SQL: {offenders[:5]}"
