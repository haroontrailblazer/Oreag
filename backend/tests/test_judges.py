"""The judge spends the user's OWN provider credit, which makes it the one
observability feature here that can cost someone money. Its guardrails - off by
default, sampled, cache hits skipped, never able to break a request - are what
these tests protect.
"""
import inspect
import types

from app.config import settings
from app.providers.base import TokenUsage
from app.services import judges


class TestSampling:
    def test_off_by_default(self, monkeypatch):
        """Nobody's provider bill grows because they upgraded Oreag."""
        monkeypatch.setattr(settings, "langfuse_judge_enabled", False)
        assert judges.should_judge() is False

    def test_zero_rate_never_judges(self, monkeypatch):
        monkeypatch.setattr(settings, "langfuse_judge_enabled", True)
        monkeypatch.setattr(settings, "langfuse_judge_sample_rate", 0.0)
        assert judges.should_judge() is False

    def test_full_rate_always_judges(self, monkeypatch):
        monkeypatch.setattr(settings, "langfuse_judge_enabled", True)
        monkeypatch.setattr(settings, "langfuse_judge_sample_rate", 1.0)
        assert all(judges.should_judge() for _ in range(20))

    def test_partial_rate_is_roughly_the_rate(self, monkeypatch):
        monkeypatch.setattr(settings, "langfuse_judge_enabled", True)
        monkeypatch.setattr(settings, "langfuse_judge_sample_rate", 0.5)
        hits = sum(judges.should_judge() for _ in range(2000))
        assert 800 < hits < 1200, f"sampling looks wrong: {hits}/2000"


class TestParser:
    """Models ignore "reply with only JSON". A judge whose output is usable but
    wrapped in noise should count - the alternative is discarding scores that
    were already paid for."""

    def test_clean_json(self):
        got = judges._parse('{"groundedness": 0.9, "relevance": 0.8}')
        assert got == {"groundedness": 0.9, "relevance": 0.8}

    def test_code_fence(self):
        got = judges._parse('```json\n{"groundedness": 1, "relevance": 0.5}\n```')
        assert got == {"groundedness": 1.0, "relevance": 0.5}

    def test_preamble_prose(self):
        got = judges._parse('Sure!\n{"groundedness": 0.2, "relevance": 0.1}')
        assert got == {"groundedness": 0.2, "relevance": 0.1}

    def test_out_of_range_is_clamped_not_discarded(self):
        """1.4 means "very good"; throwing it away loses more than it protects."""
        got = judges._parse('{"groundedness": 1.4, "relevance": -0.2}')
        assert got == {"groundedness": 1.0, "relevance": 0.0}

    def test_prose_only_is_rejected(self):
        assert judges._parse("The answer looks fine.") is None

    def test_wrong_types_are_rejected(self):
        """A bool is not a score - and True would pass an isinstance(x, int)
        check in Python, so it has to be excluded explicitly."""
        assert judges._parse('{"groundedness": "high", "relevance": true}') is None

    def test_partial_scores_are_kept(self):
        assert judges._parse('{"groundedness": 0.7}') == {"groundedness": 0.7}

    def test_comment_is_bounded(self):
        got = judges._parse('{"groundedness": 0.5, "comment": "' + "x" * 900 + '"}')
        assert len(got["comment"]) <= 500

    def test_empty_input(self):
        assert judges._parse("") is None


def _project():
    return types.SimpleNamespace(llm_provider="openai", llm_model="gpt-4o-mini")


def _stub_langfuse(monkeypatch, sink, create_score=None):
    monkeypatch.setattr(
        judges,
        "client",
        lambda: types.SimpleNamespace(
            create_score=create_score or (lambda **kw: sink.append(kw)),
            flush=lambda: None,
        ),
    )
    monkeypatch.setattr(
        judges, "resolver", types.SimpleNamespace(resolve_llm_key=lambda db, p: "k")
    )
    monkeypatch.setattr(judges, "get_llm", lambda *a, **kw: object())


class TestJudgeAnswer:
    def test_no_client_means_no_judging(self, monkeypatch):
        monkeypatch.setattr(judges, "client", lambda: None)
        assert judges.judge_answer(
            None, _project(), question="q", answer="a",
            sources=[{"content": "c"}], trace_id="t"
        ) is None

    def test_no_sources_means_no_judging(self, monkeypatch):
        """Relevance judges the SOURCES; with none there is nothing to judge."""
        monkeypatch.setattr(judges, "client", lambda: object())
        assert judges.judge_answer(
            None, _project(), question="q", answer="a", sources=[], trace_id="t"
        ) is None

    def test_no_trace_means_no_judging(self, monkeypatch):
        """Scores with nowhere to attach are money spent for nothing."""
        monkeypatch.setattr(judges, "client", lambda: object())
        assert judges.judge_answer(
            None, _project(), question="q", answer="a",
            sources=[{"content": "c"}], trace_id=""
        ) is None

    def test_unparseable_reply_is_still_metered(self, monkeypatch):
        """The call was made and billed. Reporting nothing would hide a real
        cost - exactly the failure this whole phase exists to fix."""
        scored: list = []
        _stub_langfuse(monkeypatch, scored)
        monkeypatch.setattr(
            judges, "call_llm",
            lambda *a, **kw: ("not json at all", TokenUsage(10, 2, "m")))

        usage = judges.judge_answer(
            None, _project(), question="q", answer="a",
            sources=[{"content": "c"}], trace_id="t")
        assert usage == TokenUsage(10, 2, "m")
        assert scored == [], "nothing parseable, so nothing should be scored"

    def test_scores_are_pushed_to_the_trace(self, monkeypatch):
        scored: list = []
        _stub_langfuse(monkeypatch, scored)
        monkeypatch.setattr(judges, "call_llm", lambda *a, **kw: (
            '{"groundedness": 0.9, "relevance": 0.4, "comment": "ok"}',
            TokenUsage(10, 2, "m")))

        judges.judge_answer(None, _project(), question="q", answer="a",
                            sources=[{"content": "c"}], trace_id="tid")
        assert {s["name"]: s["value"] for s in scored} == {
            "groundedness": 0.9, "relevance": 0.4
        }
        assert all(s["trace_id"] == "tid" for s in scored)

    def test_a_failing_provider_never_raises(self, monkeypatch):
        """This runs after the user already has their answer."""
        _stub_langfuse(monkeypatch, [])

        def boom(*a, **kw):
            raise RuntimeError("provider down")

        monkeypatch.setattr(judges, "call_llm", boom)
        assert judges.judge_answer(
            None, _project(), question="q", answer="a",
            sources=[{"content": "c"}], trace_id="t") is None

    def test_a_failing_score_push_does_not_lose_the_usage(self, monkeypatch):
        def bad_score(**kw):
            raise RuntimeError("langfuse down")

        _stub_langfuse(monkeypatch, [], create_score=bad_score)
        monkeypatch.setattr(judges, "call_llm", lambda *a, **kw: (
            '{"groundedness": 0.9}', TokenUsage(10, 2, "m")))

        assert judges.judge_answer(
            None, _project(), question="q", answer="a",
            sources=[{"content": "c"}], trace_id="t") == TokenUsage(10, 2, "m")


class TestWiring:
    def _src(self):
        from app.routers import rag_v1

        return inspect.getsource(rag_v1._maybe_judge)

    def test_cache_hits_are_not_judged(self):
        """A cached answer was already eligible for judging when it was first
        computed; judging it again spends money re-evaluating unchanged text."""
        assert 'usage_out.get("cache_layer") is not None' in self._src()

    def test_the_judge_is_metered_under_its_own_endpoint(self):
        """Folded into "query" it would be an invisible cost the user cannot
        decide to stop paying."""
        assert 'endpoint="judge"' in inspect.getsource(judges.schedule)

    def test_it_never_blocks_the_caller(self):
        """`/query/stream` calls this while its SSE connection is still open;
        blocking would hold that connection for an evaluation the client is
        not waiting for."""
        src = inspect.getsource(judges.schedule)
        assert "daemon=True" in src
        assert "threading.Thread" in src

    def test_it_owns_its_session(self):
        """One mechanism for both routes means one lifetime to reason about,
        instead of depending on when each route's request session closes."""
        src = inspect.getsource(judges.schedule)
        assert "SessionLocal()" in src
        assert "db.close()" in src

    def test_both_query_routes_schedule_a_judge(self):
        from app.routers import rag_v1

        buffered = inspect.getsource(rag_v1.public_query)
        streamed = inspect.getsource(rag_v1.public_query_stream)
        assert "_maybe_judge" in buffered
        assert "_maybe_judge" in streamed, "streamed answers went unjudged"

    def test_the_stream_reads_its_trace_id_inside_the_trace(self):
        """Outside the context there is no current trace, so a judge scheduled
        afterwards has nowhere to attach - the original defect."""
        from app.routers import rag_v1

        src = inspect.getsource(rag_v1.public_query_stream)
        trace_at = src.index("tracing.query_trace(")
        id_at = src.index('usage_out["trace_id"]')
        finally_at = src.index("finally:")
        assert trace_at < id_at < finally_at
