"""Per-project stemming: one language table, two sides that must agree.

The contract has no runtime check. Ingestion stamps `chunks.ts_config` and the
generated `content_tsv` is built with it; retrieval binds the same value to
parse the query. If they ever disagree `@@` matches zero rows - no exception,
no log line, an empty lexical half indistinguishable from a corpus with no
keyword hits. So most of this file is about the two sides drawing from ONE
function, and about the fallback never producing a name the database would
reject.

What cannot run here: whether `russian` actually stems better than `english`.
That needs a live PostgreSQL with the Snowball dictionaries; the suite runs on
SQLite. It was measured against the real database before the mapping was
written, and the evidence is recorded in services/text_search.py's docstring.
"""
import uuid

import pytest

from app.models import Project
from app.services import text_search


class TestTheMapping:
    def test_unset_means_english(self):
        """Every project predating 0039 has NULL here, and must keep exactly
        the behaviour it had - that is what makes this change additive."""
        assert text_search.config_for_language(None) == "english"
        assert text_search.config_for_language("") == "english"
        assert text_search.config_for_language("   ") == "english"

    def test_an_unknown_language_falls_back_rather_than_raising(self):
        """The value is cast to regconfig in SQL. A name Postgres does not
        know is a hard error on EVERY subsequent query for that project, so an
        old row, a hand-edited value, or an API caller inventing a language
        must degrade instead of poisoning the project."""
        for junk in ("Klingon", "en-GB", "'; drop table chunks; --", "Русский язык"):
            assert text_search.config_for_language(junk) == "english"

    @pytest.mark.parametrize(
        "language,config",
        [
            ("Russian", "russian"),
            ("russian", "russian"),
            ("  RUSSIAN  ", "russian"),
            ("Hindi", "hindi"),
            ("Arabic", "arabic"),
            ("Portuguese", "portuguese"),
            ("Portuguese (Brazil)", "portuguese"),
            ("English", "english"),
        ],
    )
    def test_lookup_is_case_and_space_insensitive(self, language, config):
        assert text_search.config_for_language(language) == config

    def test_every_emitted_config_is_declared_allowed(self):
        """ALLOWED_CONFIGS is what the drift guard compares against and what
        the live-database check validates against pg_ts_config."""
        for language in text_search.SUPPORTED_LANGUAGES:
            assert text_search.config_for_language(language) in text_search.ALLOWED_CONFIGS

    def test_no_config_name_could_be_sql(self):
        """Belt and braces: the value is bound, not interpolated, but a table
        of identifiers should still contain only identifiers."""
        for config in text_search.ALLOWED_CONFIGS:
            assert config.isalpha() and config.islower(), config

    def test_config_for_tolerates_a_project_without_the_column(self):
        """Matching generation.py: lightweight project stand-ins in other test
        modules do not carry columns added by later migrations."""

        class Bare:
            pass

        assert text_search.config_for(Bare()) == "english"

    def test_config_for_reads_the_document_language_not_the_answer_language(self):
        """The two settings are deliberately separate. A Hindi corpus that
        answers in English is an ordinary configuration, and conflating them
        would force one of the two to be wrong."""
        project = Project(
            id=uuid.uuid4(),
            document_language="Russian",
            answer_language="English",
        )
        assert text_search.config_for(project) == "russian"

        project.document_language = None
        assert text_search.config_for(project) == "english"


class TestTheTwoSidesCannotDrift:
    def test_the_query_binds_rather_than_hardcodes(self):
        from app.services.retrieval import LEXICAL_SQL, _TSV_QUERY

        assert "CAST(:ts_config AS regconfig)" in _TSV_QUERY
        assert "'english'" not in _TSV_QUERY
        sql = str(LEXICAL_SQL)
        # Both the filter and the ts_rank_cd ordering parse the query, and
        # both must use the same bound config.
        assert sql.count("CAST(:ts_config AS regconfig)") == 2

    def test_the_lexical_statement_still_binds_everything_else(self):
        """The config joined a parameter set that the byte-pinned SQL test
        also watches; this is the human-readable half of that guard."""
        from app.services.retrieval import LEXICAL_SQL

        params = set(LEXICAL_SQL.compile().params)
        assert {"qvec", "project_id", "limit", "question", "ts_config"} <= params


class TestChangingTheLanguageRestampsTheRows:
    """The setting has to reach rows already in the table.

    Everything else on the answer-policy card changes only how a NEW answer is
    produced. This one changes what the index means, so leaving old chunks on
    the old stemmer would make the query side and the index side disagree for
    exactly the projects that opted in.
    """

    def test_the_route_updates_chunks_and_bumps_the_content_version(self):
        source = (
            __import__("pathlib").Path(__file__).parent.parent
            / "app/routers/projects.py"
        ).read_text(encoding="utf-8")
        assert "sa_update(Chunk)" in source
        assert "ts_config=text_search.config_for_language(wanted)" in source
        # Stale answers were computed against different lexical matches.
        block = source[source.index("if body.document_language is not None:"):]
        assert "bump_content_version(db, project)" in block[:900]

    def test_it_compares_resolved_configs_not_names(self):
        """Portuguese and Portuguese (Brazil) resolve to the same stemmer, so
        switching between them must rewrite nothing."""
        assert text_search.config_for_language(
            "Portuguese"
        ) == text_search.config_for_language("Portuguese (Brazil)")
        source = (
            __import__("pathlib").Path(__file__).parent.parent
            / "app/routers/projects.py"
        ).read_text(encoding="utf-8")
        assert (
            "text_search.config_for_language(wanted) != text_search.config_for(project)"
            in source
        )


class TestIngestionStampsTheRow:
    def test_the_default_is_omitted_from_the_insert(self):
        """Same rule as embedding_full: naming a column in the INSERT breaks
        every upload on a database that has not run the migration yet, and the
        overwhelming majority of projects are on the default."""
        source = (
            __import__("pathlib").Path(__file__).parent.parent
            / "app/services/ingestion.py"
        ).read_text(encoding="utf-8")
        assert "if ts_config != text_search.DEFAULT_CONFIG:" in source

    def test_the_config_is_resolved_once_not_per_batch(self):
        source = (
            __import__("pathlib").Path(__file__).parent.parent
            / "app/services/ingestion.py"
        ).read_text(encoding="utf-8")
        resolve = source.index("ts_config = text_search.config_for(project)")
        loop = source.index("for i in range(0, len(chunks), batch_size):")
        assert resolve < loop, "the lookup moved inside the batch loop"


class TestMigration0039Shape:
    """Same house rules every migration here is held to."""

    @staticmethod
    def _sql() -> str:
        return (
            __import__("pathlib").Path(__file__).parent.parent.parent
            / "supabase/migrations/0039_per_project_text_search.sql"
        ).read_text(encoding="utf-8")

    def test_no_percent_sign_anywhere(self):
        """psycopg scans the whole statement for placeholders, comments
        included, so one percent sign makes the file unrunnable by
        scripts/apply_migration.py."""
        assert "%" not in self._sql()

    def test_every_statement_is_idempotent(self):
        sql = self._sql()
        assert sql.count("add column if not exists") == 2
        assert "create index if not exists" in sql
        assert "drop column" not in sql and "drop table" not in sql

    def test_it_adds_both_halves(self):
        sql = self._sql()
        assert "ts_config regconfig not null default 'english'" in sql
        assert "add column if not exists document_language text" in sql

    def test_the_generated_column_reads_the_column_not_a_literal(self):
        sql = self._sql()
        body = sql[sql.index("do $migration$"):]
        assert "to_tsvector(\n      ts_config," in body
        assert "to_tsvector('english'" not in body
