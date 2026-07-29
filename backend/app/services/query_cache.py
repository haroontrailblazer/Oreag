"""CAG storage - pluggable backends, the query cache, and conversation memory.

A repeated question shouldn't re-run retrieval and the LLM, and a follow-up
should remember the conversation. Both needs ride on a tiny string KV backend:

  * ``InMemoryBackend`` - per-process dict with TTL + LRU. The local-dev/test
    default; cleared on restart, not shared across workers.
  * ``RedisBackend`` - the same interface backed by Redis. Selected when
    ``REDIS_URL`` is configured, so the cache and conversations are shared across
    workers and survive restarts.

``make_backend`` picks one based on the URL (optional, with in-memory fallback).
On top of a backend:

  * ``QueryCache`` - CAG answer cache, keyed by project+model+top_k+content+
    question, with single-flight so simultaneous identical asks compute once.
    On Redis that single-flight is fleet-wide (SET NX + a token-checked
    release), so N app instances asking the same question compute once, not
    once each; on the in-memory backend it stays per-process, as before.
  * ``ConversationStore`` - server-side chat memory keyed by ``conversation_id``.
"""
import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Returned by a backend `get` when the backend itself failed (vs. a genuine
# miss). Plain readers treat it as a miss; read-modify-write callers
# (ConversationStore.append_turn) must NOT write afterwards - overwriting a
# 20-turn history with 1 turn because one read timed out would be data loss.
UNAVAILABLE = object()


def normalize_question(question: str) -> str:
    """Canonical form of a question for the exact-match (L1) cache.

    Lower-cases, collapses runs of whitespace, and strips surrounding
    punctuation, so "What is PyTorch?", "what is pytorch", and "WHAT  IS
    PYTORCH!" all map to one L1 entry (an exact repeat is case- and
    punctuation-insensitive). Anything beyond trivial rewording still misses
    L1 and is caught by the semantic (L2) layer.
    """
    return " ".join(question.lower().split()).strip(" ?!.,;:")


def cache_key(project, question: str, top_k: int, content_signature: str) -> str:
    """Build the cache key for a query.

    Everything that can change the answer is part of the key: the project, the
    chat + embedding models, top_k, a signature of the indexed content, and the
    normalized question (see ``normalize_question``), so trivial case/whitespace/
    punctuation differences share an entry.
    """
    normalized = normalize_question(question)
    return "|".join(
        [
            str(project.id),
            project.llm_provider,
            project.llm_model,
            project.embedding_provider,
            project.embedding_model,
            str(top_k),
            content_signature,
            normalized,
        ]
    )


class InMemoryBackend:
    """Per-process string KV with TTL and LRU eviction."""

    def __init__(
        self, clock: Callable[[], float] = time.monotonic, max_entries: int = 512
    ):
        self._clock = clock
        self._max_entries = max_entries
        self._store: "OrderedDict[str, tuple[float, str]]" = OrderedDict()
        self._guard = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._guard:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if self._clock() >= expires_at:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: str, ttl_seconds: float) -> None:
        with self._guard:
            self._store[key] = (self._clock() + ttl_seconds, value)
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._guard:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._guard:
            self._store.clear()


# Compare-and-delete as ONE atomic step: a leader whose lock already expired
# (a slow generation outran the TTL) must never delete the lock a NEW leader
# has taken since - that would let a third caller lead while the second still
# believes it holds the flight. GET-then-DEL from Python has exactly that race,
# so the check has to run inside Redis.
_RELEASE_IF_MINE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class RedisBackend:
    """Same interface, backed by a redis client (injected, so it's testable).

    Every operation is best-effort: this backend holds a CACHE and conversation
    memory, so a Redis outage must degrade to "miss" - never take the query
    path down with a 500 or block a thread on an unbounded socket wait (the
    client is built with short socket timeouts in ``make_backend``).
    """

    def __init__(self, client):
        self._r = client

    def get(self, key: str):
        try:
            raw = self._r.get(key)
        except Exception as exc:
            logger.warning("Redis get failed (%s) - treating as miss", type(exc).__name__)
            return UNAVAILABLE
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, (bytes, bytearray)) else raw

    def set(self, key: str, value: str, ttl_seconds: float) -> None:
        try:
            self._r.set(key, value, ex=int(ttl_seconds))
        except Exception as exc:
            logger.warning("Redis set failed (%s) - skipping", type(exc).__name__)

    def delete(self, key: str) -> None:
        try:
            self._r.delete(key)
        except Exception as exc:
            logger.warning("Redis delete failed (%s) - skipping", type(exc).__name__)

    def clear(self) -> None:
        # Never flush a shared Redis; entries expire by TTL.
        pass

    # -- distributed single-flight (see _FlightLock) ------------------------
    # Optional backend capability: a backend without these two methods simply
    # has no fleet-wide layer, so the lock stays per-process.

    def lock_acquire(self, key: str, token: str, ttl_seconds: float):
        """Take the fleet-wide lock for ``key``, best-effort.

        ``token`` identifies THIS holder so only it can release the lock; the
        TTL means a crashed leader's lock clears itself. Returns True when we
        hold it, False when another holder does, and ``UNAVAILABLE`` when Redis
        itself failed - the caller then degrades to its in-process lock rather
        than failing the query.
        """
        try:
            taken = self._r.set(key, token, nx=True, px=max(int(ttl_seconds * 1000), 1))
        except Exception as exc:
            logger.warning(
                "Redis lock acquire failed (%s) - falling back to the in-process lock",
                type(exc).__name__,
            )
            return UNAVAILABLE
        return bool(taken)

    def lock_release(self, key: str, token: str) -> None:
        """Drop the lock, but only while it still carries ``token``."""
        try:
            self._r.eval(_RELEASE_IF_MINE, 1, key, token)
        except Exception as exc:
            # Deliberately NOT falling back to a plain DELETE - that is the
            # foreign-token delete the token exists to prevent. Leaving the key
            # alone costs at most one TTL of extra waiting.
            logger.warning(
                "Redis lock release failed (%s) - the lock will expire by TTL",
                type(exc).__name__,
            )


class _FlightLock:
    """Per-key single-flight lock: the in-process ``threading.Lock``, plus a
    Redis lock when the backend offers one.

    Deliberately mirrors ``threading.Lock``'s surface - ``acquire(blocking=)``,
    ``acquire(timeout=)``, ``release()`` and ``with`` - because it replaces a
    plain Lock that services/query.py drives by hand (the streaming path emits
    tokens while computing, so it leads and follows explicitly).

    Both layers are taken in one order, local first: two threads of the same
    process queue on the cheap in-process lock and only ONE of them ever talks
    to Redis for that key. Every remote hop is best-effort - a Redis outage
    degrades to exactly the old per-process single-flight instead of taking the
    query path down with it.
    """

    def __init__(
        self,
        local: threading.Lock,
        key: str,
        backend=None,
        ttl_seconds: float = 120.0,
        poll_seconds: float = 0.05,
    ):
        self._local = local
        self._key = key
        self._acquire_remote = getattr(backend, "lock_acquire", None)
        self._release_remote = getattr(backend, "lock_release", None)
        self._ttl = ttl_seconds
        self._poll = poll_seconds
        self._token: str | None = None

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        """True when this caller LEADS the flight for the key.

        False means only "somebody else leads and we stopped waiting" - the
        caller then computes unlocked (correctness over dedup), which is what
        both call sites already do. Nothing is held when it returns False.
        """
        if timeout is None:
            timeout = -1
        deadline = time.monotonic() + timeout if timeout >= 0 else None
        got_local = (
            self._local.acquire(True, timeout) if blocking else self._local.acquire(False)
        )
        if not got_local:
            return False
        if self._lead(blocking, deadline):
            return True
        # Another instance leads. Hand the local slot back so this process's
        # other waiters queue behind that leader instead of behind us.
        self._local.release()
        return False

    def _lead(self, blocking: bool, deadline: float | None) -> bool:
        if self._acquire_remote is None:
            return True  # no fleet-wide layer: the in-process lock IS the flight
        token = uuid.uuid4().hex  # unique per acquisition - see lock_release
        # An unbounded `with` wait must not park a request thread forever: a
        # lock still held past its own TTL is stale by definition, so we stop
        # waiting and lead anyway.
        limit = deadline if deadline is not None else time.monotonic() + self._ttl
        lead_on_expiry = deadline is None
        while True:
            outcome = self._acquire_remote(self._key, token, self._ttl)
            if outcome is UNAVAILABLE:
                return True  # Redis down - fail open onto the in-process lock
            if outcome:
                self._token = token
                return True
            if not blocking:
                return False
            remaining = limit - time.monotonic()
            if remaining <= 0:
                return lead_on_expiry
            time.sleep(min(self._poll, remaining))

    def release(self) -> None:
        # Clear the token FIRST: a double release must never reach Redis with a
        # token that a newer leader could still be holding.
        token, self._token = self._token, None
        if token is not None and self._release_remote is not None:
            self._release_remote(self._key, token)
        self._local.release()

    def locked(self) -> bool:
        return self._local.locked()

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *exc_info) -> None:
        self.release()


def make_backend(
    redis_url: str = "",
    clock: Callable[[], float] = time.monotonic,
    max_entries: int = 512,
):
    """Pick a backend: Redis when a URL is configured, else in-memory."""
    if redis_url:
        import redis  # lazy - only required when actually configured

        # Short socket timeouts: redis-py defaults to NO timeout, so a hung
        # (not refused) Redis would block request threads indefinitely. A
        # cache lookup that can't answer in ~1s should just be a miss.
        return RedisBackend(
            redis.from_url(
                redis_url,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
                retry_on_timeout=False,
                health_check_interval=30,
            )
        )
    return InMemoryBackend(clock=clock, max_entries=max_entries)


class QueryCache:
    """CAG answer cache over a backend, with single-flight.

    Values are (de)serialized to JSON strings for the backend. ``serialize`` /
    ``deserialize`` can be overridden to round-trip richer objects (e.g. an
    ``AgenticResult``).

    ``flight_ttl_seconds`` bounds a lock a crashed leader left behind: long
    enough to cover a slow leader (retrieval plus a full generation) so the
    lock can't expire mid-flight and elect a second leader, short enough that
    it can't outlast a follower's own wait budget. ``flight_wait_seconds`` is
    how long ``get_or_compute``'s followers wait for the leader.
    """

    def __init__(
        self,
        backend,
        ttl_seconds: float,
        serialize: Callable[[Any], str] = json.dumps,
        deserialize: Callable[[str], Any] = json.loads,
        flight_ttl_seconds: float = 120.0,
        flight_wait_seconds: float = 30.0,
    ):
        self._backend = backend
        self._ttl = ttl_seconds
        self._serialize = serialize
        self._deserialize = deserialize
        self._flight_ttl = flight_ttl_seconds
        self._flight_wait = flight_wait_seconds
        self._key_locks: dict[str, threading.Lock] = {}
        self._key_locks_guard = threading.Lock()

    @staticmethod
    def _namespaced(key: str) -> str:
        return f"cache:{key}"

    @staticmethod
    def _flight_namespaced(key: str) -> str:
        # Its own namespace: the lock and the answer it guards share a key but
        # must never overwrite one another.
        return f"flight:{key}"

    def get(self, key: str) -> Any:
        raw = self._backend.get(self._namespaced(key))
        if raw is None or raw is UNAVAILABLE:
            return None
        return self._deserialize(raw)

    def set(self, key: str, value: Any) -> None:
        self._backend.set(self._namespaced(key), self._serialize(value), self._ttl)

    def clear(self) -> None:
        self._backend.clear()

    def _lock_for(self, key: str) -> threading.Lock:
        with self._key_locks_guard:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._key_locks[key] = lock
            return lock

    def flight_lock(self, key: str) -> _FlightLock:
        """The per-key single-flight lock (same one get_or_compute uses).

        Exposed for the streaming path, which can't run inside
        get_or_compute: it emits tokens WHILE computing, so it needs manual
        lead/follow control around its own generator.

        Keeps a ``threading.Lock``'s behaviour (acquire/release/``with``), but
        on a Redis backend it also takes a fleet-wide lock, so the leader is
        elected across instances rather than once per process."""
        return _FlightLock(
            self._lock_for(key),
            self._flight_namespaced(key),
            backend=self._backend,
            ttl_seconds=self._flight_ttl,
        )

    def get_or_compute(self, key: str, compute: Callable[[], Any]) -> Any:
        """Return the cached value, or compute it exactly once.

        On a miss the first caller computes while holding the key's lock;
        concurrent callers for the same key block, then reuse the cached value.
        With Redis configured that leader is fleet-wide, so a second instance
        follows instead of running its own copy of the pipeline. Exceptions
        from ``compute`` propagate and are not cached.

        The wait is bounded: if the leader is stuck - or cache writes are
        no-oping during a backend outage, so followers would otherwise
        recompute one-at-a-time forever - a waiter gives up after
        ``flight_wait_seconds`` and computes independently.
        """
        hit = self.get(key)
        if hit is not None:
            return hit
        lock = self.flight_lock(key)
        acquired = lock.acquire(timeout=self._flight_wait)
        try:
            if acquired:
                hit = self.get(key)
                if hit is not None:
                    return hit
            value = compute()
            self.set(key, value)
            return value
        finally:
            if acquired:
                lock.release()


class ConversationStore:
    """Server-side conversation memory keyed by (scope, conversation_id).

    ``scope`` is the project id: conversation_id is a caller-chosen string, so
    without the scope two tenants independently picking "session-1" would read
    and corrupt each other's chat history on a shared backend. (Histories
    written under the pre-scope ``conv:{id}`` key format are deliberately left
    to expire rather than dual-read - a legacy fallback would reintroduce the
    cross-tenant collision this fixes. One-time reset on deploy.)

    The whole turn list is stored as one JSON document and capped to the most
    recent ``max_turns`` on every append, so it stays small and bounded.
    """

    def __init__(self, backend, ttl_seconds: float, max_turns: int = 20):
        self._backend = backend
        self._ttl = ttl_seconds
        self._max_turns = max_turns

    @staticmethod
    def _namespaced(scope: str, conversation_id: str) -> str:
        return f"conv:{scope}:{conversation_id}"

    def _read(self, scope: str, conversation_id: str) -> tuple[list[dict], bool]:
        """Returns (history, degraded). ``degraded`` means the backend failed -
        the caller must not write back what may be a truncated view."""
        raw = self._backend.get(self._namespaced(scope, conversation_id))
        if raw is UNAVAILABLE:
            return [], True
        return (json.loads(raw) if raw else []), False

    def get_history(self, scope: str, conversation_id: str) -> list[dict]:
        return self._read(scope, conversation_id)[0]

    def append_turn(
        self, scope: str, conversation_id: str, question: str, answer: str
    ) -> list[dict]:
        history, degraded = self._read(scope, conversation_id)
        history.append({"question": question, "answer": answer})
        history = history[-self._max_turns :]
        if degraded:
            # The read failed, so `history` holds only this turn. Writing it
            # would OVERWRITE the stored conversation with a one-turn stub the
            # moment the backend recovers - dropping the turn is the lesser
            # loss.
            logger.warning(
                "Conversation backend unavailable - turn not recorded for %s",
                conversation_id,
            )
            return history
        self._backend.set(
            self._namespaced(scope, conversation_id), json.dumps(history), self._ttl
        )
        return history
