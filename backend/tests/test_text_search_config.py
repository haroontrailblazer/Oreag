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
    src = RETRIEVAL.read_text(encoding="utf-8")
    return set(re.findall(r"websearch_to_tsquery\('(\w+)'", src))


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


def _index_config() -> str:
    """The config on the LATEST migration that defines content_tsv."""
    # Tolerant of whitespace: 0033 wraps the expression across several lines,
    # so the config name no longer sits on the same line as `generated always`.
    matches = re.findall(
        r"to_tsvector\(\s*'(\w+)'", _executable_sql(_latest_tsv_migration())
    )
    assert matches, "no migration defines content_tsv"
    return matches[-1]


class TestConfigsAgree:
    def test_every_query_uses_one_config(self):
        configs = _query_configs()
        assert len(configs) == 1, f"retrieval.py mixes configs: {configs}"

    def test_the_query_matches_the_index(self):
        query = _query_configs().pop()
        assert query == _index_config(), (
            f"lexical search queries with '{query}' but content_tsv is built "
            f"with '{_index_config()}' - the terms will never meet and lexical "
            "search will silently return nothing"
        )

    def test_it_is_a_stemming_config(self):
        """'simple' does not stem, so "investing" never reached "invest" and
        the lexical half was close to dead weight on prose."""
        assert _index_config() != "simple"


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

    def test_the_migration_statements_are_ascii(self):
        """The executable SQL must not depend on file encoding.

        The class is written with \\u escapes precisely so a mangled encoding
        cannot silently turn it into a class that matches nothing - which would
        fail the same quiet way the original bug did.
        """
        body = _executable_sql(_latest_tsv_migration())
        offenders = [ch for ch in body if ord(ch) > 127]
        assert not offenders, f"non-ASCII in executable SQL: {offenders[:5]}"
