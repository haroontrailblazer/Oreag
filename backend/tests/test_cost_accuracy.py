"""The three cost numbers must agree: ours, Langfuse's, and the provider's bill.

WHY THIS EXISTS

Tokens were metered correctly and the dollars still disagreed, in three
independent ways that a token-count test can never catch.

1. NOBODY TOLD LANGFUSE WHAT A CALL COST. `tracing.py` sent a model name and a
   token count and let Langfuse re-derive the price from a table we do not
   control. Two tables, two answers - measured live against this project's own
   Langfuse: `claude-sonnet-5` priced $3/$15 here and $2/$10 there, and 13 of
   the 29 priced ids (grok, deepseek, groq, cohere, together, fireworks) match
   NOTHING in Langfuse, so the app showed real dollars where the dashboard
   showed a blank. Sending `cost_details` makes us the single source of truth
   and collapses the whole class.

2. GEMINI'S THINKING TOKENS WERE BILLED AND NEVER COUNTED. `usage_metadata`
   reports them in `thoughts_token_count`, which is NOT inside
   `candidates_token_count` - the SDK documents `total_token_count` as the sum
   of prompt + candidates + tool_use + thoughts. Google charges them at the
   output rate (corroborated by Langfuse's managed table, which prices
   `thoughts_token_count` identically to `output` on every Gemini id we
   price). Oreag read only `candidates`, so both ledgers sat below the invoice - and agreed
   with each other while doing it, which is why it went unnoticed.

3. HALF A MEASUREMENT WAS SENT AS A WHOLE ONE. `TokenUsage.known` is an OR, so
   a call reporting a prompt count but no completion count passed the gate and
   was sent as `output: 0`. Langfuse then priced the input side and showed a
   real number, while `cost_for` - which requires both counts - stored NULL.
   Same call, one ledger with dollars and one without.

The fourth defect has no unit test because it is arithmetic that only the
database can prove: cost was quantised to 6dp at NUMERIC(12,6), which prices a
20-token embedding at exactly $0.000000. Migration 0041 widens it; the rounding
constant is asserted here.
"""
import contextlib
import pathlib
import re
from unittest import mock

import pytest

from app.providers.base import TokenUsage, usage_from_gemini
from app.providers.registry import cost_breakdown, cost_for, embedding_cost_for
from app.services import tracing


class _Meta:
    """Stands in for google-genai's `usage_metadata`."""

    def __init__(self, prompt=None, candidates=None, thoughts=None):
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates
        if thoughts is not None:
            self.thoughts_token_count = thoughts


class _Resp:
    def __init__(self, meta):
        self.usage_metadata = meta


class TestGeminiThinkingTokens:
    """Thinking tokens bill at the output rate, so they belong in completion."""

    def test_thinking_tokens_are_added_to_the_completion_count(self):
        usage = usage_from_gemini(
            _Resp(_Meta(prompt=1000, candidates=30, thoughts=120)), "gemini-3.5-flash"
        )
        assert usage.completion_tokens == 150
        assert usage.prompt_tokens == 1000

    def test_thinking_tokens_are_reported_separately_as_well(self):
        """Kept visible so Langfuse can show the split, not just the total."""
        usage = usage_from_gemini(
            _Resp(_Meta(prompt=10, candidates=30, thoughts=120)), "gemini-3.5-flash"
        )
        assert usage.reasoning_tokens == 120

    def test_a_model_that_does_not_think_is_unchanged(self):
        usage = usage_from_gemini(_Resp(_Meta(prompt=10, candidates=30)), "m")
        assert usage.completion_tokens == 30
        assert usage.reasoning_tokens is None

    def test_thoughts_without_candidates_still_counts(self):
        """A pure-reasoning turn that emits no answer text still costs money."""
        usage = usage_from_gemini(_Resp(_Meta(prompt=10, thoughts=77)), "m")
        assert usage.completion_tokens == 77


class TestPriceableIsStricterThanKnown:
    """`known` answers "did we measure anything"; pricing needs both halves."""

    def test_a_half_measured_call_is_not_priceable(self):
        usage = TokenUsage(prompt_tokens=100, completion_tokens=None, model="gpt-4o")
        assert usage.known is True
        assert usage.priceable is False

    def test_both_counts_present_is_priceable(self):
        assert TokenUsage(1, 2, "gpt-4o").priceable is True

    def test_a_real_empty_completion_is_priceable(self):
        assert TokenUsage(10, 0, "gpt-4o").priceable is True


class TestCostBreakdown:
    def test_input_and_output_are_priced_separately(self):
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=100, model="gpt-4o-mini")
        # gpt-4o-mini is (0.15, 0.60) per 1M tokens.
        assert cost_breakdown("gpt-4o-mini", usage) == {
            "input": 0.00015,
            "output": 0.00006,
            "total": 0.00021,
        }

    @pytest.mark.parametrize(
        "model,prompt,completion",
        [
            ("gpt-4o-mini", 1000, 100),   # priced, both counts
            ("gpt-4o-mini", 0, 0),        # a real, measured, free call
            ("grok-3-mini", 1000, 100),   # no listed price -> None
            ("gpt-4o", 1000, None),       # half measured -> None
            ("", 1, 1),                   # no model at all -> None
        ],
    )
    def test_cost_for_and_the_breakdown_never_disagree(
        self, model, prompt, completion
    ):
        """A contract over the NULL discipline, not the arithmetic.

        Asserting cost_for == cost_breakdown["total"] on one priced model was
        vacuous - cost_for IS `cost_breakdown(...)["total"]`, so it compared a
        function to itself. What is worth pinning is that the two agree on when
        there is NO number: an unpriced model, a half-measured call and a
        missing model must all be None on both sides, because a divergence
        there is what puts a figure on the dashboard that the billing table
        does not have.
        """
        usage = TokenUsage(prompt, completion, model)
        breakdown = cost_breakdown(model, usage)
        expected = None if breakdown is None else breakdown["total"]
        assert cost_for(model, usage) == expected

    def test_an_unpriced_model_has_no_breakdown(self):
        assert cost_breakdown("grok-3-mini", TokenUsage(1, 1, "grok-3-mini")) is None

    def test_a_half_measured_call_has_no_breakdown(self):
        assert cost_breakdown("gpt-4o", TokenUsage(1, None, "gpt-4o")) is None


class TestSubMicrodollarSpendSurvives:
    """6dp priced a 20-token embedding at exactly zero - a measured lie."""

    def test_a_small_embedding_is_not_rounded_to_free(self):
        cost = embedding_cost_for("text-embedding-3-small", 20)
        assert cost is not None
        assert cost > 0

    def test_a_small_generation_is_not_rounded_to_free(self):
        cost = cost_for("llama-3.1-8b-instant", TokenUsage(1, 0, "llama-3.1-8b-instant"))
        assert cost is not None
        assert cost > 0


class _Span:
    def __init__(self):
        self.updates = {}

    def update(self, **kwargs):
        self.updates.update(kwargs)


class _Observation:
    def __init__(self, span, kwargs):
        self.span = span
        self.kwargs = kwargs

    def __enter__(self):
        return self.span

    def __exit__(self, *a):
        return False


class _FakeLangfuse:
    """Captures what would have been sent, without a network or an SDK."""

    def __init__(self):
        self.observations: list[_Observation] = []

    def start_as_current_observation(self, **kwargs):
        obs = _Observation(_Span(), kwargs)
        self.observations.append(obs)
        return obs


class _Llm:
    def __init__(self, model, usage):
        self.model = model
        self._usage = usage

    def generate_with_usage(self, system_prompt, user_prompt):
        return "an answer", self._usage


@pytest.fixture()
def langfuse(monkeypatch):
    fake = _FakeLangfuse()
    monkeypatch.setattr(tracing, "client", lambda: fake)
    return fake


class TestCostDetailsReachLangfuse:
    """The fix for "Langfuse says one number and the app says another"."""

    def test_a_generation_carries_the_cost_we_computed(self, langfuse):
        llm = _Llm("gpt-4o-mini", TokenUsage(1000, 100, "gpt-4o-mini"))
        tracing.observed_generate(llm, "sys", "user", name="generate-answer")

        sent = langfuse.observations[0].span.updates
        assert sent["usage_details"] == {"input": 1000, "output": 100, "total": 1100}
        assert sent["cost_details"] == {
            "input": 0.00015,
            "output": 0.00006,
            "total": 0.00021,
        }

    def test_a_model_langfuse_cannot_price_still_gets_our_cost(self, langfuse):
        """`llama-3.1-8b-instant` matches nothing in Langfuse's table - without
        cost_details the dashboard shows a blank while the app bills real
        dollars."""
        usage = TokenUsage(1000, 100, "llama-3.1-8b-instant")
        llm = _Llm("llama-3.1-8b-instant", usage)
        tracing.observed_generate(llm, "sys", "user", name="generate-answer")

        sent = langfuse.observations[0].span.updates
        assert sent["cost_details"]["total"] == cost_for("llama-3.1-8b-instant", usage)

    def test_a_half_measured_call_sends_neither_usage_nor_cost(self, langfuse):
        """It used to send `output: 0`, so Langfuse priced the input side while
        the app stored NULL - the same call, in one ledger only."""
        llm = _Llm("gpt-4o-mini", TokenUsage(1000, None, "gpt-4o-mini"))
        tracing.observed_generate(llm, "sys", "user", name="generate-answer")

        sent = langfuse.observations[0].span.updates
        assert "usage_details" not in sent
        assert "cost_details" not in sent

    def test_an_unpriced_model_reports_tokens_without_inventing_a_cost(self, langfuse):
        """NULL cost is honest; a guessed one is a wrong invoice."""
        llm = _Llm("grok-3-mini", TokenUsage(1000, 100, "grok-3-mini"))
        tracing.observed_generate(llm, "sys", "user", name="generate-answer")

        sent = langfuse.observations[0].span.updates
        assert sent["usage_details"]["input"] == 1000
        assert "cost_details" not in sent

    def test_tracing_being_off_still_returns_the_answer(self, monkeypatch):
        monkeypatch.setattr(tracing, "client", lambda: None)
        llm = _Llm("gpt-4o-mini", TokenUsage(1, 1, "gpt-4o-mini"))
        text, usage = tracing.observed_generate(llm, "s", "u", name="n")
        assert text == "an answer"
        assert usage.prompt_tokens == 1


class TestStreamedGenerationsCarryCostToo:
    def test_a_streamed_call_sends_cost_details(self, langfuse):
        usage = TokenUsage(1000, 100, "gpt-4o-mini")

        def streamer(system_prompt, user_prompt):
            yield "hello"
            return usage

        llm = _Llm("gpt-4o-mini", usage)
        gen = tracing.observed_stream(llm, streamer, "s", "u", name="generate-answer")
        list(gen)

        sent = langfuse.observations[0].span.updates
        assert sent["cost_details"]["total"] == cost_for("gpt-4o-mini", usage)


class TestEmbeddingSpendReachesLangfuse:
    """Langfuse held no embedding observation at all, so its total was
    structurally below the app's headline - which adds embedding dollars in."""

    def test_an_embedding_observation_carries_tokens_and_cost(self, langfuse):
        tracing.record_embedding_spend({"text-embedding-3-small": 25_000})

        obs = langfuse.observations[0]
        assert obs.kwargs["as_type"] == "generation"
        assert obs.kwargs["model"] == "text-embedding-3-small"
        sent = obs.span.updates
        assert sent["usage_details"] == {"input": 25_000, "total": 25_000}
        assert sent["cost_details"]["total"] == embedding_cost_for(
            "text-embedding-3-small", 25_000
        )

    def test_an_unpriced_embedder_reports_tokens_only(self, langfuse):
        tracing.record_embedding_spend({"nomic-embed-text": 500})

        sent = langfuse.observations[0].span.updates
        assert sent["usage_details"]["input"] == 500
        assert "cost_details" not in sent

    def test_nothing_embedded_emits_nothing(self, langfuse):
        tracing.record_embedding_spend({})
        assert langfuse.observations == []

    def test_tracing_being_off_is_a_no_op(self, monkeypatch):
        monkeypatch.setattr(tracing, "client", lambda: None)
        tracing.record_embedding_spend({"text-embedding-3-small": 10})

    def test_the_attributed_branch_production_always_takes_still_emits(
        self, langfuse
    ):
        """Every test above calls this positionally, so all of them took the
        `owner_id is None` short-circuit and the branch the ONLY production
        caller uses was covered by nothing. It sits under a bare
        `except Exception: logger.debug`, so a failure there emits nothing and
        says nothing."""
        tracing.record_embedding_spend(
            {"text-embedding-3-small": 25_000},
            owner_id="owner-1",
            project_id="p1",
            api_key_id=None,
        )
        assert len(langfuse.observations) == 1
        sent = langfuse.observations[0].span.updates
        assert sent["usage_details"] == {"input": 25_000, "total": 25_000}

    def test_it_does_not_rewrite_an_open_parent_trace(self, langfuse):
        """Re-entering propagate_attributes inside a live /query trace wrote
        `embedding` into the ROOT span's tags - verified against the real SDK,
        which merges list attributes onto whatever span is current. The two
        streaming routes call record_usage INSIDE the trace, so a streamed
        query and a buffered one produced structurally different traces for
        the same event."""
        import contextlib

        entered = []

        @contextlib.contextmanager
        def _spy(**kwargs):
            entered.append(kwargs)
            yield

        with mock.patch("langfuse.propagate_attributes", _spy):
            with mock.patch.object(tracing, "_has_live_span", lambda: True):
                tracing.record_embedding_spend(
                    {"text-embedding-3-small": 10}, owner_id="owner-1"
                )

        assert entered == [], (
            "attribution must be INHERITED from the open trace, not rewritten "
            "onto it"
        )
        assert len(langfuse.observations) == 1


class TestMigration0041Shape:
    """The migration is executed by NOTHING in this suite.

    Tests build their schema from `Base.metadata.create_all()`, so models.py's
    Numeric(18, 10) is what 1100-odd tests exercise and the .sql file has never
    run anywhere. That makes a text scan the only guard there is - it is what
    TestMigration0034Shape / 0039Shape exist for, and 0041 shipped without one.
    """

    @staticmethod
    def _sql() -> str:
        return (
            pathlib.Path(__file__).parent.parent.parent
            / "supabase/migrations/0041_cost_precision.sql"
        ).read_text(encoding="utf-8")

    def test_no_percent_sign_anywhere(self):
        """psycopg scans the whole statement for placeholders, comments
        included, so one percent sign makes the file unrunnable."""
        assert "%" not in self._sql()

    def test_every_cost_column_is_widened(self):
        sql = self._sql()
        for column in (
            "cost_usd",
            "saved_cost_usd",
            "embedding_cost_usd",
            "saved_embedding_cost_usd",
        ):
            assert f"alter column {column} type numeric(18, 10)" in sql

    def test_the_sql_scale_matches_the_constant_the_code_rounds_to(self):
        """The only thing tying the .sql to the code. If `_COST_DP` moves and
        this file does not, Postgres quantises every cost back to the old scale
        and the app and the database disagree again - silently, because nothing
        executes this file."""
        from app.providers import registry

        scale = int(re.search(r"numeric\(18, (\d+)\)", self._sql()).group(1))
        assert scale == registry._COST_DP

    def test_it_guards_the_lock_it_takes(self):
        """A numeric SCALE change is a heap REWRITE under ACCESS EXCLUSIVE -
        Postgres only relabels when the scale is unchanged and the precision
        grows. On usage_events, which every /v1 request, ingest, judge and
        playground call writes, an unguarded ALTER queues behind any
        long-running scan and everything else queues behind it. 0024 and 0039
        both set this for strictly lighter operations."""
        assert "set local lock_timeout" in self._sql()

    def test_it_destroys_nothing(self):
        sql = self._sql()
        assert "drop column" not in sql and "drop table" not in sql
