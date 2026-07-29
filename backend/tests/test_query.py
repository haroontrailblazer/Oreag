"""Integration tests for run_query - the shared /v1 + playground entry point -
now driven by the agentic retrieval loop.

These use a fake DB and monkeypatched retrieval/generation so no network or
Postgres is touched, mirroring the style of tests/test_units.py.
"""
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.models import Project


def _project():
    return Project(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        top_k=5,
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
    )


class FakeDB:
    """Returns preset scalar() values in order; records add()/commit()."""

    def __init__(self, scalars):
        self._scalars = list(scalars)
        self.added = []
        self.committed = False
        self.rollbacks = 0

    def scalar(self, *args, **kwargs):
        return self._scalars.pop(0) if self._scalars else 0

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rollbacks += 1


class TestQueryResponseSchema:
    def test_loop_fields_have_backward_compatible_defaults(self):
        from app.schemas import QueryResponse

        resp = QueryResponse(answer="a", sources=[], model="m", latency_ms=1)
        assert resp.depth == "short"
        assert resp.sub_queries == []
        assert resp.needs_clarification is False
        assert resp.clarification_questions == []
        assert resp.conversation_id is None

    def test_request_accepts_optional_conversation_id(self):
        from app.schemas import QueryRequest

        assert QueryRequest(question="hi").conversation_id is None
        assert QueryRequest(question="hi", conversation_id="c1").conversation_id == "c1"


def _src(content, similarity, chunk_index=0):
    return {
        "filename": "a.pdf",
        "page_number": 1,
        "chunk_index": chunk_index,
        "content": content,
        "similarity": similarity,
    }


class TestRunQueryWiring:
    def test_strong_retrieval_returns_grounded_answer(self, monkeypatch):
        from app.services import query

        gen = []
        monkeypatch.setattr(
            query.retrieval, "retrieve",
            lambda db, p, q, k, **kw:[_src("alpha", 0.9, 0), _src("beta", 0.8, 1)],
        )
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k, **kw:[]
        )

        def fake_generate(db, p, question, sources, depth="short", **kw):
            gen.append((question, depth, len(sources)))
            return "GROUNDED ANSWER"

        monkeypatch.setattr(query.generation, "generate_answer", fake_generate)

        resp = query.run_query(
            FakeDB([10, 0]), _project(), "what is X", None, api_key_id=None
        )

        assert resp.needs_clarification is False
        assert resp.answer == "GROUNDED ANSWER"
        assert resp.depth == "short"
        assert resp.sub_queries == ["what is X"]
        assert len(resp.sources) == 2
        assert gen and gen[0][1] == "short"  # depth threaded into generation

    def test_memory_blend_failure_answers_from_documents(self, monkeypatch):
        """A stale-dimension memory vector (from a pre-fix model switch) aborts
        pgvector with "different vector dimensions"; blending must be skipped
        and the transaction rolled back - never a 500 for the whole query."""
        from app.services import query

        monkeypatch.setattr(
            query.retrieval, "retrieve",
            lambda db, p, q, k, **kw:[_src("alpha", 0.9, 0), _src("beta", 0.8, 1)],
        )

        def exploding_search(db, p, q, k, **kw):
            raise RuntimeError("different vector dimensions 1536 and 768")

        monkeypatch.setattr(query.memory_service, "search_memories", exploding_search)
        monkeypatch.setattr(query.settings, "rag_memory_blend_k", 3)
        monkeypatch.setattr(
            query.generation, "generate_answer",
            lambda db, p, question, sources, depth="short", **kw: "DOCS ONLY",
        )

        db = FakeDB([10, 3])  # chunks present AND embedded memories present
        resp = query.run_query(db, _project(), "what is X", None, api_key_id=None)

        assert resp.answer == "DOCS ONLY"
        assert all(s.filename != "memory" for s in resp.sources)
        assert db.rollbacks >= 1  # the aborted transaction was cleaned up

    def test_weak_retrieval_escalates_to_human(self, monkeypatch):
        from app.services import query

        gen_calls = []
        monkeypatch.setattr(
            query.retrieval, "retrieve", lambda db, p, q, k, **kw:[_src("noise", 0.01)]
        )
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k, **kw:[]
        )
        monkeypatch.setattr(
            query.generation, "generate_answer",
            lambda *a, **k: gen_calls.append(a) or "SHOULD NOT HAPPEN",
        )
        # plan/clarify build an LLM - feed a fake so no network is touched.
        monkeypatch.setattr(query.resolver, "resolve_llm_key", lambda db, p: "k")

        class FakeLLM:
            model = "fake/llm"

            def generate(self, system, user):
                return "Which topic?\nWhich chapter?"

        monkeypatch.setattr(query, "get_llm", lambda *a, **k: FakeLLM())

        resp = query.run_query(
            FakeDB([10, 0]), _project(), "what is X", None, api_key_id=None
        )

        assert resp.needs_clarification is True
        assert resp.clarification_questions == ["Which topic?", "Which chapter?"]
        assert "- Which topic?" in resp.answer
        assert gen_calls == []  # never fabricated an answer

    def test_empty_project_raises_409(self):
        from fastapi import HTTPException

        from app.services import query

        with pytest.raises(HTTPException) as exc:
            query.run_query(
                FakeDB([0, 0]), _project(), "what is X", None, api_key_id=None
            )
        assert exc.value.status_code == 409


class TestSemanticCacheWiring:
    """run_query consults the semantic (L2) cache before computing, and
    remembers fresh answers - the layer every surface (playground, /v1, MCP)
    goes through."""

    def test_similar_question_served_without_touching_the_llm(self, monkeypatch):
        from app.services import query
        from app.services.agentic import AgenticResult

        cached = AgenticResult(
            answer="SEMANTIC HIT",
            sources=[],
            depth="short",
            sub_queries=[],
            rounds=1,
            needs_clarification=False,
        )
        monkeypatch.setattr(
            query.semantic_cache, "lookup", lambda db, p, q, k, s, **kw:(cached, [0.1], 0.82)
        )
        llm_calls = []
        monkeypatch.setattr(
            query.generation,
            "generate_answer",
            lambda *a, **k: llm_calls.append(1) or "FRESH",
        )
        retrieval_calls = []
        monkeypatch.setattr(
            query.retrieval,
            "retrieve",
            lambda db, p, q, k, **kw:retrieval_calls.append(q) or [],
        )
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k, **kw:[]
        )

        resp = query.run_query(
            FakeDB([10, 0]), _project(), "explain deep learning to me", None,
            api_key_id=None,
        )
        assert resp.answer == "SEMANTIC HIT"
        assert llm_calls == []  # the LLM was never invoked
        assert retrieval_calls == []  # the main chunks table was never searched
        assert resp.cache_layer == "l2"
        assert resp.cache_similarity == 0.82

    def test_fresh_answers_are_remembered_with_the_lookup_vector(self, monkeypatch):
        from app.services import query

        monkeypatch.setattr(
            query.semantic_cache, "lookup", lambda db, p, q, k, s, **kw:(None, [0.1], None)
        )
        stored = []
        monkeypatch.setattr(
            query.semantic_cache,
            "store",
            lambda db, p, q, k, s, result, vector: stored.append(
                (vector, result.answer)
            ),
        )
        monkeypatch.setattr(
            query.retrieval, "retrieve", lambda db, p, q, k, **kw:[_src("alpha", 0.9, 0)]
        )
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k, **kw:[]
        )
        monkeypatch.setattr(
            query.generation,
            "generate_answer",
            lambda db, p, q, srcs, depth="short", **kw: "FRESH ANSWER",
        )

        resp = query.run_query(
            FakeDB([10, 0]), _project(), "a brand new semantic question", None,
            api_key_id=None,
        )
        assert resp.answer == "FRESH ANSWER"
        assert resp.cache_layer is None  # computed fresh
        # stored once, reusing the vector from lookup (no second embed call)
        assert stored == [([0.1], "FRESH ANSWER")]


class TestRunQueryStream:
    """run_query_stream yields token events then a final done event, and serves
    cache hits by streaming the stored text - same brain as run_query."""

    def test_streams_tokens_then_done(self, monkeypatch):
        from app.services import query

        monkeypatch.setattr(
            query.retrieval, "retrieve",
            lambda db, p, q, k, **kw:[_src("alpha", 0.9, 0), _src("beta", 0.8, 1)],
        )
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k, **kw:[]
        )
        monkeypatch.setattr(
            query.generation, "generate_answer_stream",
            lambda db, p, q, srcs, depth="short", **kw: iter(["Hello ", "world"]),
        )
        monkeypatch.setattr(
            query.semantic_cache, "lookup", lambda db, p, q, k, s, **kw:(None, [0.1], None)
        )
        monkeypatch.setattr(query.semantic_cache, "store", lambda *a, **k: None)
        monkeypatch.setattr(query.settings, "query_cache_enabled", False)

        events = list(
            query.run_query_stream(
                FakeDB([10, 0]), _project(), "what is X", None, api_key_id=None
            )
        )
        tokens = "".join(e["text"] for e in events if e["type"] == "token")
        done = [e for e in events if e["type"] == "done"]
        assert tokens == "Hello world"
        assert len(done) == 1
        resp = done[0]["response"]
        assert resp["answer"] == "Hello world"
        assert len(resp["sources"]) == 2
        assert resp["cache_layer"] is None

    def test_cache_hit_streams_stored_text_without_generating(self, monkeypatch):
        from app.services import query
        from app.services.agentic import AgenticResult

        cached = AgenticResult(
            answer="CACHED ANSWER", sources=[], depth="short",
            sub_queries=[], rounds=1, needs_clarification=False,
        )
        monkeypatch.setattr(
            query.semantic_cache, "lookup", lambda db, p, q, k, s, **kw:(cached, [0.1], 0.9)
        )
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k, **kw:[]
        )
        monkeypatch.setattr(query.retrieval, "retrieve", lambda *a, **kw: [])
        gen_called = []
        monkeypatch.setattr(
            query.generation, "generate_answer_stream",
            lambda *a, **k: gen_called.append(1) or iter([]),
        )
        monkeypatch.setattr(query.settings, "query_cache_enabled", False)

        events = list(query.run_query_stream(FakeDB([10, 0]), _project(), "q", None))
        tokens = "".join(e["text"] for e in events if e["type"] == "token")
        done = [e for e in events if e["type"] == "done"][0]
        assert tokens == "CACHED ANSWER"
        assert gen_called == []  # cache hit never calls the model
        assert done["response"]["cache_layer"] == "l2"
        assert done["response"]["cache_similarity"] == 0.9

    def test_empty_project_yields_error_event(self, monkeypatch):
        from app.services import query

        events = list(query.run_query_stream(FakeDB([0, 0]), _project(), "q", None))
        assert events == [
            {
                "type": "error",
                "detail": "Project has no indexed content yet - upload files (or save memories) and wait for indexing",
            }
        ]


class TestQueryCaching:
    def _wire(self, monkeypatch, gen_calls, retrieval_calls=None):
        from app.services import query

        def fake_retrieve(db, p, q, k, **kw):
            if retrieval_calls is not None:
                retrieval_calls.append(q)
            return [_src("alpha", 0.9, 0), _src("beta", 0.8, 1)]

        monkeypatch.setattr(query.retrieval, "retrieve", fake_retrieve)
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k, **kw:[]
        )

        def fake_generate(db, p, question, sources, depth="short", **kw):
            gen_calls.append(question)
            return "GROUNDED ANSWER"

        monkeypatch.setattr(query.generation, "generate_answer", fake_generate)
        return query

    def test_repeated_question_is_served_from_cache(self, monkeypatch):
        gen_calls = []
        retrieval_calls = []
        query = self._wire(monkeypatch, gen_calls, retrieval_calls)
        project = _project()

        r1 = query.run_query(FakeDB([10, 0]), project, "What is X?", None, None)
        # Same question (different spacing/case) → same cache entry.
        r2 = query.run_query(FakeDB([10, 0]), project, "what is   x?", None, None)

        assert r1.answer == r2.answer == "GROUNDED ANSWER"
        assert len(gen_calls) == 1  # the second ask did not re-run the LLM
        assert len(retrieval_calls) == 1  # ...nor search the main DB again
        assert r1.cache_layer is None  # computed fresh
        assert r2.cache_layer == "l1"  # served by the exact-match layer

    def test_query_log_records_the_cache_layer(self, monkeypatch):
        # The project-wide hit rate reads cache_layer off query_logs, so every
        # query must persist which layer served it (or None when fresh).
        from app.models import QueryLog

        gen_calls = []
        query = self._wire(monkeypatch, gen_calls)
        project = _project()

        db1 = FakeDB([10, 0])
        query.run_query(db1, project, "What is X?", None, None)
        db2 = FakeDB([10, 0])
        query.run_query(db2, project, "what is   x?", None, None)  # same entry

        logged1 = [o for o in db1.added if isinstance(o, QueryLog)]
        logged2 = [o for o in db2.added if isinstance(o, QueryLog)]
        assert logged1 and logged1[0].cache_layer is None  # fresh
        assert logged2 and logged2[0].cache_layer == "l1"  # exact-match hit

    def test_content_change_bypasses_cache(self, monkeypatch):
        gen_calls = []
        query = self._wire(monkeypatch, gen_calls)
        project = _project()

        project.content_version = 1
        query.run_query(FakeDB([10, 0]), project, "What is X?", None, None)
        # Any content write bumps content_version → new signature → fresh
        # answer, even when counts happen to stay identical (in-place edits).
        project.content_version = 2
        query.run_query(FakeDB([10, 0]), project, "What is X?", None, None)

        assert len(gen_calls) == 2


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def generate(self, system, user):
        self.calls.append((system, user))
        return self.reply


class TestConversationMemory:
    def test_first_turn_persists_and_uses_no_history(self, monkeypatch):
        from app.services import query

        monkeypatch.setattr(
            query.retrieval, "retrieve",
            lambda db, p, q, k, **kw:[_src("alpha", 0.9, 0), _src("beta", 0.8, 1)],
        )
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k, **kw:[]
        )
        monkeypatch.setattr(
            query.generation, "generate_answer", lambda *a, **k: "GROUNDED ANSWER"
        )
        # A short question with strong retrieval never needs the LLM for
        # condense/plan/clarify - so if condense ran, this fake would record it.
        llm = FakeLLM("unused")
        monkeypatch.setattr(query.resolver, "resolve_llm_key", lambda db, p: "k")
        monkeypatch.setattr(query, "get_llm", lambda *a, **k: llm)

        cid = "conv-" + uuid.uuid4().hex
        project = _project()
        resp = query.run_query(
            FakeDB([10, 0]), project, "what is X", None, None, conversation_id=cid
        )

        assert resp.answer == "GROUNDED ANSWER"
        assert resp.conversation_id == cid
        assert llm.calls == []  # no history → no condense call
        assert query._conversations.get_history(str(project.id), cid) == [
            {"question": "what is X", "answer": "GROUNDED ANSWER"}
        ]

    def test_followup_is_condensed_against_history(self, monkeypatch):
        from app.services import query

        cid = "conv-" + uuid.uuid4().hex
        project = _project()
        query._conversations.append_turn(
            str(project.id), cid, "what is deep learning",
            "Deep learning is a subfield of ML.",
        )

        seen = []
        monkeypatch.setattr(
            query.retrieval, "retrieve",
            lambda db, p, q, k, **kw:seen.append(q) or [_src("ctx", 0.9, 0)],
        )
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k, **kw:[]
        )
        monkeypatch.setattr(
            query.generation, "generate_answer", lambda *a, **k: "ANSWER"
        )
        # condense rewrites the follow-up to this standalone (short → no planning).
        monkeypatch.setattr(query.resolver, "resolve_llm_key", lambda db, p: "k")
        monkeypatch.setattr(
            query, "get_llm", lambda *a, **k: FakeLLM("deep learning overview")
        )

        resp = query.run_query(
            FakeDB([10, 0]), project, "summarize that", None, None,
            conversation_id=cid,
        )

        # Retrieval ran on the condensed standalone, not the literal "summarize that".
        assert seen[0] == "deep learning overview"
        # The ORIGINAL user question is what gets stored in history.
        history = query._conversations.get_history(str(project.id), cid)
        assert history[-1] == {"question": "summarize that", "answer": "ANSWER"}
        assert resp.answer == "ANSWER"


class PooledDB:
    """FakeDB with a REAL session and a REAL connection pool behind it.

    ``scalar`` runs an actual statement, so the query's opening probes really do
    take a connection out of the pool - that is what makes ``checkedout``
    meaningful instead of a stub reading back its own bookkeeping. ``add`` stays
    fake: the app's tables are Postgres-only (UUID + pgvector columns) and
    cannot be created on SQLite, and the point here is connection lifetime, not
    persistence.
    """

    def __init__(self, scalars):
        self.engine = sa.create_engine(
            "sqlite://",
            poolclass=sa.pool.QueuePool,
            pool_size=5,
            connect_args={"check_same_thread": False},
        )
        self._session = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )()
        self._scalars = list(scalars)
        self.added = []
        self.rollbacks = 0

    @property
    def checkedout(self) -> int:
        return self.engine.pool.checkedout()

    def scalar(self, *args, **kwargs):
        self._session.execute(sa.text("SELECT 1")).scalar()  # a real checkout
        return self._scalars.pop(0) if self._scalars else 0

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self._session.commit()

    def rollback(self):
        self.rollbacks += 1
        self._session.rollback()

    def dispose(self):
        self._session.close()
        self.engine.dispose()


class TestConnectionReleasedAroundProviderIO:
    """W4: a query must not sit on a pooled DB connection while it waits on a
    provider. These run against a real pool and assert on ``pool.checkedout()``
    AT THE MOMENT the provider is called - not merely that a release exists.
    """

    def _wire(self, monkeypatch, db, seen, llm):
        from app.services import query

        def spy_lookup(d, p, q, k, s, **kw):
            seen["after_probes"] = db.checkedout
            return (None, [0.1], None)

        def spy_retrieve(d, p, q, k, **kw):
            seen["during_retrieval"] = db.checkedout
            return [_src("alpha", 0.9, 0), _src("beta", 0.8, 1)]

        monkeypatch.setattr(query.semantic_cache, "lookup", spy_lookup)
        monkeypatch.setattr(query.semantic_cache, "store", lambda *a, **k: None)
        monkeypatch.setattr(query.retrieval, "retrieve", spy_retrieve)
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda d, p, q, k, **kw: []
        )
        monkeypatch.setattr(query.resolver, "resolve_llm_key", lambda d, p: "k")
        monkeypatch.setattr(query, "get_llm", lambda *a, **k: llm)
        return query

    def test_completion_runs_with_no_connection_checked_out(self, monkeypatch):
        db = PooledDB([10, 0])
        seen = {}

        class SpyLLM:
            def generate(self, system, user):
                seen["during_generate"] = db.checkedout
                return "GROUNDED ANSWER"

        query = self._wire(monkeypatch, db, seen, SpyLLM())
        # Cache off so the ONLY release before the LLM is generation.py's -
        # this isolates the behaviour under test from the single-flight one.
        monkeypatch.setattr(query.settings, "query_cache_enabled", False)

        try:
            resp = query.run_query(db, _project(), "what is X", None, api_key_id=None)

            # The query really was holding a connection right up to generation.
            assert seen["after_probes"] == 1
            assert seen["during_retrieval"] == 1
            # ...and had given it back for the duration of the completion.
            assert seen["during_generate"] == 0
            # Unchanged externally, and the Project is still usable afterwards
            # (model/latency are read AFTER the release point).
            assert resp.answer == "GROUNDED ANSWER"
            assert resp.model == "openai/gpt-4o-mini"
            assert len(resp.sources) == 2
            assert db.added and db.checkedout == 0
        finally:
            db.dispose()

    def test_streamed_completion_runs_with_no_connection_checked_out(
        self, monkeypatch
    ):
        db = PooledDB([10, 0])
        seen = {}

        class SpyStreamingLLM:
            def generate_stream(self, system, user):
                for piece in ("Hello ", "world"):
                    seen.setdefault("during_stream", []).append(db.checkedout)
                    yield piece

            def generate(self, system, user):  # pragma: no cover - not taken
                raise AssertionError("should have streamed")

        query = self._wire(monkeypatch, db, seen, SpyStreamingLLM())
        monkeypatch.setattr(query.settings, "query_cache_enabled", False)

        try:
            events = list(
                query.run_query_stream(db, _project(), "what is X", None, None)
            )

            assert seen["after_probes"] == 1
            # Every token was produced with the pool slot handed back - the
            # stream can run for minutes and must not pin a connection.
            assert seen["during_stream"] == [0, 0]
            tokens = "".join(e["text"] for e in events if e["type"] == "token")
            done = [e for e in events if e["type"] == "done"]
            assert tokens == "Hello world"
            assert done and done[0]["response"]["answer"] == "Hello world"
            assert db.checkedout == 0
        finally:
            db.dispose()

    def test_single_flight_wait_does_not_hold_a_connection(self, monkeypatch):
        """With the cache on, a follower blocks inside get_or_compute waiting on
        the leader's LLM call. The release happens BEFORE that queue, so by the
        time computation starts the connection is already back."""
        db = PooledDB([10, 0])
        seen = {}

        class SpyLLM:
            def generate(self, system, user):
                return "GROUNDED ANSWER"

        query = self._wire(monkeypatch, db, seen, SpyLLM())
        monkeypatch.setattr(query.settings, "query_cache_enabled", True)

        try:
            query.run_query(db, _project(), "what is X", None, api_key_id=None)
            assert seen["after_probes"] == 1  # held while reading the DB
            assert seen["during_retrieval"] == 0  # released before queueing
        finally:
            db.dispose()

    def test_condense_does_not_hold_a_connection(self, monkeypatch):
        """A follow-up costs an extra LLM round-trip to rewrite the question -
        that one must not pin a connection either."""
        from app.services import query

        db = PooledDB([10, 0])
        seen = {}
        project = _project()
        cid = "conv-" + uuid.uuid4().hex
        query._conversations.append_turn(
            str(project.id), cid, "what is deep learning", "A subfield of ML."
        )

        class SpyLLM:
            def generate(self, system, user):
                seen.setdefault("during_llm", []).append(db.checkedout)
                return "deep learning overview"

        self._wire(monkeypatch, db, seen, SpyLLM())
        monkeypatch.setattr(query.settings, "query_cache_enabled", False)
        monkeypatch.setattr(
            query.generation, "generate_answer", lambda *a, **k: "ANSWER"
        )
        # Condense is the FIRST thing after the probes, so key resolution is
        # where the connection is still expected to be out.
        monkeypatch.setattr(
            query.resolver,
            "resolve_llm_key",
            lambda d, p: seen.update(at_key_resolution=db.checkedout) or "k",
        )

        try:
            resp = query.run_query(
                db, project, "summarize that", None, None, conversation_id=cid
            )
            assert seen["at_key_resolution"] == 1  # SELECT, connection needed
            assert seen["during_llm"] == [0]  # the condense round-trip
            assert resp.answer == "ANSWER"
        finally:
            db.dispose()

    def test_key_is_resolved_before_the_release_and_the_release_before_the_call(
        self, monkeypatch
    ):
        """Ordering matters: resolving the provider key is a SELECT, so it has
        to happen while the connection is still checked out."""
        from app.services import generation

        order = []

        class SpyLLM:
            def generate(self, system, user):
                order.append("generate")
                return "ANSWER"

        monkeypatch.setattr(
            generation.resolver,
            "resolve_llm_key",
            lambda db, p: order.append("resolve_key") or "k",
        )
        monkeypatch.setattr(generation, "get_llm", lambda *a, **k: SpyLLM())
        monkeypatch.setattr(
            generation, "release_connection", lambda db: order.append("release")
        )

        out = generation.generate_answer(object(), _project(), "q", [_src("a", 0.9)])

        assert out == "ANSWER"
        assert order == ["resolve_key", "release", "generate"]

    def test_stream_releases_before_the_first_token(self, monkeypatch):
        from app.services import generation

        order = []

        class SpyLLM:
            def generate_stream(self, system, user):
                order.append("stream")
                yield "tok"

        monkeypatch.setattr(
            generation.resolver,
            "resolve_llm_key",
            lambda db, p: order.append("resolve_key") or "k",
        )
        monkeypatch.setattr(generation, "get_llm", lambda *a, **k: SpyLLM())
        monkeypatch.setattr(
            generation, "release_connection", lambda db: order.append("release")
        )

        out = list(
            generation.generate_answer_stream(object(), _project(), "q", [_src("a", 0.9)])
        )

        assert out == ["tok"]
        assert order == ["resolve_key", "release", "stream"]

    def test_release_is_a_noop_without_a_session(self):
        """Standalone callers generate with db=None (see test_agentic)."""
        from app.services import generation

        generation.release_connection(None)  # must not raise

    def test_release_never_fails_the_answer(self):
        from app.services import generation

        class BrokenDB:
            rolled_back = False

            def commit(self):
                raise RuntimeError("connection is gone")

            def rollback(self):
                BrokenDB.rolled_back = True

        generation.release_connection(BrokenDB())  # swallowed, not raised
        assert BrokenDB.rolled_back is True


class _ReleaseBase(DeclarativeBase):
    pass


class _Row(_ReleaseBase):
    __tablename__ = "release_probe"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String)


class TestReleaseSemantics:
    """The evidence ``release_connection`` is built on, pinned as a test: if a
    SQLAlchemy upgrade changes it, W4 silently stops working and this fails."""

    def test_commit_returns_the_connection_and_leaves_everything_usable(
        self, tmp_path
    ):
        engine = sa.create_engine(
            f"sqlite:///{tmp_path / 'release.db'}",
            poolclass=sa.pool.QueuePool,
            pool_size=5,
        )
        _ReleaseBase.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        try:
            seed = Session()
            seed.add(_Row(id=1, name="project"))
            seed.commit()
            seed.close()

            db = Session()
            assert engine.pool.checkedout() == 0
            row = db.scalar(sa.select(_Row).where(_Row.id == 1))
            assert engine.pool.checkedout() == 1  # a read pins a connection

            db.commit()  # <- what release_connection does
            assert engine.pool.checkedout() == 0  # ...and it really is back

            # expire_on_commit=False: the loaded object survives the release
            # with its values intact and emits no refresh SELECT.
            assert row.name == "project"
            assert engine.pool.checkedout() == 0
            assert row in db  # still attached, not detached like close() would

            # The session transparently takes a new connection for later work.
            db.add(_Row(id=2, name="later"))
            db.commit()
            assert db.scalar(sa.select(sa.func.count(_Row.id))) == 2
            db.close()
            assert engine.pool.checkedout() == 0
        finally:
            engine.dispose()

    def test_sessionlocal_does_not_expire_on_commit(self):
        """release_connection's safety rests on this app-level setting."""
        from app.db import SessionLocal

        assert SessionLocal.kw.get("expire_on_commit") is False

    def test_rollback_expires_loaded_objects_but_the_release_hides_it(
        self, tmp_path
    ):
        """The FAILURE branch, which the commit-path test above does not cover.

        expire_on_commit=False does NOT apply to rollback(): it expires every
        persistent instance, so without the snapshot/restore the caller's
        Project silently re-SELECTs after a failed release - a hidden
        connection checkout, and a re-read of values that may have been
        PATCHed since the answer was generated.
        """
        from app.services import generation

        engine = sa.create_engine(
            f"sqlite:///{tmp_path / 'rollback.db'}",
            poolclass=sa.pool.QueuePool,
            pool_size=5,
        )
        _ReleaseBase.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        try:
            seed = Session()
            seed.add(_Row(id=1, name="gpt-4o-mini"))
            seed.commit()
            seed.close()

            # 1. the raw behaviour this branch has to defend against
            db = Session()
            row = db.scalar(sa.select(_Row).where(_Row.id == 1))
            db.rollback()
            assert sa.inspect(row).unloaded == {"id", "name"}  # expired, silently
            db.close()

            # 2. the same rollback through release_connection
            db = Session()
            row = db.scalar(sa.select(_Row).where(_Row.id == 1))
            assert engine.pool.checkedout() == 1

            class _CommitFails:
                """A real Session whose commit() fails - what a connection
                recycled by the pooler mid-request looks like."""

                def __init__(self, session):
                    self._session = session

                def __getattr__(self, name):
                    return getattr(self._session, name)

                def commit(self):
                    raise RuntimeError("server closed the connection")

            generation.release_connection(_CommitFails(db))

            assert engine.pool.checkedout() == 0     # still released
            assert sa.inspect(row).unloaded == set()  # ...and nothing expired
            assert row.name == "gpt-4o-mini"
            assert engine.pool.checkedout() == 0     # no refresh SELECT
            assert row not in db.dirty               # restoring is not a write
            db.close()
        finally:
            engine.dispose()
