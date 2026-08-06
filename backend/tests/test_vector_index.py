"""The HNSW gate and the indexable SQL siblings it routes to.

The live database is unreachable, so nothing here connects to Postgres. Two
things ARE testable without one, and they are the two that actually break:

  * SQL TEXT INVARIANTS. A partial expression index is only used when the
    ORDER BY operand is textually the index expression AND the WHERE clause
    repeats the index predicate AND both carry the same dimension as the index
    name. Get one of the three wrong and the query silently falls back to a seq
    scan that is SLOWER than today (it now also pays the cast per row) while
    still returning correct rows - so no test that only checks results would
    ever catch it. These assertions are that check. The capability probe is the
    same check from the other side: without a server all we can assert is that
    it still ASKS for a valid cosine HNSW index on public.chunks instead of
    trusting an index NAME.

  * THE GATE FAILING CLOSED. Every unexpected condition - no pgvector, an old
    pgvector, a missing/invalid index, an unknown dimension, a probe error, a
    project too small or too small a share of the table - must run the ORIGINAL
    statement object and issue exactly the statements it issues today. A gate
    that fails OPEN would change the DB call sequence under every existing
    fake, which is also how it would misbehave in production against a server
    it cannot interrogate.

Recall and plan quality (does the planner actually pick the index, and what is
recall@k) cannot be established without a database; that belongs in a live
verify_* harness.
"""
import re
import uuid

import pytest

from app.models import Project
from app.services import explore, retrieval


@pytest.fixture(autouse=True)
def _reset_ann_caches():
    """The capability probe and the size memo are process-wide by design."""
    retrieval.reset_ann_caches()
    yield
    retrieval.reset_ann_caches()


def _project(dimensions=1536):
    return Project(
        id=uuid.uuid4(),
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=dimensions,
        content_version=7,
    )


# ── fakes ───────────────────────────────────────────────────────────────────


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _Savepoint:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConnection:
    """The Core connection the capability probe and size query run on."""

    def __init__(self, session):
        self._session = session

    def begin_nested(self):
        return _Savepoint()

    def execute(self, statement, params=None):
        return self._session._answer(statement, params, core=True)


class _FakeSession:
    """A session that answers the probe, the size query and the real query.

    ``capable=False`` models everything the gate has to survive - most
    importantly a session that cannot hand out a Core connection at all, which
    is what every pre-existing test fake looks like.

    ``indexes`` is what the probe RETURNED, i.e. names that already passed its
    structural filter (right table, right access method, right opclass). That
    filter lives in SQL and cannot be exercised from here at all - see
    TestCapabilityProbeSql for what is assertable without a server.
    """

    def __init__(
        self,
        capable=True,
        vector_version="0.8.0",
        indexes=("chunks_embedding_hnsw_1536_idx",),
        total_chunks=1_000_000.0,
        project_chunks=200_000,
        probe_raises=False,
        memory_indexes=("memory_chunks_embedding_hnsw_1536_idx",),
        total_memory_chunks=1_000_000.0,
        project_memory_chunks=200_000,
    ):
        self.capable = capable
        self.vector_version = vector_version
        self.indexes = list(indexes)
        self.total_chunks = total_chunks
        self.project_chunks = project_chunks
        self.probe_raises = probe_raises
        self.memory_indexes = list(memory_indexes)
        self.total_memory_chunks = total_memory_chunks
        self.project_memory_chunks = project_memory_chunks
        self.statements = []       # every statement passed to session.execute
        self.core_statements = []  # every statement run on the connection
        self.rollbacks = 0
        self.savepoint_rollbacks = 0

    # -- Session API used by the gate and by retrieve() ----------------------
    def connection(self):
        if not self.capable:
            raise AttributeError("connection")
        return _FakeConnection(self)

    def execute(self, statement, params=None):
        self.statements.append(statement)
        return self._answer(statement, params, core=False)

    def rollback(self):
        self.rollbacks += 1

    def begin_nested(self):
        """A savepoint, like SQLAlchemy's. It does NOT swallow the exception -
        it rolls back to the savepoint and re-raises, leaving the OUTER
        transaction (and every uncommitted write in it) intact."""
        outer = self

        class _SP:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                if exc_type is not None:
                    outer.savepoint_rollbacks += 1
                return False  # never suppress

        return _SP()

    # -- routing ------------------------------------------------------------
    def _answer(self, statement, params, core):
        sql = str(statement)
        if core:
            self.core_statements.append(statement)
        if self.probe_raises and "pg_extension" in sql:
            raise RuntimeError("catalog unavailable")
        if "pg_extension" in sql:
            return _Rows(
                [
                    {
                        "vector_version": self.vector_version,
                        "hnsw_indexes": self.indexes,
                        "chunk_reltuples": self.total_chunks,
                        "memory_hnsw_indexes": self.memory_indexes,
                        "memory_reltuples": self.total_memory_chunks,
                    }
                ]
            )
        if "sum(chunk_count)" in sql:
            return _Rows([self.project_chunks])
        if "from memory_chunks where project_id" in sql.lower():
            return _Rows([self.project_memory_chunks])
        if "set_config" in sql:
            return _Rows([])
        if "m.tags" in sql:  # a memory-target neighbour query
            return _Rows(
                [
                    {
                        "id": 2,
                        "content": "a saved memory",
                        "tags": ["x"],
                        "pinned": False,
                        "source": "mcp",
                        "similarity": 0.7,
                    }
                ]
            )
        return _Rows(
            [
                {
                    "id": 1,
                    "content": "alpha",
                    "page_number": None,
                    "chunk_index": 0,
                    "filename": "a.pdf",
                    "similarity": 0.9,
                }
            ]
        )


def _retrieve(db, project):
    """retrieve() with the embedder stubbed out (no provider round trip)."""

    class _Embedder:
        def embed_query(self, q):
            return [0.1] * (project.embedding_dimensions or 1)

    original_resolve = retrieval.resolver.resolve_embedding_key
    original_embedder = retrieval.get_embedder
    retrieval.resolver.resolve_embedding_key = lambda db, p: "k"
    retrieval.get_embedder = lambda *a, **k: _Embedder()
    try:
        return retrieval.retrieve(db, project, "what is X", 5)
    finally:
        retrieval.resolver.resolve_embedding_key = original_resolve
        retrieval.get_embedder = original_embedder


def _semantic_statement(db):
    """The statement retrieve() used for the semantic half."""
    return db.statements[-2]  # -1 is the lexical query


# ── SQL text invariants ─────────────────────────────────────────────────────

ALL_TEMPLATES = [
    ("semantic", retrieval._ANN_SEMANTIC_TEMPLATE),
    ("seed_chunk", explore._ANN_SEED_CHUNK_TEMPLATE),
    ("chunk_rel_chunk", explore._ANN_CHUNK_REL_CHUNK_TEMPLATE),
    ("memory_rel_chunk", explore._ANN_MEMORY_REL_CHUNK_TEMPLATE),
]


def _split_top_level(text_: str) -> list[str]:
    """Split a SELECT list on commas that are not inside parentheses."""
    out, depth, current = [], 0, []
    for ch in text_:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(current))
            current = []
        else:
            current.append(ch)
    out.append("".join(current))
    return [item.strip() for item in out if item.strip()]


def _result_columns(sql: str) -> list[str]:
    """Column names produced by the LAST select list in a statement."""
    start = sql.upper().rindex("SELECT ") + len("SELECT ")
    end = sql.upper().index("FROM", start)
    names = []
    for item in _split_top_level(sql[start:end]):
        alias = re.split(r"\s+AS\s+", item, flags=re.I)[-1]
        names.append(alias.strip().split(".")[-1])
    return names


def _bind_params(sql: str) -> set[str]:
    # (?<!:) so the second colon of a `::vector` cast is not read as a bind
    return set(re.findall(r"(?<!:):([a-z_]+)", sql))


class TestAnnSqlShape:
    """The cast, the predicate and the index name must agree on the dimension.

    A mismatch between any two of them is the classic silent "index is never
    used" bug: the query still returns the right rows, it just does it with a
    seq scan plus a per-row cast.
    """

    @pytest.mark.parametrize("dim", sorted(retrieval.ANN_DIMENSIONS))
    @pytest.mark.parametrize("name,template", ALL_TEMPLATES)
    def test_one_dimension_everywhere(self, name, template, dim):
        sql = str(retrieval.build_ann_sql(template, dim))

        # every dimension mentioned anywhere in the statement is THIS one
        casts = re.findall(r"::vector\((\d+)\)", sql)
        casted = re.findall(r"CAST\(:qvec AS vector\((\d+)\)\)", sql)
        predicates = re.findall(r"vector_dims\([a-z]+\.embedding\) = (\d+)", sql)
        assert casts, f"{name}: no ::vector(d) cast at all"
        assert predicates, f"{name}: no vector_dims predicate - index unusable"
        assert set(casts) | set(casted) | set(predicates) == {str(dim)}

        # the ORDER BY operand must be TEXTUALLY the index expression
        order_by = re.search(r"ORDER BY (.+?)\n\s+LIMIT", sql, re.S)
        assert order_by, f"{name}: no ranked ORDER BY ... LIMIT"
        assert f"c.embedding::vector({dim})" in order_by.group(1)

        # and it must name the index that migration 0018 actually creates
        assert retrieval.ann_index_name(dim) == f"chunks_embedding_hnsw_{dim}_idx"

    @pytest.mark.parametrize("name,template", ALL_TEMPLATES)
    def test_orders_by_distance_ascending(self, name, template):
        sql = str(retrieval.build_ann_sql(template, 1536))
        # nearest first, exactly like `ORDER BY embedding <=> q` today
        assert sql.rstrip().endswith("ORDER BY nn.distance")

    @pytest.mark.parametrize("name,template", ALL_TEMPLATES)
    def test_similarity_is_one_minus_distance(self, name, template):
        sql = str(retrieval.build_ann_sql(template, 768))
        assert "1 - nn.distance AS similarity" in sql

    def test_semantic_sibling_matches_the_exact_statement(self):
        """Same columns in the same order, same binds: the two are drop-in."""
        exact = str(retrieval.SEMANTIC_SQL)
        ann = str(retrieval.ann_semantic_sql(1536))
        assert _result_columns(ann) == _result_columns(exact)
        assert _result_columns(exact) == [
            "id", "content", "page_number", "chunk_index", "filename", "similarity",
        ]
        assert _bind_params(ann) == _bind_params(exact) == {
            "qvec", "project_id", "limit",
        }

    @pytest.mark.parametrize(
        "template,exact",
        [
            (explore._ANN_SEED_CHUNK_TEMPLATE, explore._SEED_CHUNK_SQL),
            (explore._ANN_CHUNK_REL_CHUNK_TEMPLATE, explore._CHUNK_REL_CHUNK_SQL),
            (explore._ANN_MEMORY_REL_CHUNK_TEMPLATE, explore._MEMORY_REL_CHUNK_SQL),
        ],
    )
    def test_explore_siblings_match_their_exact_statements(self, template, exact):
        ann = str(retrieval.build_ann_sql(template, 1024))
        assert _result_columns(ann) == _result_columns(str(exact))
        assert _bind_params(ann) == _bind_params(str(exact))

    def test_chunk_neighbour_still_excludes_the_probe_chunk(self):
        sql = str(retrieval.build_ann_sql(explore._ANN_CHUNK_REL_CHUNK_TEMPLATE, 512))
        assert "c.id <> :id" in sql
        # ...and the memory-target one must NOT (different tables, ids collide)
        memory_sql = str(
            retrieval.build_ann_sql(explore._ANN_MEMORY_REL_CHUNK_TEMPLATE, 512)
        )
        assert "c.id <> :id" not in memory_sql
        assert "x.embedding IS NOT NULL" in memory_sql

    def test_probe_vector_is_uncorrelated(self):
        """Read as an InitPlan, or the HNSW order-by key cannot resolve."""
        for template in (
            explore._ANN_CHUNK_REL_CHUNK_TEMPLATE,
            explore._ANN_MEMORY_REL_CHUNK_TEMPLATE,
        ):
            sql = str(retrieval.build_ann_sql(template, 256))
            assert "(SELECT v FROM probe)" in sql
            assert "x.embedding <=>" not in sql


class TestDimensionAllowlist:
    def test_unknown_dimensions_get_no_sql(self):
        # 3072 exceeds pgvector's 2000-dimension HNSW limit and 999 is not a
        # real embedding size; both must take the exact path, not interpolate.
        for dim in (None, 0, 999, 3072, 2048):
            assert retrieval.ann_semantic_sql(dim) is None
            assert retrieval.build_ann_sql(retrieval._ANN_SEMANTIC_TEMPLATE, dim) is None
            assert explore._ann_sql("seed_chunk", explore._ANN_SEED_CHUNK_TEMPLATE, dim) is None

    def test_only_indexed_dimensions_are_allowed(self):
        assert retrieval.ANN_DIMENSIONS == {256, 384, 512, 768, 1024, 1536}
        assert 3072 not in retrieval.ANN_DIMENSIONS

    def test_statements_are_built_once_per_dimension(self):
        assert retrieval.ann_semantic_sql(1536) is retrieval.ann_semantic_sql(1536)
        assert retrieval.ann_semantic_sql(768) is not retrieval.ann_semantic_sql(1536)

    def test_non_integer_dimensions_cannot_reach_the_sql(self):
        """The allowlist is the injection guard - the dimension is interpolated
        because it is part of a TYPE and cannot be a bind parameter."""
        for hostile in ("1536); drop table chunks --", "1536", 1536.0, True):
            assert retrieval.ann_semantic_sql(hostile) is None


class TestCapabilityProbeSql:
    """TEXT-LEVEL checks on the probe statement - nothing here runs any SQL.

    These cannot prove the catalog query returns the right rows; only a live
    server can, and whether the planner then picks the index belongs in a
    verify_* harness. What they CAN pin is that the statement still asks the
    questions that make an index NAME trustworthy. The probe used to trust the
    name alone, so a `chunks_embedding_hnsw_1536_idx` sitting on a DIFFERENT
    table, built under a different access method, or built on a different
    operator class would have opened the ANN path onto an index the planner
    cannot use - slower than the exact scan it replaced (the rewritten SQL also
    pays a per-row cast), and with the wrong opclass a different ranking.
    """

    PROBE = " ".join(str(retrieval._CAPABILITY_SQL).split())

    def test_probe_text_joins_the_index_catalogs(self):
        for catalog in ("pg_class", "pg_namespace", "pg_index", "pg_am", "pg_opclass"):
            assert catalog in self.PROBE
        assert "JOIN pg_index i ON i.indexrelid = c.oid" in self.PROBE
        assert "JOIN pg_am am ON am.oid = c.relam" in self.PROBE
        # indclass is an oidvector, which is subscripted from 0 - [1] would
        # read the SECOND key column and match nothing on a one-column index
        assert "JOIN pg_opclass op ON op.oid = i.indclass[0]" in self.PROBE

    def test_probe_text_still_requires_indisvalid(self):
        # a failed CREATE INDEX CONCURRENTLY leaves an index that is never used
        # for reads but IS maintained on writes: treat it as absent
        assert "i.indisvalid" in self.PROBE

    def test_probe_text_pins_the_table(self):
        # a same-named index on another table is not an index on chunks
        assert "i.indrelid = to_regclass('public.chunks')" in self.PROBE
        # to_regclass returns NULL instead of raising when the table is absent,
        # so the comparison yields no rows rather than failing the statement
        assert "i.indrelid = 'public.chunks'::regclass" not in self.PROBE

    def test_probe_text_pins_the_access_method_and_the_opclass(self):
        assert "am.amname = 'hnsw'" in self.PROBE
        assert "op.opcname = 'vector_cosine_ops'" in self.PROBE
        # unqualified catalog names on purpose: pg_am has no schema, and an
        # opclass name is schema-independent, so neither check breaks when
        # pgvector lives in `extensions` rather than `public`
        assert "extensions." not in self.PROBE

    def test_probe_text_is_still_one_cheap_statement(self):
        # one round trip answers all three questions, and it stays a single
        # statement so the SAVEPOINT around it covers the whole probe
        assert ";" not in self.PROBE
        assert _bind_params(self.PROBE) == set()
        assert "extversion" in self.PROBE
        assert "reltuples" in self.PROBE
        assert retrieval.ANN_INDEX_PREFIX in self.PROBE

    def test_dimensions_are_still_read_from_the_name(self):
        """The SQL does the structural filtering; the name carries the dim."""
        names = [
            "chunks_embedding_hnsw_768_idx",
            "chunks_embedding_hnsw_99_idx",     # not an allowlisted dimension
            "chunks_embedding_hnsw_idx",        # no dimension at all
        ]
        assert retrieval._indexed_dimensions(names) == {768}


class TestCapabilityProbe:
    def test_parses_version_and_index_names(self):
        db = _FakeSession(
            vector_version="0.8.1",
            indexes=[
                "chunks_embedding_hnsw_768_idx",
                "chunks_embedding_hnsw_1536_idx",
                "chunks_embedding_hnsw_3072_idx",   # not allowlisted - ignored
                "chunks_embedding_hnsw_bogus_idx",  # unparseable - ignored
            ],
        )
        cap = retrieval.ann_capability(db)
        assert cap.pgvector == (0, 8, 1)
        assert cap.dimensions == {768, 1536}
        assert cap.total_chunks == 1_000_000.0

    def test_probe_result_is_cached(self):
        db = _FakeSession()
        retrieval.ann_capability(db)
        retrieval.ann_capability(db)
        assert len(db.core_statements) == 1

    def test_probe_failure_reports_no_ann(self):
        db = _FakeSession(probe_raises=True)
        assert retrieval.ann_capability(db) is retrieval.NO_ANN

    def test_missing_pgvector_reports_no_ann(self):
        db = _FakeSession(vector_version=None, indexes=[])
        cap = retrieval.ann_capability(db)
        assert cap.pgvector == (0, 0, 0)
        assert cap.dimensions == frozenset()


class TestGateFailsClosed:
    """Every closed gate must run the ORIGINAL statement object and issue
    exactly the two statements retrieve() issues today."""

    def _assert_exact_path(self, db, project):
        _retrieve(db, project)
        assert len(db.statements) == 2  # semantic + lexical, nothing extra
        assert _semantic_statement(db) is retrieval.SEMANTIC_SQL
        assert db.statements[-1] is retrieval.LEXICAL_SQL

    def test_session_without_a_core_connection(self):
        # This is what every pre-existing test fake looks like: the gate must
        # close without consuming a statement.
        db = _FakeSession(capable=False)
        self._assert_exact_path(db, _project())
        assert db.rollbacks == 0

    def test_probe_error(self):
        self._assert_exact_path(_FakeSession(probe_raises=True), _project())

    def test_kill_switch_off(self, monkeypatch):
        monkeypatch.setattr(retrieval.settings, "vector_ann_enabled", False)
        db = _FakeSession()
        self._assert_exact_path(db, _project())
        assert db.core_statements == []  # not even probed

    def test_old_pgvector(self):
        # hnsw.iterative_scan does not exist before 0.8.0, and without it a
        # post-filtered scan silently returns too few rows.
        self._assert_exact_path(_FakeSession(vector_version="0.7.4"), _project())

    def test_index_missing_entirely(self):
        self._assert_exact_path(_FakeSession(indexes=[]), _project())

    def test_index_for_a_different_dimension(self):
        db = _FakeSession(indexes=["chunks_embedding_hnsw_768_idx"])
        self._assert_exact_path(db, _project(dimensions=1536))

    def test_invalid_index_is_treated_as_absent(self):
        # The probe filters on indisvalid, so a half-built index never appears
        # in the list at all - modelled here as an empty result.
        self._assert_exact_path(_FakeSession(indexes=[]), _project())

    def test_dimension_off_the_allowlist(self):
        db = _FakeSession(indexes=["chunks_embedding_hnsw_1536_idx"])
        self._assert_exact_path(db, _project(dimensions=3072))
        assert db.core_statements == []  # closed before any DB work

    def test_project_too_small(self, monkeypatch):
        monkeypatch.setattr(retrieval.settings, "vector_ann_min_chunks", 20000)
        db = _FakeSession(project_chunks=19_999, total_chunks=20_000.0)
        self._assert_exact_path(db, _project())

    def test_project_share_too_small(self, monkeypatch):
        monkeypatch.setattr(retrieval.settings, "vector_ann_min_chunks", 20000)
        monkeypatch.setattr(retrieval.settings, "vector_ann_min_project_share", 0.02)
        # 25k chunks is big in absolute terms but 0.25% of a 10M-row table:
        # an HNSW post-filter would burn its whole budget on other tenants.
        db = _FakeSession(project_chunks=25_000, total_chunks=10_000_000.0)
        self._assert_exact_path(db, _project())

    def test_unanalyzed_table(self):
        # pg_class.reltuples is -1 until the table is analyzed; an unknown
        # denominator means the share gate cannot be evaluated.
        self._assert_exact_path(_FakeSession(total_chunks=-1.0), _project())

    def test_size_query_failure(self, monkeypatch):
        # An unanswerable size question means 0, which closes the size gate.
        monkeypatch.setattr(retrieval, "_project_chunk_count", lambda d, p: 0)
        self._assert_exact_path(_FakeSession(), _project())


class TestGateOpens:
    def _open(self, monkeypatch):
        monkeypatch.setattr(retrieval.settings, "vector_ann_enabled", True)
        monkeypatch.setattr(retrieval.settings, "vector_ann_min_chunks", 20000)
        monkeypatch.setattr(retrieval.settings, "vector_ann_min_project_share", 0.02)
        return _FakeSession(project_chunks=200_000, total_chunks=1_000_000.0)

    def test_large_dominant_project_uses_the_ann_sibling(self, monkeypatch):
        db = self._open(monkeypatch)
        project = _project()
        rows = _retrieve(db, project)

        semantic = _semantic_statement(db)
        assert semantic is not retrieval.SEMANTIC_SQL
        assert semantic is retrieval.ann_semantic_sql(1536)
        # the lexical half is never rewritten: it ranks by ts_rank_cd
        assert db.statements[-1] is retrieval.LEXICAL_SQL
        # ...and the rows still look exactly like the exact path's rows
        assert rows and "similarity" in rows[0] and "id" not in rows[0]

    def test_scan_settings_are_transaction_local(self, monkeypatch):
        db = self._open(monkeypatch)
        _retrieve(db, _project())
        gucs = [s for s in db.statements if "set_config" in str(s)]
        assert len(gucs) == 1
        sql = str(gucs[0])
        # the third argument to set_config is is_local => SET LOCAL, so the
        # setting cannot leak onto the next request that borrows this
        # connection from the pool
        assert sql.count(", true)") == 3
        for guc in ("hnsw.iterative_scan", "hnsw.ef_search", "hnsw.max_scan_tuples"):
            assert guc in sql
        # values are bound, never interpolated
        assert ":mode" in sql and ":ef_search" in sql and ":max_scan_tuples" in sql

    def test_settings_failure_falls_back_to_exact(self, monkeypatch):
        db = self._open(monkeypatch)
        monkeypatch.setattr(retrieval, "apply_ann_gucs", lambda db_: False)
        _retrieve(db, _project())
        assert _semantic_statement(db) is retrieval.SEMANTIC_SQL

    def test_ann_plan_returns_none_when_settings_cannot_be_applied(self, monkeypatch):
        db = self._open(monkeypatch)
        monkeypatch.setattr(retrieval, "apply_ann_gucs", lambda db_: False)
        assert retrieval.ann_plan(db, _project()) is None

    def test_gucs_failure_rolls_back(self, monkeypatch):
        db = self._open(monkeypatch)

        def _boom(statement, params=None):
            if "set_config" in str(statement):
                raise RuntimeError("unrecognized configuration parameter")
            return _Rows([])

        monkeypatch.setattr(db, "execute", _boom)
        assert retrieval.apply_ann_gucs(db) is False
        # SAVEPOINT, not a full rollback. A failed statement aborts the whole
        # transaction, so this has to be undone somehow - but db.rollback()
        # would also discard the caller's uncommitted work, and by this point
        # the /v1 routers have already added the request's UsageEvent
        # (routers/rag_v1.py:78). Rolling that back silently drops the billing
        # record for the request.
        assert db.savepoint_rollbacks == 1
        assert db.rollbacks == 0, "the caller's uncommitted writes were discarded"

    def test_project_size_is_memoized_on_content_version(self, monkeypatch):
        db = self._open(monkeypatch)
        project = _project()
        retrieval.ann_dimension(db, project)
        retrieval.ann_dimension(db, project)
        size_queries = [s for s in db.core_statements if "sum(chunk_count)" in str(s)]
        assert len(size_queries) == 1
        # a content write bumps the version, which invalidates the memo
        project.content_version = 8
        retrieval.ann_dimension(db, project)
        size_queries = [s for s in db.core_statements if "sum(chunk_count)" in str(s)]
        assert len(size_queries) == 2


class TestExploreGate:
    def test_exact_statements_by_default(self):
        db = _FakeSession(capable=False)
        project = _project()
        explore._neighbours(db, project, "chunk:1", 4, None)
        assert db.statements[0] is explore._CHUNK_REL_CHUNK_SQL
        assert db.statements[1] is explore._CHUNK_REL_MEMORY_SQL

        db = _FakeSession(capable=False)
        explore._neighbours(db, project, "memory:1", 4, None)
        assert db.statements[0] is explore._MEMORY_REL_CHUNK_SQL
        assert db.statements[1] is explore._MEMORY_REL_MEMORY_SQL

    def test_only_chunk_targets_are_rewritten(self):
        db = _FakeSession()
        project = _project()
        explore._neighbours(db, project, "chunk:1", 4, 1536)
        assert db.statements[0] is not explore._CHUNK_REL_CHUNK_SQL
        # memories have no HNSW index, so that half is untouched
        assert db.statements[1] is explore._CHUNK_REL_MEMORY_SQL

        db = _FakeSession()
        explore._neighbours(db, project, "memory:1", 4, 1536)
        assert db.statements[0] is not explore._MEMORY_REL_CHUNK_SQL
        assert db.statements[1] is explore._MEMORY_REL_MEMORY_SQL

    def test_statements_are_built_once(self):
        first = explore._ann_sql("seed_chunk", explore._ANN_SEED_CHUNK_TEMPLATE, 384)
        second = explore._ann_sql("seed_chunk", explore._ANN_SEED_CHUNK_TEMPLATE, 384)
        assert first is second


class TestExactStatementsAreUntouched:
    """The exact SQL is the fallback for every gate above, so it must not have
    drifted while the ANN siblings were added."""

    def test_semantic_sql(self):
        sql = " ".join(str(retrieval.SEMANTIC_SQL).split())
        assert sql == (
            "SELECT c.id, c.content, c.page_number, c.chunk_index, f.filename, "
            "1 - (c.embedding <=> CAST(:qvec AS vector)) AS similarity "
            "FROM chunks c JOIN files f ON f.id = c.file_id "
            "WHERE c.project_id = :project_id "
            "ORDER BY c.embedding <=> CAST(:qvec AS vector) LIMIT :limit"
        )

    def test_memories_stay_exact(self):
        from app.services import memory

        sql = str(memory._SEARCH_SQL)
        assert "::vector(" not in sql
        assert "vector_dims" not in sql

    def test_semantic_cache_stays_exact(self):
        from app.services import semantic_cache

        sql = str(semantic_cache._LOOKUP_SQL)
        assert "::vector(" not in sql
        assert "vector_dims" not in sql

    def test_memory_graph_stays_exact(self):
        from app.services import memory_graph

        for statement in (
            memory_graph.RELATED_SQL,
            memory_graph.MEMORY_CHUNK_SQL,
            memory_graph.MEMORY_MEMORY_SQL,
        ):
            assert "::vector(" not in str(statement)


class TestMigrationIsDefensive:
    """The database is unreachable, so 0018 cannot be test-run. These are the
    properties that make a blind paste into a SQL editor survivable."""

    @staticmethod
    def _sql():
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "supabase"
            / "migrations"
            / "0018_hnsw_vector_indexes.sql"
        )
        return path.read_text(encoding="utf-8")

    @classmethod
    def _executable(cls):
        """The migration with comments and string literals removed.

        Both carry prose that names the very statements these tests assert are
        absent (the runbook, and the NOTICE that points an operator at it), so
        searching the raw file would test the documentation, not the SQL.
        """
        body = re.sub(r"--.*$", "", cls._sql(), flags=re.M)
        return re.sub(r"'[^']*'", "''", body)

    def test_every_index_is_idempotent(self):
        statements = re.findall(r"create index[^;]*", self._executable(), re.I)
        assert len(statements) >= 2  # the two semantic_query_cache btrees
        for statement in statements:
            assert "if not exists" in statement.lower()

    def test_nothing_raises_an_exception(self):
        # RAISE NOTICE only: a guard that fails must not abort the migration.
        body = self._executable()
        assert "raise exception" not in body.lower()
        assert "raise notice" in self._sql().lower()

    def test_concurrently_is_not_in_an_executable_statement(self):
        # CREATE INDEX CONCURRENTLY cannot run in a transaction block, and both
        # the Supabase SQL editor and the repo's migration runner impose one.
        # It belongs in the runbook comment, never in a statement.
        assert "concurrently" not in self._executable().lower()
        assert "concurrently" in self._sql().lower()  # ...but it IS documented

    def test_indexes_match_the_allowlist(self):
        sql = self._sql()
        dims = re.search(r"dims\s+constant int\[\]\s*:=\s*array\[([^\]]+)\]", sql)
        assert dims
        declared = {int(d.strip()) for d in dims.group(1).split(",")}
        assert declared == set(retrieval.ANN_DIMENSIONS)
        assert 3072 not in declared  # over pgvector's 2000-dimension HNSW limit

    def test_index_names_match_what_the_runtime_probes_for(self):
        sql = self._sql()
        assert "chunks_embedding_hnsw_%s_idx" in sql
        assert retrieval.ANN_INDEX_PREFIX in sql
        assert "vector_dims(embedding) = %s" in sql

    def test_built_indexes_match_the_structure_the_probe_demands(self):
        # The probe no longer trusts the NAME: it also requires the hnsw access
        # method and vector_cosine_ops. Text-level on both sides, but if the two
        # ever disagree the gate silently never opens, which no other test here
        # would notice. (Read from the raw file: _executable() blanks string
        # literals, and these CREATE INDEXes are built inside format() strings.)
        sql = self._sql()
        assert (
            "on public.chunks using hnsw ((embedding::vector(%s)) vector_cosine_ops)"
            in sql
        )
        probe = " ".join(str(retrieval._CAPABILITY_SQL).split())
        assert "am.amname = 'hnsw'" in probe
        assert "op.opcname = 'vector_cosine_ops'" in probe

    def test_semantic_query_cache_gets_btrees_not_hnsw(self):
        body = self._executable()
        assert "semantic_query_cache_scope_idx" in body
        assert "semantic_query_cache_expiry_idx" in body
        assert not re.search(
            r"create index[^;]*semantic_query_cache[^;]*using hnsw", body, re.I
        )

    def test_no_index_on_memories(self):
        assert not re.search(
            r"create index[^;]*\bon\s+\S*memories", self._executable(), re.I
        )

    def test_a_cancelled_build_stops_the_block_it_is_in(self):
        """A caught query_canceled leaves NO armed statement_timeout behind.

        statement_timeout is armed once per top-level protocol message; when it
        fires, ProcessInterrupts consumes it, and PL/pgSQL catching the 57014
        does not re-arm anything until the next message. So any later build in
        the same DO block runs UNBOUNDED - and both of these hold a ShareLock on
        a table the running system writes to (the ingest queue, the cache
        sweep). The operator Ctrl-C meant to stop that would be swallowed by the
        same handler. Both blocks therefore stop on a cancel.
        """
        blocks = re.findall(r"do \$\$(.*?)\$\$;", self._executable(), re.S | re.I)
        assert len(blocks) == 2  # chunks HNSW, then the two cache btrees
        for block in blocks:
            assert "when query_canceled then" in block
            assert "cancelled := true" in block
            # ...and the stop itself is a plain statement in the block body, not
            # something the handler has to get right: exit for the loop, return
            # for the straight-line block.
            assert re.search(r"exit when cancelled|if cancelled then", block), block


class TestTheMigrationRunnerSurfacesNotices:
    """0018 is written so that NOTHING raises: every skipped index degrades to a
    RAISE NOTICE naming what was skipped and pointing at the runbook. psycopg3
    installs its own notice processor over libpq's stderr default, and that one
    DISCARDS every notice while no handler is registered - so a runner that
    registers none turns the whole design into a silent success, printing
    "applied 0018..." and "OK" for a run that created zero indexes."""

    @staticmethod
    def _source():
        from pathlib import Path

        return (Path(__file__).resolve().parent / "apply_migrations.py").read_text(
            encoding="utf-8"
        )

    @staticmethod
    def _tree(source):
        import ast

        return ast.parse(source)

    def test_a_notice_handler_is_registered_on_the_connection(self):
        import ast

        calls = [
            node
            for node in ast.walk(self._tree(self._source()))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_notice_handler"
        ]
        assert len(calls) == 1
        owner = calls[0].func.value
        assert isinstance(owner, ast.Name) and owner.id == "conn"

    def test_the_handler_prints_the_severity_and_the_message(self, capsys):
        # exec the handler alone: importing the module would try to connect.
        import ast

        source = self._source()
        fn = next(
            node
            for node in self._tree(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "print_notice"
        )
        scope: dict = {"current_file": ["0018_hnsw_vector_indexes.sql"], "notices": []}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<handler>", "exec"), scope)

        class _Diagnostic:
            severity_nonlocalized = "NOTICE"
            severity = "NOTICE"
            message_primary = (
                "0018: public.semantic_query_cache does not exist "
                "(migration 0010 has not been applied here); no cache index created."
            )

        scope["print_notice"](_Diagnostic())

        printed = capsys.readouterr().out
        assert "no cache index created" in printed  # the operator can see it...
        assert "NOTICE" in printed
        assert "0018_hnsw_vector_indexes.sql" in printed  # ...and which file said so
        assert len(scope["notices"]) == 1  # counted, so the OK line can say so


class TestMemoryChunkAnn:
    """The pieces of long memories route onto their own HNSW indexes.

    Same gate, same thresholds, same fail-closed rule as document chunks - but
    on memory_chunks' OWN row counts and memory_chunks' OWN indexes. The bug
    this guards against is subtle and silent: borrow the document side's
    numbers and a project with a million document chunks would route its memory
    search onto an index that does not exist, and the planner would fall back
    to a seq scan that now ALSO pays a cast per row - strictly slower than the
    exact query it replaced, while still returning correct rows.
    """

    def test_ann_sql_lines_up_with_the_index(self):
        """The three textual conditions. Miss any one and the index is ignored
        silently - correct rows, worse performance, no signal anywhere."""
        from app.services import memory

        stmt = memory._ann_search_sql(1536)
        sql = " ".join(str(stmt).split())
        # ORDER BY operand is TEXTUALLY the index expression...
        assert (
            "ORDER BY embedding::vector(1536) <=> CAST(:qvec AS vector(1536))" in sql
        )
        # ...the WHERE repeats the index predicate verbatim...
        assert "vector_dims(embedding) = 1536" in sql
        # ...and the ANN scan is pinned as its own node so the outer GROUP BY
        # cannot be pushed under the LIMIT.
        assert "MATERIALIZED" in sql

    def test_parents_branch_is_never_limited(self):
        """What makes the piece LIMIT safe. Every memory stays a candidate via
        its own vector, so a piece outside the limit costs that memory its
        piece-level boost - never its findability. Limit both branches and the
        query silently becomes lossy."""
        from app.services import memory

        sql = " ".join(str(memory._ann_search_sql(1536)).split())
        parents = sql.split("UNION ALL")[0].split("FROM memories")[1]
        assert "LIMIT" not in parents.upper()

    def test_unknown_dimension_gets_no_ann_sql(self):
        """3072 has no HNSW index (pgvector's limit is 2000 dims) and must not
        render one. build_ann_sql's allowlist is the injection guard too."""
        from app.services import memory

        assert memory._ann_search_sql(3072) is None
        assert memory._ann_search_sql(999) is None

    def test_oversample_is_derived_not_hardcoded(self):
        """top_k distinct memories must still be reachable when the nearest
        pieces all belong to one long memory."""
        from app.services.memory import (
            MAX_PIECES_PER_MEMORY,
            MEMORY_CHUNK_OVERLAP,
            MEMORY_CHUNK_SIZE,
        )

        assert MAX_PIECES_PER_MEMORY == -(
            -8000 // (MEMORY_CHUNK_SIZE - MEMORY_CHUNK_OVERLAP)
        )
        assert MAX_PIECES_PER_MEMORY > 1

    def test_gate_uses_memory_counts_not_document_counts(self):
        """A project huge in documents but tiny in memories must stay exact."""
        from app.services import retrieval

        db = _FakeSession(project_chunks=5_000_000, project_memory_chunks=12)
        assert retrieval.memory_ann_dimension(db, _project()) is None

    def test_gate_opens_on_memory_counts_alone(self):
        """...and the mirror image: tiny in documents, huge in memory pieces."""
        from app.services import retrieval

        db = _FakeSession(project_chunks=3, project_memory_chunks=200_000)
        assert retrieval.memory_ann_dimension(db, _project()) == 1536

    def test_missing_memory_index_closes_the_gate(self):
        """Document indexes existing says NOTHING about memory_chunks."""
        from app.services import retrieval

        db = _FakeSession(memory_indexes=[])
        assert retrieval.memory_ann_dimension(db, _project()) is None
        # ...while the document gate is unaffected, proving they are independent
        assert retrieval.ann_dimension(db, _project()) == 1536

    def test_unanalyzed_memory_table_closes_the_gate(self):
        """reltuples is -1 until ANALYZE runs. Unknown must never read as
        'small enough to be a safe share'."""
        from app.services import retrieval

        db = _FakeSession(total_memory_chunks=-1.0)
        assert retrieval.memory_ann_dimension(db, _project()) is None

    def test_small_share_closes_the_gate(self):
        """Post-filter recall depends on the project's SHARE of the table."""
        from app.services import retrieval

        db = _FakeSession(
            total_memory_chunks=100_000_000.0, project_memory_chunks=25_000
        )
        assert retrieval.memory_ann_dimension(db, _project()) is None

    def test_old_pgvector_closes_the_gate(self):
        """Without hnsw.iterative_scan a post-filtered scan stops after
        ef_search candidates and returns however few survived the project
        filter - worse than not using the index at all."""
        from app.services import retrieval

        db = _FakeSession(vector_version="0.7.4")
        assert retrieval.memory_ann_dimension(db, _project()) is None

    def test_capability_defaults_report_no_memory_ann(self):
        """An AnnCapability built without the memory fields must not inherit
        the document answer."""
        from app.services.retrieval import AnnCapability

        cap = AnnCapability(
            pgvector=(0, 8, 1),
            dimensions=frozenset({1536}),
            total_chunks=1_000_000.0,
        )
        assert cap.memory_dimensions == frozenset()
        assert cap.total_memory_chunks == 0.0


class TestMemorySearchRouting:
    """search_memories must actually SWITCH statements, and fall back on any
    failure. The gate returning a dimension is not the same as the query using
    it, and a gate that opens onto an un-tuned scan is worse than one that
    never opened."""

    @staticmethod
    def _project():
        p = _project()
        p.embedding_provider = "openai"
        p.embedding_model = "text-embedding-3-small"
        return p

    class _DB(_FakeSession):
        def __init__(self, gucs_ok=True, **kw):
            super().__init__(**kw)
            self.gucs_ok = gucs_ok
            self.executed = []

        def execute(self, statement, params=None):
            sql = str(statement)
            if "set_config" in sql and not self.gucs_ok:
                raise RuntimeError("cannot set hnsw gucs")
            if "MAX(similarity)" in sql:
                self.executed.append((sql, params or {}))
                return _Rows([])
            return super().execute(statement, params)

        def scalars(self, stmt):
            return _Rows([])

    def _run(self, db):
        from app.services import memory

        memory.search_memories(
            db, self._project(), "q", 5, embed_fn=lambda _q: [0.1] * 1536
        )
        assert db.executed, "the search statement never ran"
        return db.executed[0]

    def test_open_gate_uses_the_ann_statement(self):
        sql, params = self._run(self._DB(project_memory_chunks=200_000))
        assert "vector_dims(embedding) = 1536" in sql
        # oversampled so top_k distinct memories survive the GROUP BY even when
        # the nearest pieces all belong to one long memory
        from app.services.memory import MAX_PIECES_PER_MEMORY

        assert params["piece_limit"] == 5 * MAX_PIECES_PER_MEMORY

    def test_closed_gate_uses_the_exact_statement(self):
        sql, params = self._run(self._DB(project_memory_chunks=12))
        assert "vector_dims" not in sql
        assert "piece_limit" not in params

    def test_failed_gucs_fall_back_to_exact(self):
        """The gate opened, but the scan could not be tuned. Running ANN anyway
        would post-filter by project_id and stop after ef_search candidates,
        returning however few survived - silently fewer memories, no error."""
        sql, _ = self._run(self._DB(project_memory_chunks=200_000, gucs_ok=False))
        assert "vector_dims" not in sql
