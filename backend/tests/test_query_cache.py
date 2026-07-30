"""Unit tests for CAG storage: pluggable backends (in-memory / Redis), the query
cache built on top, and server-side conversation memory.

A backend is just get/set(ttl)/delete/clear over strings. The in-memory backend
is the local-dev/test default; the Redis backend (tested here with a fake client,
no server) is selected when REDIS_URL is configured. The query cache and the
conversation store both ride on whichever backend is active.

Single-flight is covered at both levels: per-process (the plain lock) and
fleet-wide (the Redis SET NX lock), the latter driven by two QueryCache objects
sharing one fake client - that is what "two app instances" looks like in a unit
test. Two properties of that lock get their own sections at the bottom: when a
Redis outage may promote a waiter to leader, and the leader's heartbeat that
keeps a slow generation from losing its lock mid-flight.
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

    ``eval`` implements the TWO scripts we send - the compare-and-delete lock
    release and the compare-and-pexpire renewal - since that is where their
    atomicity actually lives. Renewals are recorded in ``pexpires`` so a test
    can watch a leader's heartbeat.
    """

    def __init__(self):
        self.store = {}
        self.last_ex = None
        self.last_px = None
        self.pexpires = []  # (key, token, milliseconds) per successful renewal
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
        from app.services.query_cache import _EXTEND_IF_MINE, _RELEASE_IF_MINE

        assert script in (_RELEASE_IF_MINE, _EXTEND_IF_MINE), "unexpected Lua script"
        keys, argv = args[:numkeys], args[numkeys:]
        with self._guard:
            current = self.store.get(keys[0])
            if current is None or current.decode() != argv[0]:
                return 0  # gone, or somebody else's - both scripts no-op
            if script == _RELEASE_IF_MINE:
                del self.store[keys[0]]
            else:
                # PEXPIRE only re-arms the clock; the value stays put.
                self.pexpires.append((keys[0], argv[0], int(argv[1])))
            return 1

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
        assert backend.lock_extend("flight:k", "tok", 60) is UNAVAILABLE
        backend.lock_release("flight:k", "tok")  # must not raise


class _LockBlipRedis(_FakeRedis):
    """Answers the first ``healthy_acquires`` SET NX calls honestly, then goes
    dark for every later one.

    The blip that matters: by the time it starts failing, Redis has already
    told a waiter that somebody else holds the flight.
    """

    def __init__(self, healthy_acquires=1):
        super().__init__()
        self.healthy_acquires = healthy_acquires
        self.nx_calls = 0

    def set(self, key, value, ex=None, nx=False, px=None):
        if nx:
            self.nx_calls += 1
            if self.nx_calls > self.healthy_acquires:
                raise ConnectionError("redis blipped")
        return super().set(key, value, ex=ex, nx=nx, px=px)


class _ExpiringFakeRedis(_FakeRedis):
    """A fake that actually honours PX and PEXPIRE, on the real clock.

    The plain fake never expires anything, so it cannot tell apart a leader
    that renews its lock from one that silently loses it mid-flight.
    """

    def __init__(self):
        super().__init__()
        self.expiries = {}

    def _evict(self):
        now = time.monotonic()
        for key in [k for k, at in self.expiries.items() if now >= at]:
            del self.expiries[key]
            self.store.pop(key, None)

    def get(self, key):
        with self._guard:
            self._evict()
            return self.store.get(key)

    def set(self, key, value, ex=None, nx=False, px=None):
        with self._guard:
            self._evict()
            if nx and key in self.store:
                return None
            self.last_ex, self.last_px = ex, px
            self.store[key] = value.encode() if isinstance(value, str) else value
            if px is not None:
                self.expiries[key] = time.monotonic() + px / 1000.0
            elif ex is not None:
                self.expiries[key] = time.monotonic() + ex
            return True

    def eval(self, script, numkeys, *args):
        from app.services.query_cache import _RELEASE_IF_MINE

        keys, argv = args[:numkeys], args[numkeys:]
        with self._guard:
            self._evict()
            current = self.store.get(keys[0])
            if current is None or current.decode() != argv[0]:
                return 0
            if script == _RELEASE_IF_MINE:
                del self.store[keys[0]]
                self.expiries.pop(keys[0], None)
            else:
                self.pexpires.append((keys[0], argv[0], int(argv[1])))
                self.expiries[keys[0]] = time.monotonic() + int(argv[1]) / 1000.0
            return 1


class TestWhatAnUnreachableLockStoreCosts:
    """A lock cannot exclude anyone while the store that defines it is dark, so
    these are the two degradations we choose between - never right vs. wrong.

    Lead, and two instances may compute the same answer (per-process
    single-flight, the pre-Redis behaviour). Follow, and the request stalls for
    its whole budget on a leader nobody can confirm exists, then computes
    anyway. So: follow through a short grace, because a blip that heals inside
    it buys real exclusion back, and lead after it. The last test in this class
    states the limit that leaves, so no comment here can quietly claim more.
    """

    def test_first_attempt_unavailable_still_leads(self):
        """This process has never reached the store, so it has no leader to
        follow and no way to be elected either: leading is the only move that
        answers the query."""
        cache = _instance(_LockBlindRedis())
        lock = cache.flight_lock("k")
        started = time.monotonic()
        assert lock.acquire(timeout=5.0) is True  # led...
        assert time.monotonic() - started < 1.0  # ...at once, not after waiting
        lock.release()

    def test_a_later_unavailable_does_not_promote_a_follower(self):
        # #1 is the leader's acquire, #2 the follower's first poll (which is
        # told the lock is held); every poll after that blips.
        client = _LockBlipRedis(healthy_acquires=2)
        one, two = _instance(client), _instance(client)

        leader = one.flight_lock("k")
        assert leader.acquire(blocking=False) is True
        held = client.store["flight:k"]

        follower = two.flight_lock("k")
        started = time.monotonic()
        assert follower.acquire(timeout=0.3) is False  # stayed a follower
        assert time.monotonic() - started >= 0.3  # by waiting, not by leading
        assert client.nx_calls > 2  # it really did keep polling
        assert client.store["flight:k"] == held  # never took the lock over

        # ...and it handed the local slot back on the way out, as always.
        after = two.flight_lock("k")
        assert after.acquire(blocking=False) is True
        after.release()
        leader.release()

    def test_a_later_unavailable_does_not_fail_the_query_either(self):
        """The follower falls through and computes for itself: an outage costs
        dedup, never the answer."""
        client = _LockBlipRedis(healthy_acquires=2)
        one = _instance(client)
        two = _instance(client, flight_wait_seconds=0.2)

        stuck = one.flight_lock("k")
        assert stuck.acquire(blocking=False) is True

        assert two.get_or_compute("k", lambda: {"answer": "SELF SERVED"}) == {
            "answer": "SELF SERVED"
        }
        stuck.release()

    def test_the_store_being_seen_is_remembered_across_flight_locks(self):
        """"Could a leader have been elected?" is a fact about the STORE, not
        about one request. A flight lock is built per request, so a per-lock
        flag forgets it on every new one - and then every waiter during an
        outage promotes itself, which is the shape this is here to narrow."""
        client = _LockBlipRedis(healthy_acquires=1)  # only the leader gets an answer
        cache = _instance(client)

        leader = cache.flight_lock("k")
        assert leader.acquire(blocking=False) is True  # the store answered us

        # A brand new lock object (different key, so its local slot is free),
        # with the store dark from here on. It still knows.
        started = time.monotonic()
        assert cache.flight_lock("other").acquire(timeout=0.3) is False
        assert time.monotonic() - started >= 0.3  # it followed, it did not lead

        # ...whereas an instance that never reached the store has nothing to
        # remember, and leads at once.
        elsewhere = _instance(client).flight_lock("other")
        assert elsewhere.acquire(blocking=False) is True
        elsewhere.release()
        leader.release()

    def test_a_sustained_outage_leads_after_the_grace_instead_of_stalling(self):
        """Following forever is not on the menu: with the store dark nothing
        will ever name the leader, so a waiter that kept following would spend
        its whole budget and then compute anyway - later, and without even the
        in-process lock to dedup behind."""
        from app.services.query_cache import RedisBackend, _FlightLock

        seen = threading.Event()
        seen.set()  # the store HAS answered this process before
        lock = _FlightLock(
            threading.Lock(),
            "flight:k",
            backend=RedisBackend(_LockBlindRedis()),
            ttl_seconds=60.0,
            outage_grace_seconds=0.1,
            store_seen=seen,
        )
        started = time.monotonic()
        assert lock.acquire(timeout=30.0) is True  # led...
        assert 0.1 <= time.monotonic() - started < 5.0  # ...after the grace, not the budget
        assert lock._token is None  # holding nothing fleet-wide, so...
        assert lock._heartbeat_thread is None  # ...there is nothing to renew
        lock.release()

    def test_an_outage_after_election_can_still_produce_two_leaders(self):
        """The honest limit, pinned so nothing can quietly claim otherwise.

        A leader is elected while the store is healthy; the store then goes
        dark; a SECOND instance - a different process, with no memory of the
        first - leads too. That is per-process single-flight, exactly the
        pre-Redis behaviour, and no lock can do better than its store.
        """
        client = _LockBlipRedis(healthy_acquires=1)
        one, two = _instance(client), _instance(client)

        a = one.flight_lock("k")
        assert a.acquire(blocking=False) is True  # elected through a healthy store
        assert a._token is not None  # ...and really holds the fleet-wide lock

        b = two.flight_lock("k")
        assert b.acquire(blocking=False) is True  # and so does B, with it dark
        assert b._token is None  # holding nothing fleet-wide: no remote lock
        b.release()
        a.release()


class TestLeaderRenewsItsLockWhileItWorks:
    """The flight TTL bounds a leader that DIED, not one that is merely slow.

    Unrenewed, a generation longer than the TTL dropped its lock mid-flight
    and a waiting follower was promoted to a second leader computing the same
    answer - the duplicate work the fleet-wide lock is there to stop.
    """

    def test_the_lock_is_extended_while_the_leader_works(self):
        client = _FakeRedis()
        cache = _instance(client, flight_ttl_seconds=0.3)  # a beat every 0.1s
        lock = cache.flight_lock("k")
        assert lock.acquire(blocking=False) is True
        token = client.store["flight:k"].decode()
        try:
            deadline = time.monotonic() + 3.0
            while len(client.pexpires) < 2 and time.monotonic() < deadline:
                time.sleep(0.02)
        finally:
            lock.release()

        assert len(client.pexpires) >= 2  # renewed, and kept being renewed
        # Every renewal is OUR token, re-armed to a whole fresh TTL.
        assert all(
            entry == ("flight:k", token, 300) for entry in client.pexpires
        ), client.pexpires

    def test_a_leader_slower_than_the_ttl_keeps_the_flight(self):
        client = _ExpiringFakeRedis()
        one = _instance(client, flight_ttl_seconds=0.3)
        two = _instance(client, flight_ttl_seconds=0.3)

        leader = one.flight_lock("k")
        assert leader.acquire(blocking=False) is True
        try:
            time.sleep(0.75)  # two whole TTLs of "still generating"
            # Unrenewed the lock would have lapsed by now and this would lead.
            assert two.flight_lock("k").acquire(blocking=False) is False
        finally:
            leader.release()

        successor = two.flight_lock("k")
        assert successor.acquire(blocking=False) is True  # free the moment it ends
        successor.release()

    def test_extend_cannot_touch_a_foreign_token(self):
        """The renewal is compare-and-pexpire for the same reason the release
        is compare-and-delete: a stale leader must never keep its successor's
        lock alive."""
        from app.services.query_cache import RedisBackend

        client = _FakeRedis()
        backend = RedisBackend(client)
        assert backend.lock_acquire("flight:k", "the-owner", 60) is True

        assert backend.lock_extend("flight:k", "a-stale-leader", 60) is False
        assert client.pexpires == []  # nothing renewed...
        assert client.store["flight:k"] == b"the-owner"  # ...and nothing evicted

        assert backend.lock_extend("flight:k", "the-owner", 60) is True
        assert client.pexpires == [("flight:k", "the-owner", 60_000)]

    def test_extend_is_a_no_op_once_the_lock_is_gone(self):
        from app.services.query_cache import RedisBackend

        client = _FakeRedis()
        backend = RedisBackend(client)
        backend.lock_acquire("flight:k", "tok", 60)
        client.expire_now("flight:k")
        assert backend.lock_extend("flight:k", "tok", 60) is False
        assert "flight:k" not in client.store  # never resurrected

    def test_both_lock_scripts_compare_the_token_inside_redis(self):
        """The fake applies the token check in Python, so it would pass even
        against an unguarded script: only the script TEXT can show that the
        real comparison happens inside Redis, atomically with the write. An
        unguarded pexpire is precisely the GET-then-PEXPIRE race the token
        exists to prevent - it would let a stale leader keep renewing the lock
        a newer leader has taken since.
        """
        from app.services.query_cache import _EXTEND_IF_MINE, _RELEASE_IF_MINE

        guard = "if redis.call('get', KEYS[1]) == ARGV[1] then"
        for script, write in ((_RELEASE_IF_MINE, "del"), (_EXTEND_IF_MINE, "pexpire")):
            assert guard in script, script
            # The one mutating call sits INSIDE the guard, and the path that
            # skips the guard reports "not mine" instead of falling through.
            assert script.count(write) == 1, script
            assert script.index(guard) < script.index(write), script
            assert script.rstrip().endswith("return 0"), script


class TestHeartbeatLifecycle:
    """The renewal thread belongs to one leader's flight: a daemon, stopped
    whenever that flight ends, and never accumulating per request."""

    def test_heartbeat_is_a_daemon_and_stops_on_exit(self):
        client = _FakeRedis()
        cache = _instance(client, flight_ttl_seconds=0.3)
        lock = cache.flight_lock("k")
        with lock:
            beat = lock._heartbeat_thread
            assert beat is not None
            assert beat.daemon is True  # never holds the process open
            assert beat.is_alive()
        assert not beat.is_alive()  # release joined it - deterministically gone

        beats = len(client.pexpires)
        time.sleep(0.25)  # two whole intervals later...
        assert len(client.pexpires) == beats  # ...nothing is still renewing

    def test_heartbeat_stops_when_the_flight_raises(self):
        client = _FakeRedis()
        cache = _instance(client, flight_ttl_seconds=0.3)
        lock = cache.flight_lock("k")
        beat = None
        with pytest.raises(RuntimeError):
            with lock:
                beat = lock._heartbeat_thread
                raise RuntimeError("generation blew up")

        assert beat is not None and not beat.is_alive()
        assert "flight:k" not in client.store  # the lock went with it

    def test_heartbeat_retires_once_a_newer_leader_owns_the_key(self):
        """A leader that lost the lock anyway (its TTL lapsed while Redis was
        unreachable, say) must not go on renewing what is now someone else's."""
        client = _FakeRedis()
        one, two = _instance(client, flight_ttl_seconds=0.3), _instance(client)

        slow = one.flight_lock("k")
        assert slow.acquire(blocking=False) is True
        beat = slow._heartbeat_thread
        client.expire_now("flight:k")  # the TTL lapses mid-flight

        successor = two.flight_lock("k")
        assert successor.acquire(blocking=False) is True
        successor_token = client.store["flight:k"]

        beat.join(timeout=3.0)
        assert not beat.is_alive()  # it retired itself
        assert client.pexpires == []  # having renewed nothing
        assert client.store["flight:k"] == successor_token

        slow.release()
        assert client.store["flight:k"] == successor_token  # nor deleted it
        successor.release()

    def test_a_follower_starts_no_heartbeat(self):
        client = _FakeRedis()
        one, two = _instance(client), _instance(client)
        leader = one.flight_lock("k")
        assert leader.acquire(blocking=False) is True

        follower = two.flight_lock("k")
        assert follower.acquire(blocking=False) is False
        assert follower._heartbeat_thread is None  # nothing of ours to renew
        leader.release()

    def test_leading_by_failing_open_starts_no_heartbeat(self):
        # No remote token exists, so there is nothing to extend: the
        # in-process lock IS the flight.
        cache = _instance(_LockBlindRedis())
        lock = cache.flight_lock("k")
        assert lock.acquire(blocking=False) is True
        assert lock._heartbeat_thread is None
        lock.release()

    def test_the_in_memory_backend_starts_no_heartbeat(self):
        from app.services.query_cache import InMemoryBackend, QueryCache

        cache = QueryCache(InMemoryBackend(clock=_Clock(0)), ttl_seconds=60)
        lock = cache.flight_lock("k")
        with lock:
            assert lock._heartbeat_thread is None

    def test_repeated_flights_do_not_pile_up_threads(self):
        client = _FakeRedis()
        cache = _instance(client, flight_ttl_seconds=0.3)
        before = threading.active_count()
        for _ in range(5):
            with cache.flight_lock("k"):
                pass
        assert threading.active_count() <= before  # no thread per request


class TestTheLeaseBoundsALeakedFlight:
    """The heartbeat took the TTL's job of freeing a wedged lock, so it needs a
    backstop of its own.

    ``release`` is the ONLY thing that stops a beat, so an acquire whose release
    never runs (an exception on a path that misses it, a killed request) would
    otherwise renew the FLEET-WIDE lock for the life of the worker process:
    every later asker of that question waits out its whole follower budget and
    then computes unlocked, forever. Before the heartbeat, one TTL healed
    exactly that. The lease puts that back.
    """

    def test_a_leaked_flight_stops_renewing_at_its_lease(self):
        client = _FakeRedis()
        cache = _instance(client, flight_ttl_seconds=0.3, flight_max_lease_seconds=0.35)
        lock = cache.flight_lock("k")
        assert lock.acquire(blocking=False) is True  # ...and is never released

        beat = lock._heartbeat_thread
        beat.join(timeout=5.0)
        assert not beat.is_alive()  # it retired itself, unasked
        renewals = len(client.pexpires)
        assert renewals >= 1  # having genuinely renewed while the lease ran
        time.sleep(0.3)  # three whole beat intervals later...
        assert len(client.pexpires) == renewals  # ...nothing is renewing

    def test_the_lock_frees_itself_after_a_leaked_flight(self):
        """The point of stopping: the TTL can clear a key nothing is re-arming,
        so the fleet heals itself exactly as it did before the heartbeat."""
        client = _ExpiringFakeRedis()
        one = _instance(client, flight_ttl_seconds=0.3, flight_max_lease_seconds=0.35)
        two = _instance(client, flight_ttl_seconds=0.3)

        leaked = one.flight_lock("k")
        assert leaked.acquire(blocking=False) is True  # leaked: no release, ever

        took_over = False
        deadline = time.monotonic() + 5.0
        while not took_over and time.monotonic() < deadline:
            attempt = two.flight_lock("k")
            if attempt.acquire(blocking=False):
                took_over = True
                attempt.release()
            else:
                time.sleep(0.05)
        assert took_over

    def test_a_normal_flight_never_reaches_the_lease(self):
        """The bound must not clip a leader that is merely slow - keeping one is
        the whole reason the heartbeat exists."""
        client = _FakeRedis()
        cache = _instance(client, flight_ttl_seconds=0.3, flight_max_lease_seconds=30.0)
        lock = cache.flight_lock("k")
        with lock:
            deadline = time.monotonic() + 3.0
            while len(client.pexpires) < 3 and time.monotonic() < deadline:
                time.sleep(0.02)
        assert len(client.pexpires) >= 3  # renewed straight through
        assert "flight:k" not in client.store  # and released normally

    def test_the_default_lease_is_a_multiple_of_the_flight_ttl(self):
        """Far longer than the slowest legitimate flight, far shorter than for
        ever - and derived from the TTL, so tuning one moves the other."""
        from app.services.query_cache import _MAX_LEASE_TTLS

        assert _MAX_LEASE_TTLS >= 2
        cache = _instance(_FakeRedis(), flight_ttl_seconds=120.0)
        assert cache.flight_lock("k")._max_lease == 120.0 * _MAX_LEASE_TTLS
