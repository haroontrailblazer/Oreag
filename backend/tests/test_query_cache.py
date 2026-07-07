"""Unit tests for CAG storage: pluggable backends (in-memory / Redis), the query
cache built on top, and server-side conversation memory.

A backend is just get/set(ttl)/delete/clear over strings. The in-memory backend
is the local-dev/test default; the Redis backend (tested here with a fake client,
no server) is selected when REDIS_URL is configured. The query cache and the
conversation store both ride on whichever backend is active.
"""
import threading
import uuid

from app.models import Project


def _project(llm_model="gpt-4o-mini", embedding_model="text-embedding-3-small"):
    return Project(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        top_k=5,
        embedding_provider="openai",
        embedding_model=embedding_model,
        llm_provider="openai",
        llm_model=llm_model,
    )


class _Clock:
    """A controllable monotonic clock for deterministic TTL tests."""

    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class TestCacheKey:
    def test_normalizes_case_and_whitespace(self):
        from app.services.query_cache import cache_key

        project = _project()
        a = cache_key(project, "What is  X?", 5, "10:0")
        b = cache_key(project, "what is x?", 5, "10:0")
        assert a == b

    def test_same_question_in_any_case_shares_the_l1_entry(self):
        # An exact repeat asked in caps, lower, or with different trailing
        # punctuation must map to ONE L1 key (a true exact-match hit), not fall
        # through to the semantic layer.
        from app.services.query_cache import cache_key, normalize_question

        project = _project()
        variants = [
            "what is pytorch",
            "WHAT IS PYTORCH",
            "What Is PyTorch?",
            "  what   is   pytorch!!  ",
        ]
        keys = {cache_key(project, v, 5, "10:0") for v in variants}
        assert len(keys) == 1
        assert normalize_question("What Is PyTorch?") == "what is pytorch"

    def test_different_question_differs(self):
        from app.services.query_cache import cache_key

        project = _project()
        assert cache_key(project, "what is X", 5, "10:0") != cache_key(
            project, "what is Y", 5, "10:0"
        )

    def test_content_signature_invalidates(self):
        from app.services.query_cache import cache_key

        project = _project()
        assert cache_key(project, "q", 5, "10:0") != cache_key(
            project, "q", 5, "11:0"
        )

    def test_model_and_top_k_differ(self):
        from app.services.query_cache import cache_key

        assert cache_key(_project(llm_model="gpt-4o"), "q", 5, "10:0") != cache_key(
            _project(llm_model="gpt-4o-mini"), "q", 5, "10:0"
        )
        project = _project()
        assert cache_key(project, "q", 5, "10:0") != cache_key(project, "q", 8, "10:0")


class TestInMemoryBackend:
    def test_set_then_get(self):
        from app.services.query_cache import InMemoryBackend

        backend = InMemoryBackend(clock=_Clock(0))
        backend.set("k", "v", 60)
        assert backend.get("k") == "v"
        assert backend.get("missing") is None

    def test_entry_expires(self):
        from app.services.query_cache import InMemoryBackend

        clock = _Clock(0)
        backend = InMemoryBackend(clock=clock)
        backend.set("k", "v", 60)
        clock.advance(61)
        assert backend.get("k") is None

    def test_delete_and_clear(self):
        from app.services.query_cache import InMemoryBackend

        backend = InMemoryBackend(clock=_Clock(0))
        backend.set("k", "v", 60)
        backend.delete("k")
        assert backend.get("k") is None
        backend.set("a", "1", 60)
        backend.set("b", "2", 60)
        backend.clear()
        assert backend.get("a") is None and backend.get("b") is None

    def test_lru_eviction(self):
        from app.services.query_cache import InMemoryBackend

        backend = InMemoryBackend(clock=_Clock(0), max_entries=2)
        backend.set("a", "1", 60)
        backend.set("b", "2", 60)
        backend.set("c", "3", 60)  # evicts the least-recently-used "a"
        assert backend.get("a") is None
        assert backend.get("b") == "2" and backend.get("c") == "3"


class _FakeRedis:
    """Minimal stand-in for a redis client: get/set(ex)/delete over a dict."""

    def __init__(self):
        self.store = {}
        self.last_ex = None

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.last_ex = ex
        self.store[key] = value.encode() if isinstance(value, str) else value

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)


class TestRedisBackend:
    def test_get_decodes_bytes_and_set_passes_ttl(self):
        from app.services.query_cache import RedisBackend

        client = _FakeRedis()
        backend = RedisBackend(client)
        backend.set("k", "v", 120)
        assert client.last_ex == 120  # TTL forwarded to redis as expiry
        assert backend.get("k") == "v"  # bytes decoded back to str

    def test_missing_key_is_none_and_delete(self):
        from app.services.query_cache import RedisBackend

        backend = RedisBackend(_FakeRedis())
        assert backend.get("nope") is None
        backend.set("k", "v", 60)
        backend.delete("k")
        assert backend.get("k") is None


class TestMakeBackend:
    def test_no_url_falls_back_to_in_memory(self):
        from app.services.query_cache import InMemoryBackend, make_backend

        assert isinstance(make_backend(""), InMemoryBackend)


class TestQueryCache:
    def _cache(self, clock=None):
        from app.services.query_cache import InMemoryBackend, QueryCache

        return QueryCache(InMemoryBackend(clock=clock or _Clock(0)), ttl_seconds=60)

    def test_miss_computes_then_hit_serves_cached(self):
        calls = []
        cache = self._cache()

        def compute():
            calls.append(1)
            return {"answer": "VALUE"}

        assert cache.get_or_compute("k", compute) == {"answer": "VALUE"}
        assert cache.get_or_compute("k", compute) == {"answer": "VALUE"}
        assert len(calls) == 1  # second call served from cache

    def test_value_round_trips_through_serialization(self):
        cache = self._cache()
        cache.set("k", {"a": 1, "b": ["x", "y"]})
        assert cache.get("k") == {"a": 1, "b": ["x", "y"]}

    def test_entry_expires_after_ttl(self):
        calls = []
        clock = _Clock(0)
        cache = self._cache(clock)

        def compute():
            calls.append(1)
            return "V"

        cache.get_or_compute("k", compute)
        clock.advance(61)
        cache.get_or_compute("k", compute)
        assert len(calls) == 2

    def test_single_flight_computes_once_under_concurrency(self):
        cache = self._cache()
        calls = []
        results = []
        ready = threading.Event()
        release = threading.Event()
        barrier = threading.Barrier(2)

        def compute():
            calls.append(1)
            ready.set()
            release.wait(timeout=2)
            return "V"

        def worker():
            barrier.wait()
            results.append(cache.get_or_compute("k", compute))

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        ready.wait(timeout=2)
        release.set()
        t1.join(timeout=2)
        t2.join(timeout=2)

        assert len(calls) == 1
        assert results == ["V", "V"]


class TestConversationStore:
    def _store(self, clock=None, max_turns=20):
        from app.services.query_cache import ConversationStore, InMemoryBackend

        return ConversationStore(
            InMemoryBackend(clock=clock or _Clock(0)),
            ttl_seconds=3600,
            max_turns=max_turns,
        )

    def test_unknown_conversation_has_empty_history(self):
        assert self._store().get_history("cid-1") == []

    def test_append_then_get_returns_turns_in_order(self):
        store = self._store()
        store.append_turn("cid", "q1", "a1")
        store.append_turn("cid", "q2", "a2")
        assert store.get_history("cid") == [
            {"question": "q1", "answer": "a1"},
            {"question": "q2", "answer": "a2"},
        ]

    def test_history_is_capped_to_max_turns(self):
        store = self._store(max_turns=2)
        for i in range(4):
            store.append_turn("cid", f"q{i}", f"a{i}")
        history = store.get_history("cid")
        assert len(history) == 2
        assert history[0]["question"] == "q2"  # oldest dropped

    def test_conversations_are_isolated_by_id(self):
        store = self._store()
        store.append_turn("a", "qa", "aa")
        store.append_turn("b", "qb", "ab")
        assert store.get_history("a") == [{"question": "qa", "answer": "aa"}]
        assert store.get_history("b") == [{"question": "qb", "answer": "ab"}]
