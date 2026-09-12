"""Regression coverage for topic-only hits poisoning later exact-match answers.

Exercise both public query engines with real cache keys and history storage;
provider calls are deterministic and never spend a user's key.
"""
from types import SimpleNamespace

import pytest

from app.services import generation, query, query_cache
from tests.test_query import FakeDB, _project, _src


def _ask(project, question, conversation_id=None, *, streaming=False):
    if streaming:
        events = list(query.run_query_stream(
            FakeDB([10, 0]), project, question, None, conversation_id=conversation_id,
        ))
        assert not [event for event in events if event["type"] == "error"]
        return SimpleNamespace(**next(event["response"] for event in events if event["type"] == "done"))
    return query.run_query(
        FakeDB([10, 0]), project, question, None, None, conversation_id=conversation_id,
    )


@pytest.fixture
def pipeline(monkeypatch):
    calls = {"condense": [], "generate": [], "semantic_read": [], "semantic_write": []}
    monkeypatch.setattr(query.settings, "query_cache_enabled", True)
    monkeypatch.setattr(query.resolver, "resolve_llm_key", lambda *a: "test-only")
    monkeypatch.setattr(query, "get_llm", lambda *a, **kw: object())

    def condense(llm, history, question, max_turns):
        calls["condense"].append(question)
        # Deliberately lossy: the cache must be safe even when rewrites collide.
        return "how to build a basic neural network"

    def generate(db, project, question, sources, depth, **kwargs):
        original = kwargs.get("original_question")
        calls["generate"].append((question, original))
        return "Fresh answer for: " + (original or question)

    def lookup(*args, **kwargs):
        calls["semantic_read"].append(args[2])
        return None, [0.1], None

    monkeypatch.setattr(query.agentic, "condense_question", condense)
    monkeypatch.setattr(query.retrieval, "retrieve", lambda *a, **kw: [_src("pytorch", 0.99)])
    monkeypatch.setattr(query.memory_service, "search_memories", lambda *a, **kw: [])
    monkeypatch.setattr(query.generation, "generate_answer", generate)
    monkeypatch.setattr(query.generation, "generate_answer_stream", lambda *a, **kw: iter([generate(*a, **kw)]))
    monkeypatch.setattr(query.semantic_cache, "lookup", lookup)
    monkeypatch.setattr(query.semantic_cache, "store", lambda *a, **kw: calls["semantic_write"].append(a[2]))
    return calls


@pytest.mark.parametrize("streaming", [False, True])
def test_pasted_followups_never_reuse_a_generic_answer(pipeline, streaming):
    project = _project()
    generic = "how to build a basic neural network"
    _ask(project, generic, "chat", streaming=streaming)
    for followup in [
        "explain in more detailed way",
        "give example program",
        "how to build aa baasic neural nnetwork in that",
        "how to build aa baasic neural nnetwork in that pytorch",
        "neural network in pytorch",
    ]:
        result = _ask(project, followup, "chat", streaming=streaming)
        assert result.cache_layer is None
        assert result.answer == "Fresh answer for: " + followup
        assert pipeline["generate"][-1] == (generic, followup)
    # Follow-up answers neither read nor contaminate the cross-user semantic cache.
    assert pipeline["semantic_read"] == [generic]
    assert pipeline["semantic_write"] == [generic]


@pytest.mark.parametrize("streaming", [False, True])
def test_same_request_and_context_hit_redis_before_condense(pipeline, streaming):
    project = _project()
    for cid in ["first", "retry", "changed"]:
        query._conversations.append_turn(
            str(project.id), cid, "what is pytorch",
            "Tensors and neural networks." if cid != "changed" else "A changed earlier answer.",
        )
    first = _ask(project, "give example program", "first", streaming=streaming)
    second = _ask(project, "give example program", "retry", streaming=streaming)
    assert second.cache_layer == "l1"
    assert first.answer == second.answer
    assert pipeline["condense"] == ["give example program"]
    assert len(pipeline["generate"]) == 1
    third = _ask(project, "give example program", "changed", streaming=streaming)
    assert third.cache_layer is None
    assert len(pipeline["generate"]) == 2


@pytest.mark.parametrize("streaming", [False, True])
def test_different_requests_with_the_same_context_and_rewrite_do_not_collide(pipeline, streaming):
    project = _project()
    for cid in ["detail", "code"]:
        query._conversations.append_turn(str(project.id), cid, "what is pytorch", "A tensor library.")
    _ask(project, "explain in more detailed way", "detail", streaming=streaming)
    code = _ask(project, "give example program", "code", streaming=streaming)
    assert code.cache_layer is None
    assert code.answer == "Fresh answer for: give example program"
    assert len(pipeline["generate"]) == 2


@pytest.mark.parametrize("streaming", [False, True])
def test_unavailable_history_never_reads_or_writes_shared_answers(pipeline, monkeypatch, streaming):
    project = _project()
    monkeypatch.setattr(query._conversations, "read_history", lambda *a: ([], True))
    _ask(project, "give example program", "offline", streaming=streaming)
    assert pipeline["semantic_read"] == pipeline["semantic_write"] == []
    key = query_cache.cache_key(project, "give example program", 5, query._answer_signature(project))
    assert query._cache.get(key) is None


def test_new_policy_orphans_legacy_semantic_signatures():
    project = _project()
    project.content_version = 7
    assert query._answer_signature(project).startswith("request-v2|v7")


def test_buffered_follower_reports_cache_hit(pipeline, monkeypatch):
    from app.services.agentic import AgenticResult

    monkeypatch.setattr(query._cache, "get_or_compute", lambda *a: AgenticResult(
        answer="Leader's answer", sources=[], depth="short", sub_queries=[],
        rounds=1, needs_clarification=False,
    ))
    result = _ask(_project(), "what is pytorch")
    assert result.cache_layer == "l1"
    assert result.answer == "Leader's answer"
    assert pipeline["generate"] == []


def test_generation_prompt_preserves_raw_followup_alongside_topic():
    prompt = generation.build_user_prompt(
        "how to build a basic neural network", [_src("pytorch", 0.99)], "give example program",
    )
    assert "Resolved conversation topic: how to build a basic neural network" in prompt
    assert prompt.endswith("Current user request: give example program")


@pytest.mark.parametrize("raw", ["not json", "[]", '{"unknown_field":true}'])
def test_corrupt_cached_payload_is_a_miss(raw):
    backend = query_cache.InMemoryBackend()
    cache = query_cache.QueryCache(backend, 60, deserialize=query._deserialize_result)
    backend.set("cache:question", raw, 60)
    assert cache.get("question") is None


@pytest.mark.parametrize("raw", ["not json", "{}", '[{"question":"q"}]'])
def test_corrupt_history_is_unavailable_and_is_not_overwritten(raw):
    backend = query_cache.InMemoryBackend()
    store = query_cache.ConversationStore(backend, 60)
    backend.set("conv:project:chat", raw, 60)
    assert store.read_history("project", "chat") == ([], True)
    store.append_turn("project", "chat", "new", "answer")
    assert backend.get("conv:project:chat") == raw
