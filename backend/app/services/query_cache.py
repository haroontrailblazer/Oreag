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
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any


def cache_key(project, question: str, top_k: int, content_signature: str) -> str:
    """Build the cache key for a query.

    Everything that can change the answer is part of the key: the project, the
    chat + embedding models, top_k, a signature of the indexed content, and the
    question (lower-cased, whitespace-collapsed, so trivial spelling differences
    share an entry).
    """
    normalized = " ".join(question.lower().split())
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
    """Same interface, backed by a redis client (injected, so it's testable)."""

    def __init__(self, client):
        self._r = client

    def get(self, key: str) -> str | None:
        raw = self._r.get(key)
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, (bytes, bytearray)) else raw

    def set(self, key: str, value: str, ttl_seconds: float) -> None:
        self._r.set(key, value, ex=int(ttl_seconds))

    def delete(self, key: str) -> None:
        self._r.delete(key)

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

        return RedisBackend(redis.from_url(redis_url))
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
        return None if raw is None else self._deserialize(raw)

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

    def get_or_compute(self, key: str, compute: Callable[[], Any]) -> Any:
        """Return the cached value, or compute it exactly once.

        On a miss the first caller computes while holding the key's lock;
        concurrent callers for the same key block, then reuse the cached value.
        Exceptions from ``compute`` propagate and are not cached.
        """
        hit = self.get(key)
        if hit is not None:
            return hit
        with self._lock_for(key):
            hit = self.get(key)
            if hit is not None:
                return hit
            value = compute()
            self.set(key, value)
            return value


class ConversationStore:
    """Server-side conversation memory keyed by conversation_id.

    The whole turn list is stored as one JSON document and capped to the most
    recent ``max_turns`` on every append, so it stays small and bounded.
    """

    def __init__(self, backend, ttl_seconds: float, max_turns: int = 20):
        self._backend = backend
        self._ttl = ttl_seconds
        self._max_turns = max_turns

    @staticmethod
    def _namespaced(conversation_id: str) -> str:
        return f"conv:{conversation_id}"

    def get_history(self, conversation_id: str) -> list[dict]:
        raw = self._backend.get(self._namespaced(conversation_id))
        return json.loads(raw) if raw else []

    def append_turn(
        self, conversation_id: str, question: str, answer: str
    ) -> list[dict]:
        history = self.get_history(conversation_id)
        history.append({"question": question, "answer": answer})
        history = history[-self._max_turns :]
        self._backend.set(
            self._namespaced(conversation_id), json.dumps(history), self._ttl
        )
        return history
