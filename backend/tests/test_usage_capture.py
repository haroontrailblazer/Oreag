"""Usage-analytics capture (migration 0027): tokens, cost, and cache savings.

What these pin down:

  * one /query sums the tokens of ALL its LLM calls (condense + plan +
    generate), not just the final generation;
  * a provider that reports nothing writes NULL - never 0 - into
    usage_events (NULL is "not measured"; 0 is a real empty completion);
  * a cache hit replays the token counts persisted WITH the cached answer
    as saved_prompt_tokens/saved_completion_tokens - measured, not estimated;
  * record_usage keeps its never-raises contract;
  * cost_for prices only what it can actually know.

Mirrors tests/test_query.py's harness: FakeDB + monkeypatched retrieval and
provider lookups - no network, no Postgres.
"""
import dataclasses
import json
import uuid

import pytest

from app.models import Project, QueryLog, UsageEvent
from app.providers.base import TokenUsage
from app.providers.registry import cost_for
from app.services.usage import record_usage


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

    def __init__(self, scalars=()):
        self._scalars = list(scalars)
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def scalar(self, *args, **kwargs):
        return self._scalars.pop(0) if self._scalars else 0

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _src(content, similarity, chunk_index=0):
    return {
        "filename": "a.pdf",
        "page_number": 1,
        "chunk_index": chunk_index,
        "content": content,
        "similarity": similarity,
    }


class MeteredLLM:
    """Reports usage like every real provider: 100 prompt / 10 completion.

    The reply carries a directive verb so a condensed question stays "long"
    and the planning step runs too.
    """

    model = "gpt-4o-mini"

    def __init__(self, reply="explain deep learning types and applications"):
        self.reply = reply
        self.calls = []

    def generate(self, system, user):
        return self.generate_with_usage(system, user)[0]

    def generate_with_usage(self, system, user):
        self.calls.append((system, user))
        return self.reply, TokenUsage(100, 10, self.model)


class SilentLLM:
    """A stub that reports nothing - only text, like a provider without usage."""

    model = "gpt-4o-mini"

    def generate(self, system, user):
        return "an answer"


def _wire(monkeypatch, llm):
    from app.services import query

    monkeypatch.setattr(
        query.retrieval,
        "retrieve",
        lambda db, p, q, k, **kw: [_src("alpha", 0.9, 0), _src("beta", 0.8, 1)],
    )
    monkeypatch.setattr(
        query.memory_service, "search_memories", lambda db, p, q, k, **kw: []
    )
    # L2 out of the way: these tests never embed anything.
    monkeypatch.setattr(
        query.semantic_cache, "lookup", lambda *a, **k: (None, None, None)
    )
    monkeypatch.setattr(query.semantic_cache, "store", lambda *a, **k: None)
    monkeypatch.setattr(query.resolver, "resolve_llm_key", lambda db, p: "k")
    monkeypatch.setattr(query, "get_llm", lambda *a, **k: llm)
    return query


class TestTokensSummedAcrossCalls:
    def test_condense_plan_and_generate_sum_into_one_figure(self, monkeypatch):
        llm = MeteredLLM()
        query = _wire(monkeypatch, llm)
        project = _project()
        cid = "conv-" + uuid.uuid4().hex
        query._conversations.append_turn(
            str(project.id), cid, "what is deep learning", "An ML subfield."
        )

        db = FakeDB([10, 0])
        usage_out = {}
        resp = query.run_query(
            db,
            project,
            "explain that in more detail",
            None,
            None,
            conversation_id=cid,
            usage_out=usage_out,
        )

        # condense + plan + generate ran, each metered at 100/10 - the request
        # total is their SUM via TokenUsage.__add__, not the last call's.
        assert len(llm.calls) == 3
        assert usage_out["usage"] == TokenUsage(300, 30, "gpt-4o-mini")
        assert usage_out["cache_layer"] is None
        assert "saved" not in usage_out  # a fresh answer saved nothing
        assert resp.answer == llm.reply

        # The QueryLog rides along: mean similarity of the sources used, and
        # no cache similarity because nothing came from L2.
        [log] = [o for o in db.added if isinstance(o, QueryLog)]
        assert log.retrieval_similarity == pytest.approx(0.85)
        assert log.cache_similarity is None

    def test_the_summed_usage_reaches_the_usage_event(self, monkeypatch):
        llm = MeteredLLM()
        query = _wire(monkeypatch, llm)
        project = _project()

        usage_out = {}
        query.run_query(
            FakeDB([10, 0]), project, "explain X", None, None, usage_out=usage_out
        )

        db = FakeDB()
        record_usage(
            db,
            project=project,
            api_key_id=None,
            endpoint="query",
            usage=usage_out["usage"],
            saved=usage_out.get("saved"),
            cache_layer=usage_out.get("cache_layer"),
        )
        [event] = [o for o in db.added if isinstance(o, UsageEvent)]
        # plan + generate (no history -> no condense): 2 calls at 100/10.
        assert event.prompt_tokens == 200
        assert event.completion_tokens == 20
        assert event.model == "gpt-4o-mini"
        # Priced at gpt-4o-mini list rates: (200*0.15 + 20*0.60) / 1e6.
        assert event.cost_usd == pytest.approx(0.000042)
        assert event.saved_prompt_tokens is None
        assert event.cache_layer is None


class TestUnmeasuredStaysNull:
    def test_a_silent_provider_writes_null_not_zero(self, monkeypatch):
        llm = SilentLLM()
        query = _wire(monkeypatch, llm)
        project = _project()

        usage_out = {}
        query.run_query(
            FakeDB([10, 0]), project, "what is X", None, None, usage_out=usage_out
        )
        assert usage_out["usage"].known is False  # nothing was measured

        db = FakeDB()
        record_usage(
            db,
            project=project,
            api_key_id=None,
            endpoint="query",
            usage=usage_out["usage"],
        )
        [event] = [o for o in db.added if isinstance(o, UsageEvent)]
        assert event.prompt_tokens is None  # NULL, never 0
        assert event.completion_tokens is None
        assert event.cost_usd is None  # unpriceable without counts

    def test_zero_is_a_real_measurement_and_survives(self):
        # An empty completion is a MEASURED zero - it must not be blanked to
        # NULL, and it prices at a real (tiny) dollar figure.
        db = FakeDB()
        record_usage(
            db,
            project=_project(),
            api_key_id=None,
            endpoint="query",
            usage=TokenUsage(1_000_000, 0, "gpt-4o"),
        )
        [event] = db.added
        assert event.completion_tokens == 0  # zero, not NULL
        assert event.cost_usd == pytest.approx(2.50)

    def test_no_usage_at_all_keeps_every_analytics_column_null(self):
        db = FakeDB()
        record_usage(db, project=_project(), api_key_id=None, endpoint="retrieve")
        [event] = db.added
        assert event.prompt_tokens is None
        assert event.completion_tokens is None
        assert event.model is None
        assert event.cost_usd is None
        assert event.saved_prompt_tokens is None
        assert event.saved_completion_tokens is None
        assert event.cache_layer is None


class TestCacheHitRecordsSavings:
    def test_l1_hit_replays_the_original_calls_counts(self, monkeypatch):
        llm = MeteredLLM()
        query = _wire(monkeypatch, llm)
        project = _project()

        first = {}
        query.run_query(
            FakeDB([10, 0]), project, "explain X", None, None, usage_out=first
        )
        second = {}
        query.run_query(
            FakeDB([10, 0]), project, "explain   x", None, None, usage_out=second
        )

        # First run computed for real: plan + generate at 100/10 each.
        assert first["usage"] == TokenUsage(200, 20, "gpt-4o-mini")
        # Second run hit L1: it spent nothing measurable itself, and the SAVED
        # numbers are exactly what the original computation was measured at.
        assert second["cache_layer"] == "l1"
        assert second["usage"].known is False
        assert second["saved"] == TokenUsage(200, 20)

        db = FakeDB()
        record_usage(
            db,
            project=project,
            api_key_id=None,
            endpoint="query",
            usage=second["usage"],
            saved=second["saved"],
            cache_layer=second["cache_layer"],
        )
        [event] = db.added
        assert event.saved_prompt_tokens == 200
        assert event.saved_completion_tokens == 20
        assert event.cache_layer == "l1"
        assert event.prompt_tokens is None  # the hit itself spent nothing

    def test_an_unmeasured_original_reports_no_saving(self, monkeypatch):
        # Original computed by a provider that reported nothing (the streamed
        # generation case): the hit must NOT invent a saving.
        llm = SilentLLM()
        query = _wire(monkeypatch, llm)
        project = _project()

        query.run_query(FakeDB([10, 0]), project, "what is X", None, None)
        second = {}
        query.run_query(
            FakeDB([10, 0]), project, "what is   x", None, None, usage_out=second
        )

        assert second["cache_layer"] == "l1"
        assert "saved" not in second


class TestCachedResultCarriesItsCost:
    def test_round_trip_through_the_serialized_form(self):
        from app.services import agentic

        result = agentic.AgenticResult(
            answer="a",
            sources=[],
            depth="short",
            sub_queries=[],
            rounds=1,
            needs_clarification=False,
            gen_prompt_tokens=42,
            gen_completion_tokens=7,
        )
        back = agentic.AgenticResult(**json.loads(json.dumps(dataclasses.asdict(result))))
        assert back.gen_prompt_tokens == 42
        assert back.gen_completion_tokens == 7

    def test_a_pre_migration_cache_payload_still_deserializes(self):
        # Entries stored before these fields existed lack the keys entirely -
        # they must come back as "not measured", not crash the lookup.
        from app.services import agentic

        payload = {
            "answer": "a",
            "sources": [],
            "depth": "short",
            "sub_queries": [],
            "rounds": 1,
            "needs_clarification": False,
            "clarification_questions": [],
        }
        back = agentic.AgenticResult(**payload)
        assert back.gen_prompt_tokens is None
        assert back.gen_completion_tokens is None


class ExplodingAddDB(FakeDB):
    def add(self, obj):
        raise RuntimeError("db down")


class EverythingFailsDB(FakeDB):
    def commit(self):
        raise RuntimeError("commit failed")

    def rollback(self):
        raise RuntimeError("rollback failed too")


class TestRecordUsageNeverRaises:
    def test_an_add_failure_is_swallowed(self):
        record_usage(
            ExplodingAddDB(),
            project=_project(),
            api_key_id=None,
            endpoint="query",
            usage=TokenUsage(1, 2, "m"),
        )  # not raising IS the assertion

    def test_even_the_rollback_failing_is_swallowed(self):
        record_usage(
            EverythingFailsDB(), project=_project(), api_key_id=None, endpoint="query"
        )


class TestCostFor:
    def test_a_known_model_prices_both_sides(self):
        usage = TokenUsage(1_000_000, 1_000_000, "gpt-4o")
        assert cost_for("gpt-4o", usage) == pytest.approx(12.50)

    def test_an_unknown_model_is_none_never_a_guess(self):
        assert cost_for("some-future-model", TokenUsage(10, 10, "x")) is None

    def test_a_partial_measurement_is_unpriceable(self):
        # Prompt measured, completion unknown: pricing only half would look
        # like a total while understating it - unknown is the honest answer.
        assert cost_for("gpt-4o", TokenUsage(10, None, "gpt-4o")) is None
        assert cost_for("gpt-4o", TokenUsage(None, 10, "gpt-4o")) is None

    def test_zero_tokens_price_at_a_real_zero(self):
        assert cost_for("gpt-4o", TokenUsage(0, 0, "gpt-4o")) == 0.0

    def test_the_empty_model_is_unknown(self):
        assert cost_for("", TokenUsage(10, 10, "")) is None


class TestStreamUsage:
    def test_stream_meters_the_fallback_generation(self, monkeypatch):
        # MeteredLLM has no generate_stream, so the stream falls back to one
        # blocking call - which must be metered like the non-streaming path.
        llm = MeteredLLM()
        query = _wire(monkeypatch, llm)
        project = _project()

        db = FakeDB([10, 0])
        usage_out = {}
        events = list(
            query.run_query_stream(
                db, project, "explain X", None, usage_out=usage_out
            )
        )

        assert events[-1]["type"] == "done"
        # plan + fallback generation, each 100/10.
        assert usage_out["usage"] == TokenUsage(200, 20, "gpt-4o-mini")
        assert usage_out["cache_layer"] is None
        [log] = [o for o in db.added if isinstance(o, QueryLog)]
        assert log.retrieval_similarity == pytest.approx(0.85)

    def test_stream_stores_its_counts_for_future_hits(self, monkeypatch):
        llm = MeteredLLM()
        query = _wire(monkeypatch, llm)
        project = _project()

        list(query.run_query_stream(FakeDB([10, 0]), project, "explain X", None))

        # A later non-streaming ask hits L1 and reports the stream's counts.
        second = {}
        query.run_query(
            FakeDB([10, 0]), project, "explain   x", None, None, usage_out=second
        )
        assert second["cache_layer"] == "l1"
        assert second["saved"] == TokenUsage(200, 20)
