"""Embedding spend must be attributed to the right request and the right account.

Embedding is plausibly the largest token consumer in Oreag and reported nothing
before this. The two tests that matter most are the isolation ones: embedders
are `lru_cache`d and therefore SHARED, and retrieval fans out across threads.
Getting either wrong bills one project for another's work.
"""
import threading

import pytest

from app.providers.base import TokenUsage
from app.providers.registry import embedding_cost_for
from app.services import embedding_usage


class TestScope:
    def test_records_inside_a_scope(self):
        with embedding_usage.scope() as acc:
            embedding_usage.record("text-embedding-3-small", 120)
            embedding_usage.record("text-embedding-3-small", 80)
        assert acc.by_model == {"text-embedding-3-small": 200}
        assert acc.total == TokenUsage(200, 0, "text-embedding-3-small")

    def test_outside_a_scope_is_a_silent_no_op(self):
        """An embedder used by a script or a migration must not blow up."""
        embedding_usage.record("m", 10)  # must not raise
        assert embedding_usage.current() is None

    def test_unreported_usage_is_counted_but_not_invented(self):
        """Local models report nothing. That is a disclosed gap, not a zero."""
        with embedding_usage.scope() as acc:
            embedding_usage.record("nomic-embed-text", None)
            embedding_usage.record("nomic-embed-text", None)
        assert acc.calls == 2
        assert acc.unmeasured_calls == 2
        assert acc.total.known is False

    def test_completion_side_is_a_real_zero(self):
        """An embedding produces a vector, not text: 0 is measured, not absent."""
        with embedding_usage.scope() as acc:
            embedding_usage.record("m", 5)
        assert acc.total.completion_tokens == 0
        assert acc.total.known is True

    def test_nesting_restores_the_outer_tally(self):
        with embedding_usage.scope() as outer:
            embedding_usage.record("m", 10)
            with embedding_usage.scope() as inner:
                embedding_usage.record("m", 999)
            embedding_usage.record("m", 5)
        assert inner.by_model == {"m": 999}
        assert outer.by_model == {"m": 15}, "inner scope leaked into outer"


class TestIsolation:
    """The bug that would matter: shared embedder instances billing the wrong
    project. `get_embedder` is lru_cached, so state must live in the CALLER."""

    def test_two_scopes_do_not_see_each_other(self):
        with embedding_usage.scope() as a:
            embedding_usage.record("m", 100)
        with embedding_usage.scope() as b:
            embedding_usage.record("m", 7)
        assert a.by_model == {"m": 100}
        assert b.by_model == {"m": 7}

    def test_concurrent_threads_accumulate_separately(self):
        """Two simultaneous requests must not merge their bills."""
        results = {}
        barrier = threading.Barrier(2)

        def work(name, tokens):
            with embedding_usage.scope() as acc:
                barrier.wait()          # force real overlap
                embedding_usage.record("m", tokens)
                results[name] = acc.by_model

        threads = [
            threading.Thread(target=work, args=("a", 10)),
            threading.Thread(target=work, args=("b", 500)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results == {"a": {"m": 10}, "b": {"m": 500}}


class TestThreadBoundary:
    """Retrieval runs inside a ThreadPoolExecutor, which does NOT carry
    ContextVars. Without adopt(), every embedding call made during a streamed
    query would be silently dropped."""

    def test_worker_thread_sees_nothing_without_adopt(self):
        from concurrent.futures import ThreadPoolExecutor

        with embedding_usage.scope() as acc:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(embedding_usage.record, "m", 42).result()
        assert acc.by_model == {}, "context unexpectedly crossed the boundary"

    def test_adopt_reenters_the_callers_accumulator(self):
        from concurrent.futures import ThreadPoolExecutor

        def work(acc):
            with embedding_usage.adopt(acc):
                embedding_usage.record("m", 42)

        with embedding_usage.scope() as acc:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(work, acc).result()
        assert acc.by_model == {"m": 42}

    def test_adopt_of_none_is_harmless(self):
        with embedding_usage.adopt(None):
            embedding_usage.record("m", 1)  # must not raise


class TestPricing:
    def test_priced_model(self):
        assert embedding_cost_for("text-embedding-3-small", 1_000_000) == 0.02

    def test_unpriced_model_is_null_not_zero(self):
        """A local embedder costs no dollars, but a measured $0.00 would be
        indistinguishable from a price we simply do not have."""
        assert embedding_cost_for("nomic-embed-text", 5_000) is None

    def test_unmeasured_is_null(self):
        assert embedding_cost_for("text-embedding-3-small", None) is None

    def test_chat_prices_are_not_reachable_through_the_embedding_table(self):
        """Embedding tokens are 10-100x cheaper; crossing the tables would
        overcharge by orders of magnitude."""
        assert embedding_cost_for("gpt-4o-mini", 1_000_000) is None


@pytest.fixture()
def db():
    """A local SQLite session - the report tests build the same one, but this
    module only needs the two tables record_usage touches."""
    import sqlalchemy as sa
    from sqlalchemy import BigInteger
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import Session

    from app.models import Base, Project, UsageEvent

    @compiles(BigInteger, "sqlite")
    def _bigint_as_integer(type_, compiler, **kw):
        # SQLite autoincrement needs INTEGER PRIMARY KEY, not BIGINT.
        return "INTEGER"

    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool,
                              connect_args={"check_same_thread": False})
    Base.metadata.create_all(
        engine, tables=[Project.__table__, UsageEvent.__table__])
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


class TestRecordUsagePersistsIt:
    def test_defaults_to_the_request_scope(self, db):
        """A route should not have to remember to pass it."""
        import uuid

        from app.models import Project, UsageEvent
        from app.services.usage import record_usage

        project = Project(
            id=uuid.uuid4(), owner_id=uuid.uuid4(), name="p",
            llm_provider="openai", llm_model="gpt-4o-mini",
            embedding_provider="openai", embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
        )
        db.add(project)
        db.commit()

        with embedding_usage.scope():
            embedding_usage.record("text-embedding-3-small", 1_000_000)
            record_usage(db, project=project, api_key_id=None,
                         endpoint="files_upload")

        row = db.query(UsageEvent).one()
        assert row.embedding_tokens == 1_000_000
        assert row.embedding_model == "text-embedding-3-small"
        assert float(row.embedding_cost_usd) == pytest.approx(0.02)
        # The LLM side stays NULL: an upload calls no chat model, and 0 would
        # claim a measurement that never happened.
        assert row.prompt_tokens is None and row.cost_usd is None
