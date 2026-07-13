"""Integration tests for run_query - the shared /v1 + playground entry point -
now driven by the agentic retrieval loop.

These use a fake DB and monkeypatched retrieval/generation so no network or
Postgres is touched, mirroring the style of tests/test_units.py.
"""
import uuid

import pytest

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
