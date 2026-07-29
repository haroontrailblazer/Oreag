"""Unit tests for CAG storage: pluggable backends (in-memory / Redis), the query
cache built on top, and server-side conversation memory.

A backend is just get/set(ttl)/delete/clear over strings. The in-memory backend
is the local-dev/test default; the Redis backend (tested here with a fake client,
no server) is selected when REDIS_URL is configured. The query cache and the
conversation store both ride on whichever backend is active.

Single-flight is covered at both levels: per-process (the plain lock) and
fleet-wide (the Redis SET NX lock), the latter driven by two QueryCache objects
sharing one fake client - that is what "two app instances" looks like in a unit
test.
"""
import threading
import time
import uuid

import pytest

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
    """Minimal stand-in for a redis client: get/set(ex|nx|px)/delete/eval over a
    dict, guarded by a lock because real Redis executes one command at a time
    (the concurrency tests below drive it from several threads).

    ``eval`` implements the ONE script we send - the compare-and-delete lock
    release - since that is where the release's atomicity actually lives.
    """

    def __init__(self):
        self.store = {}
        self.last_ex = None
        self.last_px = None
        self._guard = threading.Lock()

    def get(self, key):
        with self._guard:
            return self.store.get(key)

    def set(self, key, value, ex=None, nx=False, px=None):
        with self._guard:
            if nx and key in self.store:
                return None  # redis-py returns None when NX didn't apply
            self.last_ex = ex
            self.last_px = px
            self.store[key] = value.encode() if isinstance(value, str) else value
            return True

    def delete(self, *keys):
        with self._guard:
            for key in keys:
                self.store.pop(key, None)

    def eval(self, script, numkeys, *args):
        from app.services.query_cache import _RELEASE_IF_MINE

        assert script == _RELEASE_IF_MINE, "unexpected Lua script"
        keys, argv = args[:numkeys], args[numkeys:]
        with self._guard:
            current = self.store.get(keys[0])
            if current is not None and current.decode() == argv[0]:
                del self.store[keys[0]]
                return 1
            return 0

    def expire_now(self, key):
        """Simulate a lock's TTL lapsing while its holder is still running."""
        with self._guard:
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
        assert self._store().get_history("p1", "cid-1") == []

    def test_append_then_get_returns_turns_in_order(self):
        store = self._store()
        store.append_turn("p1", "cid", "q1", "a1")
        store.append_turn("p1", "cid", "q2", "a2")
        assert store.get_history("p1", "cid") == [
            {"question": "q1", "answer": "a1"},
            {"question": "q2", "answer": "a2"},
        ]

    def test_history_is_capped_to_max_turns(self):
        store = self._store(max_turns=2)
        for i in range(4):
            store.append_turn("p1", "cid", f"q{i}", f"a{i}")
        history = store.get_history("p1", "cid")
        assert len(history) == 2
        assert history[0]["question"] == "q2"  # oldest dropped

    def test_conversations_are_isolated_by_id(self):
        store = self._store()
        store.append_turn("p1", "a", "qa", "aa")
        store.append_turn("p1", "b", "qb", "ab")
        assert store.get_history("p1", "a") == [{"question": "qa", "answer": "aa"}]
        assert store.get_history("p1", "b") == [{"question": "qb", "answer": "ab"}]

    def test_same_conversation_id_is_isolated_across_scopes(self):
        """conversation_id is caller-chosen: two tenants both picking "session-1"
        must never read or corrupt each other's history on a shared backend."""
        store = self._store()
        store.append_turn("project-A", "session-1", "qa", "aa")
        store.append_turn("project-B", "session-1", "qb", "ab")
        assert store.get_history("project-A", "session-1") == [
            {"question": "qa", "answer": "aa"}
        ]
        assert store.get_history("project-B", "session-1") == [
            {"question": "qb", "answer": "ab"}
        ]


class _ExplodingRedis:
    """Mimics redis-py's surface but every call fails like an outage would."""

    def get(self, key):
        raise ConnectionError("redis down")

    def set(self, key, value, ex=None, nx=False, px=None):
        raise ConnectionError("redis down")

    def delete(self, key):
        raise ConnectionError("redis down")

    def eval(self, script, numkeys, *args):
        raise ConnectionError("redis down")


class _FlakyGetRedis:
    """The dangerous outage shape: reads fail but writes succeed (redis-py
    discards a timed-out connection, so the next command gets a fresh one)."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        raise ConnectionError("redis read timed out")

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


class TestRedisBackendDegradesOnOutage:
    """A cache/conversation backend must degrade to 'miss', never raise: an
    unhandled Redis error here would 500 every /v1 query."""

    def _backend(self):
        from app.services.query_cache import RedisBackend

        return RedisBackend(_ExplodingRedis())

    def test_cache_get_treats_outage_as_miss(self):
        import json

        from app.services.query_cache import QueryCache

        cache = QueryCache(self._backend(), ttl_seconds=60, serialize=json.dumps,
                           deserialize=json.loads)
        assert cache.get("k") is None

    def test_set_is_a_noop(self):
        self._backend().set("k", "v", 60)  # must not raise

    def test_delete_is_a_noop(self):
        self._backend().delete("k")  # must not raise

    def test_history_read_degrades_to_empty(self):
        from app.services.query_cache import ConversationStore

        store = ConversationStore(self._backend(), ttl_seconds=60)
        assert store.get_history("p1", "cid") == []

    def test_append_turn_never_overwrites_history_after_failed_read(self):
        """append_turn is read-modify-write: if the read degraded to [] but the
        write would succeed, writing must be SKIPPED - otherwise a 20-turn
        conversation gets silently replaced by a one-turn stub."""
        from app.services.query_cache import ConversationStore, RedisBackend

        flaky = _FlakyGetRedis()
        flaky.store["conv:p1:cid"] = '[{"question": "old", "answer": "history"}]'
        store = ConversationStore(RedisBackend(flaky), ttl_seconds=60)

        returned = store.append_turn("p1", "cid", "new q", "new a")

        # The caller still gets the turn it just made...
        assert returned == [{"question": "new q", "answer": "new a"}]
        # ...but the stored history was NOT clobbered.
        assert flaky.store["conv:p1:cid"] == '[{"question": "old", "answer": "history"}]'


def _instance(client, **kwargs):
    """One app instance's QueryCache over a shared Redis - separate process
    state (its own in-process locks), same fleet-wide backend."""
    from app.services.query_cache import QueryCache, RedisBackend

    kwargs.setdefault("ttl_seconds", 60)
    return QueryCache(RedisBackend(client), **kwargs)


class TestFlightLockSemantics:
    """flight_lock's return value must keep behaving like the threading.Lock it
    replaced - services/query.py drives it by hand (acquire/release/`with`)."""

    def test_in_memory_backend_keeps_the_plain_per_process_lock(self):
        from app.services.query_cache import InMemoryBackend, QueryCache

        cache = QueryCache(InMemoryBackend(clock=_Clock(0)), ttl_seconds=60)
        lock = cache.flight_lock("k")
        assert lock.acquire(blocking=False) is True
        assert cache.flight_lock("k").acquire(blocking=False) is False  # held
        assert lock.locked() is True
        lock.release()
        assert cache.flight_lock("k").acquire(blocking=False) is True

    def test_works_as_a_context_manager(self):
        client = _FakeRedis()
        cache = _instance(client)
        with cache.flight_lock("k"):
            assert "flight:k" in client.store  # the fleet-wide lock is held
        assert "flight:k" not in client.store  # ...and released on exit

    def test_locks_are_scoped_per_key(self):
        client = _FakeRedis()
        cache = _instance(client)
        first = cache.flight_lock("a")
        assert first.acquire(blocking=False) is True
        assert cache.flight_lock("b").acquire(blocking=False) is True
        first.release()


class TestRedisSingleFlightAcrossInstances:
    """The Phase 3 point of the Redis lock: with several app instances, the
    leader must be elected across the fleet, not once per process."""

    def test_leader_takes_the_lock_and_another_instance_cannot(self):
        client = _FakeRedis()
        one, two = _instance(client), _instance(client)

        leader = one.flight_lock("k")
        assert leader.acquire(blocking=False) is True
        token = client.store["flight:k"]
        assert token  # a unique token, not a fixed marker

        follower = two.flight_lock("k")
        assert follower.acquire(blocking=False) is False
        assert client.store["flight:k"] == token  # a loser never overwrites it

        leader.release()
        assert "flight:k" not in client.store
        assert follower.acquire(blocking=False) is True
        follower.release()

    def test_each_acquisition_gets_a_fresh_token(self):
        client = _FakeRedis()
        cache = _instance(client)
        lock = cache.flight_lock("k")
        lock.acquire(blocking=False)
        first = client.store["flight:k"]
        lock.release()
        lock.acquire(blocking=False)
        assert client.store["flight:k"] != first
        lock.release()

    def test_lock_carries_a_ttl_so_a_crashed_leader_frees_it(self):
        client = _FakeRedis()
        cache = _instance(client, flight_ttl_seconds=90.0)
        lock = cache.flight_lock("k")
        lock.acquire(blocking=False)
        assert client.last_px == 90_000  # milliseconds, as SET PX wants
        lock.release()

    def test_follower_waits_then_serves_the_leaders_cached_value(self):
        """The whole point: instance B must NOT run its own copy of the
        pipeline while instance A is already computing the same answer."""
        client = _FakeRedis()
        one, two = _instance(client), _instance(client)
        calls: list[str] = []
        leading = threading.Event()
        finish = threading.Event()
        results: dict[str, object] = {}

        def leader_compute():
            calls.append("leader")
            leading.set()
            finish.wait(timeout=3)
            return {"answer": "FROM THE LEADER"}

        def follower_compute():
            calls.append("follower")
            return {"answer": "DUPLICATE WORK"}

        def lead():
            results["one"] = one.get_or_compute("k", leader_compute)

        def follow():
            results["two"] = two.get_or_compute("k", follower_compute)

        leader = threading.Thread(target=lead)
        leader.start()
        assert leading.wait(timeout=3)

        follower = threading.Thread(target=follow)
        follower.start()
        time.sleep(0.2)  # long enough that an unlocked follower would have run
        assert calls == ["leader"]

        finish.set()
        leader.join(timeout=3)
        follower.join(timeout=3)

        assert calls == ["leader"]  # computed once for the whole fleet
        assert results["one"] == {"answer": "FROM THE LEADER"}
        assert results["two"] == {"answer": "FROM THE LEADER"}

    def test_follower_falls_through_and_computes_when_the_wait_expires(self):
        """A wedged leader must not park followers forever: past the wait
        budget a follower computes on its own (correctness over dedup)."""
        client = _FakeRedis()
        one = _instance(client)
        two = _instance(client, flight_wait_seconds=0.1)

        stuck = one.flight_lock("k")
        assert stuck.acquire(blocking=False) is True  # leads and never finishes

        calls = []

        def compute():
            calls.append(1)
            return {"answer": "SELF SERVED"}

        started = time.monotonic()
        assert two.get_or_compute("k", compute) == {"answer": "SELF SERVED"}
        assert calls == [1]
        assert time.monotonic() - started >= 0.1  # it really did wait first

        # The follower gave the local slot back on the way out, so this
        # instance can lead the next flight for the same key.
        stuck.release()
        after = two.flight_lock("k")
        assert after.acquire(blocking=False) is True
        after.release()

    def test_a_failed_leader_frees_the_lock_instead_of_wedging_the_fleet(self):
        """A leader whose compute raises must release the fleet-wide lock on
        the way out. Otherwise one upstream 500 parks every other instance
        asking that question for a whole flight TTL."""
        client = _FakeRedis()
        one, two = _instance(client), _instance(client)

        def explode():
            raise RuntimeError("provider blew up")

        with pytest.raises(RuntimeError):
            one.get_or_compute("k", explode)

        assert "flight:k" not in client.store  # released, not left to expire
        assert one.get("k") is None  # and the failure was NOT cached
        successor = two.flight_lock("k")
        assert successor.acquire(blocking=False) is True  # no waiting for TTL
        successor.release()

    def test_the_lock_and_the_answer_it_guards_never_clobber_each_other(self):
        """Both are keyed by the same cache key, so they need separate
        namespaces: a lock written over the answer would drop a fresh cache
        entry, and an answer written over the lock would hand a second leader
        the flight."""
        client = _FakeRedis()
        cache = _instance(client)
        cache.set("k", {"answer": "A"})

        lock = cache.flight_lock("k")
        assert lock.acquire(blocking=False) is True
        assert sorted(client.store) == ["cache:k", "flight:k"]
        assert cache.get("k") == {"answer": "A"}  # survives the lock

        lock.release()
        assert cache.get("k") == {"answer": "A"}  # survives the release
        assert "flight:k" not in client.store

    def test_release_never_deletes_a_newer_leaders_lock(self):
        """A leader slower than the TTL wakes up holding a stale token. Its
        release must be a no-op, not a delete of the lock its successor now
        holds - otherwise a third caller leads alongside the second."""
        client = _FakeRedis()
        one, two = _instance(client), _instance(client)

        slow = one.flight_lock("k")
        assert slow.acquire(blocking=False) is True
        client.expire_now("flight:k")  # the TTL lapses mid-flight

        successor = two.flight_lock("k")
        assert successor.acquire(blocking=False) is True
        successor_token = client.store["flight:k"]

        slow.release()  # the stale leader finally finishes
        assert client.store["flight:k"] == successor_token  # untouched

        successor.release()
        assert "flight:k" not in client.store

    def test_a_double_release_cannot_reach_a_later_lock(self):
        from app.services.query_cache import RedisBackend

        client = _FakeRedis()
        cache = _instance(client)
        lock = cache.flight_lock("k")
        lock.acquire(blocking=False)
        lock.release()

        RedisBackend(client).lock_acquire("flight:k", "someone-elses", 60)
        try:
            lock.release()  # threading.Lock raises on an unheld release
        except RuntimeError:
            pass
        assert client.store["flight:k"] == b"someone-elses"


class _LockBlindRedis(_FakeRedis):
    """Reads and writes work, but the LOCK commands (SET NX, EVAL) fail.

    The partial outage that isolates the fallback: the answer cache is still
    shared, so the only thing a failed lock can cost is fleet-wide dedup.
    """

    def set(self, key, value, ex=None, nx=False, px=None):
        if nx:
            raise ConnectionError("redis down")
        return super().set(key, value, ex=ex)

    def eval(self, script, numkeys, *args):
        raise ConnectionError("redis down")


class TestFlightLockDegradesWhenRedisIsDown:
    """Fail open: a Redis outage costs cross-instance dedup, never the query."""

    def test_outage_falls_back_to_the_in_process_lock(self):
        cache = _instance(_ExplodingRedis())
        lock = cache.flight_lock("k")
        assert lock.acquire(blocking=False) is True  # led anyway
        assert cache.flight_lock("k").acquire(blocking=False) is False  # local
        lock.release()  # must not raise even though the release call fails

    def test_single_flight_still_dedupes_within_the_process(self):
        cache = _instance(_LockBlindRedis())
        calls = []
        results = []
        ready = threading.Event()
        release = threading.Event()
        barrier = threading.Barrier(2)

        def compute():
            calls.append(1)
            ready.set()
            release.wait(timeout=2)
            return {"answer": "V"}

        def worker():
            barrier.wait()
            results.append(cache.get_or_compute("k", compute))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        ready.wait(timeout=2)
        release.set()
        for thread in threads:
            thread.join(timeout=3)

        assert len(calls) == 1  # the in-process lock is intact
        assert results == [{"answer": "V"}, {"answer": "V"}]

    def test_dedup_degrades_to_per_process_not_to_an_error(self):
        """Honest about what is lost: with the lock layer down, two instances
        can both lead - exactly the behaviour before this change - instead of
        one of them failing."""
        client = _LockBlindRedis()
        one, two = _instance(client), _instance(client)
        assert one.flight_lock("k").acquire(blocking=False) is True
        assert two.flight_lock("k").acquire(blocking=False) is True

    def test_backend_lock_helpers_report_the_outage_instead_of_raising(self):
        from app.services.query_cache import UNAVAILABLE, RedisBackend

        backend = RedisBackend(_ExplodingRedis())
        assert backend.lock_acquire("flight:k", "tok", 60) is UNAVAILABLE
        backend.lock_release("flight:k", "tok")  # must not raise
