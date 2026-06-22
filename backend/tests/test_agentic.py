"""Unit tests for the agentic retrieval loop (services/agentic.py).

The loop fixes "big questions return nothing": it auto-detects when a question
needs a long, structured answer, decomposes it into sub-queries, retrieves for
each, and — if it still can't gather enough grounding — escalates to a human
clarification step instead of refusing.
"""
import uuid

from app.models import Project


class TestDetectDepth:
    def test_simple_factual_question_is_short(self):
        from app.services.agentic import detect_depth

        assert detect_depth("what is deep learning") == "short"

    def test_explain_multipart_question_is_long(self):
        from app.services.agentic import detect_depth

        assert (
            detect_depth("Explain deep learning, its types, and applications")
            == "long"
        )

    def test_explicit_marks_force_long(self):
        from app.services.agentic import detect_depth

        # "what is a perceptron" alone is short, but a marks weighting demands a
        # full exam-style answer.
        assert detect_depth("What is a perceptron? (13 marks)") == "long"

    def test_plain_who_question_is_short(self):
        from app.services.agentic import detect_depth

        assert detect_depth("Who proposed the perceptron?") == "short"


class TestParseSubqueries:
    def test_parses_numbered_list(self):
        from app.services.agentic import parse_subqueries

        raw = "1. What is X?\n2. How does Y work?"
        assert parse_subqueries(raw, 5) == ["What is X?", "How does Y work?"]

    def test_strips_bullets_and_blank_lines(self):
        from app.services.agentic import parse_subqueries

        raw = "- first\n\n*  second\n\n\n• third"
        assert parse_subqueries(raw, 5) == ["first", "second", "third"]

    def test_caps_to_max(self):
        from app.services.agentic import parse_subqueries

        raw = "a\nb\nc\nd\ne"
        assert parse_subqueries(raw, 3) == ["a", "b", "c"]

    def test_dedupes_case_insensitively_preserving_order(self):
        from app.services.agentic import parse_subqueries

        raw = "What is X?\nwhat is x?\nHow about Y?"
        assert parse_subqueries(raw, 5) == ["What is X?", "How about Y?"]


class FakeLLM:
    """Records prompts and returns a canned reply — no network."""

    def __init__(self, reply: str, model: str = "fake/llm"):
        self.reply = reply
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.reply


class TestPlanSubqueries:
    def test_keeps_original_question_first(self):
        from app.services.agentic import plan_subqueries

        llm = FakeLLM("types of deep learning\napplications of deep learning")
        result = plan_subqueries(llm, "Explain deep learning and its uses", 5)
        assert result == [
            "Explain deep learning and its uses",
            "types of deep learning",
            "applications of deep learning",
        ]

    def test_falls_back_to_question_when_model_returns_nothing(self):
        from app.services.agentic import plan_subqueries

        llm = FakeLLM("   \n\n")
        assert plan_subqueries(llm, "the question", 5) == ["the question"]

    def test_caps_total_including_the_original(self):
        from app.services.agentic import plan_subqueries

        llm = FakeLLM("a\nb\nc\nd")
        assert plan_subqueries(llm, "Q", 3) == ["Q", "a", "b"]

    def test_dedupes_echoed_original(self):
        from app.services.agentic import plan_subqueries

        llm = FakeLLM("Explain X\nsecond angle")
        assert plan_subqueries(llm, "Explain X", 5) == ["Explain X", "second angle"]


def _chunk(filename, chunk_index, content, similarity, page_number=1):
    return {
        "filename": filename,
        "page_number": page_number,
        "chunk_index": chunk_index,
        "content": content,
        "similarity": similarity,
    }


class TestMergeSources:
    def test_dedupes_same_chunk_keeping_higher_similarity(self):
        from app.services.agentic import merge_sources

        weak = [_chunk("a.pdf", 0, "x", 0.5)]
        strong = [_chunk("a.pdf", 0, "x", 0.8)]
        merged = merge_sources([weak, strong])
        assert len(merged) == 1
        assert merged[0]["similarity"] == 0.8

    def test_sorts_by_similarity_descending(self):
        from app.services.agentic import merge_sources

        merged = merge_sources(
            [[_chunk("a.pdf", 0, "lo", 0.3)], [_chunk("a.pdf", 1, "hi", 0.9)]]
        )
        assert [s["content"] for s in merged] == ["hi", "lo"]

    def test_keeps_distinct_memories_sharing_an_index(self):
        from app.services.agentic import merge_sources

        m1 = {"filename": "memory", "page_number": None, "chunk_index": -1,
              "content": "m1", "similarity": 0.6}
        m2 = {"filename": "memory", "page_number": None, "chunk_index": -1,
              "content": "m2", "similarity": 0.7}
        merged = merge_sources([[m1], [m2]])
        assert {s["content"] for s in merged} == {"m1", "m2"}

    def test_empty_input_returns_empty(self):
        from app.services.agentic import merge_sources

        assert merge_sources([]) == []
        assert merge_sources([[], []]) == []


class TestIsSufficient:
    def test_no_sources_is_insufficient(self):
        from app.services.agentic import is_sufficient

        assert is_sufficient([], min_similarity=0.3, min_strong=2) is False

    def test_all_below_threshold_is_insufficient(self):
        from app.services.agentic import is_sufficient

        weak = [_chunk("a.pdf", 0, "x", 0.1), _chunk("a.pdf", 1, "y", 0.2)]
        assert is_sufficient(weak, min_similarity=0.3, min_strong=1) is False

    def test_enough_strong_sources_is_sufficient(self):
        from app.services.agentic import is_sufficient

        srcs = [_chunk("a.pdf", 0, "x", 0.4), _chunk("a.pdf", 1, "y", 0.9)]
        assert is_sufficient(srcs, min_similarity=0.3, min_strong=2) is True

    def test_threshold_is_inclusive(self):
        from app.services.agentic import is_sufficient

        srcs = [_chunk("a.pdf", 0, "x", 0.3)]
        assert is_sufficient(srcs, min_similarity=0.3, min_strong=1) is True


class TestDepthAwareGeneration:
    def test_short_prompt_is_concise(self):
        from app.services.generation import system_prompt_for

        assert "concise" in system_prompt_for("short").lower()

    def test_long_prompt_is_comprehensive_and_does_not_refuse(self):
        from app.services.generation import system_prompt_for

        prompt = system_prompt_for("long").lower()
        assert "comprehensive" in prompt
        # It must instruct the model NOT to refuse outright on partial context.
        assert "refuse" in prompt

    def test_generate_answer_uses_long_prompt_for_long_depth(self, monkeypatch):
        from app.services import generation

        llm = FakeLLM("the long answer")
        monkeypatch.setattr(
            generation.resolver, "resolve_llm_key", lambda db, p: "k"
        )
        monkeypatch.setattr(generation, "get_llm", lambda *a, **k: llm)
        project = Project(
            owner_id=uuid.uuid4(), llm_provider="openai", llm_model="gpt-4o-mini"
        )

        out = generation.generate_answer(None, project, "Explain X", [], depth="long")

        assert out == "the long answer"
        assert llm.calls[0][0] == generation.system_prompt_for("long")

    def test_generate_answer_defaults_to_short_prompt(self, monkeypatch):
        from app.services import generation

        llm = FakeLLM("short answer")
        monkeypatch.setattr(
            generation.resolver, "resolve_llm_key", lambda db, p: "k"
        )
        monkeypatch.setattr(generation, "get_llm", lambda *a, **k: llm)
        project = Project(
            owner_id=uuid.uuid4(), llm_provider="openai", llm_model="gpt-4o-mini"
        )

        generation.generate_answer(None, project, "what is X", [])

        assert llm.calls[0][0] == generation.system_prompt_for("short")


def _recorder(return_value):
    """A fake callable that records its calls and returns a fixed value."""

    def fn(*args):
        fn.calls.append(args)
        return return_value

    fn.calls = []
    return fn


class TestRunAgenticQuery:
    def test_sufficient_first_round_answers_without_clarifying(self):
        from app.services.agentic import run_agentic_query

        strong = [_chunk("a.pdf", 0, "x", 0.9), _chunk("a.pdf", 1, "y", 0.8)]
        retrieve_fn = _recorder(strong)
        plan_fn = _recorder(["unused"])
        generate_fn = _recorder("ANSWER")
        clarify_fn = _recorder(["unused?"])

        result = run_agentic_query(
            question="what is X",
            retrieve_fn=retrieve_fn,
            plan_fn=plan_fn,
            generate_fn=generate_fn,
            clarify_fn=clarify_fn,
            top_k=5,
            min_similarity=0.3,
            min_strong=2,
            max_rounds=2,
        )

        assert result.needs_clarification is False
        assert result.answer == "ANSWER"
        assert result.depth == "short"
        assert result.sub_queries == ["what is X"]
        assert plan_fn.calls == []  # short question is not decomposed
        assert clarify_fn.calls == []  # no escalation
        assert generate_fn.calls[0][2] == "short"  # depth threaded to generation

    def test_long_question_is_decomposed_and_each_subquery_retrieved(self):
        from app.services.agentic import run_agentic_query

        strong = [_chunk("a.pdf", 0, "x", 0.9), _chunk("a.pdf", 1, "y", 0.8)]
        retrieve_fn = _recorder(strong)
        plan_fn = _recorder(["Explain X and Y", "part: X", "part: Y"])
        generate_fn = _recorder("LONG ANSWER")
        clarify_fn = _recorder(["unused?"])

        result = run_agentic_query(
            question="Explain X and Y",
            retrieve_fn=retrieve_fn,
            plan_fn=plan_fn,
            generate_fn=generate_fn,
            clarify_fn=clarify_fn,
            min_similarity=0.3,
            min_strong=2,
            max_rounds=2,
        )

        assert result.depth == "long"
        assert plan_fn.calls == [("Explain X and Y",)]
        assert result.sub_queries == ["Explain X and Y", "part: X", "part: Y"]
        # round one retrieves every planned sub-query
        assert [c[0] for c in retrieve_fn.calls] == [
            "Explain X and Y", "part: X", "part: Y"
        ]
        assert generate_fn.calls[0][2] == "long"

    def test_insufficient_escalates_to_human_clarification(self):
        from app.services.agentic import run_agentic_query

        weak = [_chunk("a.pdf", 0, "x", 0.05)]
        retrieve_fn = _recorder(weak)
        plan_fn = _recorder(["unused"])
        generate_fn = _recorder("SHOULD NOT BE CALLED")
        clarify_fn = _recorder(["Which topic?", "Which chapter?"])

        result = run_agentic_query(
            question="what is X",
            retrieve_fn=retrieve_fn,
            plan_fn=plan_fn,
            generate_fn=generate_fn,
            clarify_fn=clarify_fn,
            min_similarity=0.3,
            min_strong=2,
            max_rounds=2,
        )

        assert result.needs_clarification is True
        assert result.answer is None
        assert result.clarification_questions == ["Which topic?", "Which chapter?"]
        assert clarify_fn.calls == [("what is X",)]
        assert generate_fn.calls == []  # never fabricate an answer

    def test_retries_another_round_before_giving_up(self):
        from app.services.agentic import run_agentic_query

        weak = [_chunk("a.pdf", 0, "x", 0.05)]
        retrieve_fn = _recorder(weak)
        result = run_agentic_query(
            question="what is X",
            retrieve_fn=retrieve_fn,
            plan_fn=_recorder([]),
            generate_fn=_recorder("x"),
            clarify_fn=_recorder(["?"]),
            min_similarity=0.3,
            min_strong=2,
            max_rounds=2,
        )

        assert result.rounds == 2  # it tried twice before escalating
        assert len(retrieve_fn.calls) == 2  # a second retrieval round happened


class TestRequestClarification:
    def test_parses_clarifying_questions_from_model(self):
        from app.services.agentic import request_clarification

        llm = FakeLLM("Which chapter?\nDo you mean CNNs or RNNs?")
        assert request_clarification(llm, "explain it", 3) == [
            "Which chapter?",
            "Do you mean CNNs or RNNs?",
        ]

    def test_falls_back_to_a_generic_question_when_empty(self):
        from app.services.agentic import request_clarification

        llm = FakeLLM("")
        result = request_clarification(llm, "explain it", 3)
        assert len(result) == 1
        assert "?" in result[0]


class TestClarificationMessage:
    def test_message_introduces_and_bullets_each_question(self):
        from app.services.agentic import clarification_message

        msg = clarification_message(["Which topic?", "Which document?"])
        assert "- Which topic?" in msg
        assert "- Which document?" in msg
        # a human-facing preface, not just a bare list
        assert msg.splitlines()[0].strip() != "- Which topic?"


class TestCondenseQuestion:
    def test_no_history_returns_question_unchanged_without_calling_model(self):
        from app.services.agentic import condense_question

        llm = FakeLLM("should not be used")
        assert condense_question(llm, [], "what is deep learning") == (
            "what is deep learning"
        )
        assert llm.calls == []  # no history → no rewrite, no cost

    def test_rewrites_followup_using_history(self):
        from app.services.agentic import condense_question

        llm = FakeLLM("Give a brief summary of deep learning")
        history = [
            {"question": "what is deep learning", "answer": "It is a subfield of ML."}
        ]
        assert condense_question(llm, history, "give a brief summary") == (
            "Give a brief summary of deep learning"
        )

    def test_falls_back_to_original_when_model_returns_nothing(self):
        from app.services.agentic import condense_question

        llm = FakeLLM("   ")
        history = [{"question": "q", "answer": "a"}]
        assert condense_question(llm, history, "clarify that") == "clarify that"

    def test_only_recent_turns_are_sent_to_the_model(self):
        from app.services.agentic import condense_question

        llm = FakeLLM("standalone")
        history = [
            {"question": "OLDEST", "answer": "old answer"},
            {"question": "MIDDLE", "answer": "mid answer"},
            {"question": "NEWEST", "answer": "new answer"},
        ]
        condense_question(llm, history, "and that?", max_turns=1)
        sent_prompt = llm.calls[0][1]
        assert "NEWEST" in sent_prompt
        assert "OLDEST" not in sent_prompt
