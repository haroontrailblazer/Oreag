"""Semantic (L2) query cache: threshold behavior, scoping, and never-raise.

Uses fake DB sessions - no Postgres. The pgvector similarity itself is the
database's job; these tests pin the decision logic around it.
"""
import uuid
from types import SimpleNamespace

from app.models import Project
from app.services import semantic_cache
from app.services.agentic import AgenticResult


def _project():
    return Project(
        id=uuid.uuid4(),
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        llm_provider="openai",
        llm_model="gpt-4o-mini",
    )


def _result_dict():
    return {
        "answer": "cached answer",
        "sources": [],
        "depth": "short",
        "sub_queries": ["q"],
        "rounds": 1,
        "needs_clarification": False,
        "clarification_questions": [],
    }


class _LookupDB:
    def __init__(self, row):
        self._row = row
        self.rollbacks = 0

    def execute(self, stmt, params=None):
        return SimpleNamespace(first=lambda: self._row)

    def rollback(self):
        self.rollbacks += 1


class TestSemanticLookup:
    def test_hit_at_or_above_threshold(self, monkeypatch):
        monkeypatch.setattr(semantic_cache, "_embed_question", lambda db, p, q: [0.1])
        row = SimpleNamespace(result=_result_dict(), similarity=0.82)
        hit, vector, similarity = semantic_cache.lookup(
            _LookupDB(row), _project(), "what is deep learning", 5, "3:0"
        )
        assert isinstance(hit, AgenticResult)
        assert hit.answer == "cached answer"
        assert vector == [0.1]
        assert similarity == 0.82

    def test_miss_below_threshold_still_returns_vector(self, monkeypatch):
        monkeypatch.setattr(semantic_cache, "_embed_question", lambda db, p, q: [0.1])
        row = SimpleNamespace(result=_result_dict(), similarity=0.6)
        hit, vector, similarity = semantic_cache.lookup(
            _LookupDB(row), _project(), "q", 5, "3:0"
        )
        assert hit is None
        assert vector == [0.1]  # reused by store() - the question isn't re-embedded
        assert similarity is None

    def test_threshold_default(self):
        # 0.75: strict enough that different topics don't collide, loose
        # enough that rephrasings of one question still hit.
        from app.config import settings

        assert settings.semantic_cache_min_similarity == 0.75

    def test_lookup_never_raises(self, monkeypatch):
        monkeypatch.setattr(semantic_cache, "_embed_question", lambda db, p, q: [0.1])

        class _Boom:
            def execute(self, *a, **k):
                raise RuntimeError("db down")

            def rollback(self):
                pass

        hit, vector, similarity = semantic_cache.lookup(_Boom(), _project(), "q", 5, "3:0")
        assert hit is None and vector is None and similarity is None

    def test_disabled_is_a_no_op(self, monkeypatch):
        monkeypatch.setattr(semantic_cache.settings, "semantic_cache_enabled", False)
        hit, vector, similarity = semantic_cache.lookup(object(), _project(), "q", 5, "3:0")
        assert hit is None and vector is None and similarity is None


class _StoreDB:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.executed = 0
        self.rollbacks = 0

    def add(self, obj):
        self.added.append(obj)

    def execute(self, *a, **k):
        self.executed += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class TestSemanticStore:
    def _result(self, needs_clarification: bool = False) -> AgenticResult:
        return AgenticResult(
            answer="a",
            sources=[],
            depth="short",
            sub_queries=[],
            rounds=1,
            needs_clarification=needs_clarification,
        )

    def test_stores_scoped_row_with_ttl(self):
        db = _StoreDB()
        project = _project()
        semantic_cache.store(db, project, "q", 5, "3:0", self._result(), vector=[0.1])
        assert db.commits == 1
        assert len(db.added) == 1
        row = db.added[0]
        assert row.project_id == project.id
        assert row.embedding == [0.1]
        assert row.content_signature == "3:0"
        assert row.llm_model == "gpt-4o-mini"
        assert row.expires_at is not None
        assert db.executed == 1  # expired-row housekeeping ran

    def test_clarifications_are_not_cached(self):
        db = _StoreDB()
        semantic_cache.store(
            db, _project(), "q", 5, "3:0", self._result(True), vector=[0.1]
        )
        assert db.added == []
        assert db.commits == 0

    def test_store_never_raises(self):
        class _Boom(_StoreDB):
            def commit(self):
                raise RuntimeError("no table yet")

        semantic_cache.store(
            _Boom(), _project(), "q", 5, "3:0", self._result(), vector=[0.1]
        )  # must not raise
