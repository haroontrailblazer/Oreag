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
    question, with per-process single-flight so simultaneous identical asks
    compute once.
  * ``ConversationStore`` - server-side chat memory keyed by ``conversation_id``.
"""
import json
import logging
import threading
import time
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
    """CAG answer cache over a backend, with per-process single-flight.

    Values are (de)serialized to JSON strings for the backend. ``serialize`` /
    ``deserialize`` can be overridden to round-trip richer objects (e.g. an
    ``AgenticResult``).
    """

    def __init__(
        self,
        backend,
        ttl_seconds: float,
        serialize: Callable[[Any], str] = json.dumps,
        deserialize: Callable[[str], Any] = json.loads,
    ):
        self._backend = backend
        self._ttl = ttl_seconds
        self._serialize = serialize
        self._deserialize = deserialize
        self._key_locks: dict[str, threading.Lock] = {}
        self._key_locks_guard = threading.Lock()

    @staticmethod
    def _namespaced(key: str) -> str:
        return f"cache:{key}"

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

    def flight_lock(self, key: str) -> threading.Lock:
        """The per-key single-flight lock (same one get_or_compute uses).

        Exposed for the streaming path, which can't run inside
        get_or_compute: it emits tokens WHILE computing, so it needs manual
        lead/follow control around its own generator."""
        return self._lock_for(key)

    def get_or_compute(self, key: str, compute: Callable[[], Any]) -> Any:
        """Return the cached value, or compute it exactly once.

        On a miss the first caller computes while holding the key's lock;
        concurrent callers for the same key block, then reuse the cached value.
        Exceptions from ``compute`` propagate and are not cached.

        The wait is bounded: if the leader is stuck - or cache writes are
        no-oping during a backend outage, so followers would otherwise
        recompute one-at-a-time forever - a waiter gives up after 30s and
        computes independently.
        """
        hit = self.get(key)
        if hit is not None:
            return hit
        lock = self._lock_for(key)
        acquired = lock.acquire(timeout=30.0)
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
