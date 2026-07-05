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
            lambda db, p, q, k: [_src("alpha", 0.9, 0), _src("beta", 0.8, 1)],
        )
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k: []
        )

        def fake_generate(db, p, question, sources, depth="short"):
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
            lambda db, p, q, k: [_src("alpha", 0.9, 0), _src("beta", 0.8, 1)],
        )

        def exploding_search(db, p, q, k):
            raise RuntimeError("different vector dimensions 1536 and 768")

        monkeypatch.setattr(query.memory_service, "search_memories", exploding_search)
        monkeypatch.setattr(query.settings, "rag_memory_blend_k", 3)
        monkeypatch.setattr(
            query.generation, "generate_answer",
            lambda db, p, question, sources, depth="short": "DOCS ONLY",
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
            query.retrieval, "retrieve", lambda db, p, q, k: [_src("noise", 0.01)]
        )
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k: []
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


class TestQueryCaching:
    def _wire(self, monkeypatch, gen_calls):
        from app.services import query

        monkeypatch.setattr(
            query.retrieval, "retrieve",
            lambda db, p, q, k: [_src("alpha", 0.9, 0), _src("beta", 0.8, 1)],
        )
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k: []
        )

        def fake_generate(db, p, question, sources, depth="short"):
            gen_calls.append(question)
            return "GROUNDED ANSWER"

        monkeypatch.setattr(query.generation, "generate_answer", fake_generate)
        return query

    def test_repeated_question_is_served_from_cache(self, monkeypatch):
        gen_calls = []
        query = self._wire(monkeypatch, gen_calls)
        project = _project()

        r1 = query.run_query(FakeDB([10, 0]), project, "What is X?", None, None)
        # Same question (different spacing/case) → same cache entry.
        r2 = query.run_query(FakeDB([10, 0]), project, "what is   x?", None, None)

        assert r1.answer == r2.answer == "GROUNDED ANSWER"
        assert len(gen_calls) == 1  # the second ask did not re-run the LLM

    def test_content_change_bypasses_cache(self, monkeypatch):
        gen_calls = []
        query = self._wire(monkeypatch, gen_calls)
        project = _project()

        query.run_query(FakeDB([10, 0]), project, "What is X?", None, None)
        # A newly ingested file changes the chunk count → fresh answer.
        query.run_query(FakeDB([11, 0]), project, "What is X?", None, None)

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
            lambda db, p, q, k: [_src("alpha", 0.9, 0), _src("beta", 0.8, 1)],
        )
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k: []
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
        resp = query.run_query(
            FakeDB([10, 0]), _project(), "what is X", None, None, conversation_id=cid
        )

        assert resp.answer == "GROUNDED ANSWER"
        assert resp.conversation_id == cid
        assert llm.calls == []  # no history → no condense call
        assert query._conversations.get_history(cid) == [
            {"question": "what is X", "answer": "GROUNDED ANSWER"}
        ]

    def test_followup_is_condensed_against_history(self, monkeypatch):
        from app.services import query

        cid = "conv-" + uuid.uuid4().hex
        query._conversations.append_turn(
            cid, "what is deep learning", "Deep learning is a subfield of ML."
        )

        seen = []
        monkeypatch.setattr(
            query.retrieval, "retrieve",
            lambda db, p, q, k: seen.append(q) or [_src("ctx", 0.9, 0)],
        )
        monkeypatch.setattr(
            query.memory_service, "search_memories", lambda db, p, q, k: []
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
            FakeDB([10, 0]), _project(), "summarize that", None, None,
            conversation_id=cid,
        )

        # Retrieval ran on the condensed standalone, not the literal "summarize that".
        assert seen[0] == "deep learning overview"
        # The ORIGINAL user question is what gets stored in history.
        history = query._conversations.get_history(cid)
        assert history[-1] == {"question": "summarize that", "answer": "ANSWER"}
        assert resp.answer == "ANSWER"
