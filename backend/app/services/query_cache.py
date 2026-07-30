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
    On Redis that single-flight is fleet-wide (SET NX, with token-checked
    renewal while the leader works and a token-checked release), so N app
    instances asking the same question compute once, not once each; on the
    in-memory backend it stays per-process, as before.
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

# Renewing the lock is the same shape and needs the same protection: a leader
# whose generation outran the TTL must push out ITS OWN expiry, never the one
# a newer leader has taken since. GET-then-PEXPIRE from Python would hand a
# slow leader the power to keep a successor's lock alive, so the token check
# runs inside Redis here too.
_EXTEND_IF_MINE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
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
    # Optional backend capability: a backend without these methods simply has
    # no fleet-wide layer, so the lock stays per-process. ``lock_extend`` is
    # optional on top of that: without it a leader just can't renew.

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

    def lock_extend(self, key: str, token: str, ttl_seconds: float):
        """Re-arm the lock's TTL, but only while it still carries ``token``.

        Returns True when the extension landed, False when the lock is gone or
        a NEWER holder owns it (this caller must stop renewing - it no longer
        leads), and ``UNAVAILABLE`` when Redis itself failed, which is a blip
        to retry rather than proof we lost the lock.
        """
        try:
            extended = self._r.eval(
                _EXTEND_IF_MINE, 1, key, token, max(int(ttl_seconds * 1000), 1)
            )
        except Exception as exc:
            logger.warning(
                "Redis lock extend failed (%s) - the lock may expire mid-flight",
                type(exc).__name__,
            )
            return UNAVAILABLE
        return bool(extended)

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


# How long ``release`` waits for the heartbeat thread to notice it should stop.
# Only a beat already inside a Redis call can need it, and the client's socket
# timeout is ~1s (see make_backend).
_HEARTBEAT_JOIN_SECONDS = 2.0

# Hard ceiling on how long ONE flight may keep renewing its lock, as a multiple
# of the TTL. The heartbeat is what stops a merely slow leader from dropping its
# lock mid-generation - but on its own it also removes the only backstop a
# distributed lock has: a leader that never releases (an exception on a path
# that does not reach its release, a request killed mid-flight) would hold the
# FLEET-WIDE lock forever, because the TTL can no longer clear a key something
# is still re-arming. The lease puts that backstop back: once it runs out the
# beat gives up, and the lock expires by TTL exactly as it did before the
# heartbeat existed. 5 TTLs (10 minutes at the 120s default) is an order of
# magnitude longer than the slowest legitimate flight - an agentic query is
# minutes at worst, and every HTTP client between here and the browser has given
# up long before - and it is not forever.
_MAX_LEASE_TTLS = 5

# How long a waiter keeps following a leader it can no longer see, once the lock
# store has gone dark mid-flight. Nothing can prove who leads while the store is
# unreachable, so this is a choice between two degradations, not between right
# and wrong: lead without fleet-wide exclusion (duplicate work), or follow
# somebody nobody can confirm is there (a stall). A short grace absorbs the
# common shape - a reconnect or failover of a second or two, after which the
# store itself says who leads - and beyond it we degrade to per-process
# single-flight rather than park a request for its whole budget. Sized above the
# client's ~1s socket timeout so a hung (not refused) store gets more than one
# attempt inside the grace.
_LOCK_OUTAGE_GRACE_SECONDS = 1.5


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

    A leader keeps its own lock alive for as long as it works: a daemon
    heartbeat re-arms the TTL (token-checked, so it can only ever extend OUR
    lock) from ``acquire`` until ``release`` stops it. So the TTL bounds a
    leader that DIED, not one that is merely slow - a generation longer than
    the TTL no longer drops its lock mid-flight and elects a second leader
    onto the same answer. That renewal is itself bounded by a LEASE
    (``_MAX_LEASE_TTLS``): a flight that never releases stops being renewed and
    the lock expires by TTL, so a leaked leader cannot wedge the fleet forever.

    What an outage of the lock store costs is dedup, never the answer - and the
    honest limit of that is worth stating, because a distributed lock cannot
    exclude anyone while the thing it locks in is unreachable:

      * while the store has never answered THIS PROCESS, leading is the only
        option (nobody can be followed, and an unreachable lock store must not
        fail a query);
      * once it has answered, an outage may be hiding a leader elected while it
        was healthy, so a waiter keeps following through
        ``_LOCK_OUTAGE_GRACE_SECONDS`` - long enough for a blip to heal and for
        the store to name the leader - and only then leads anyway;
      * so two instances CAN both lead while the store is down. That is
        per-process single-flight, exactly the pre-Redis behaviour, and it is a
        deliberate trade against stalling every request for its whole budget on
        a leader nobody can see.
    """

    def __init__(
        self,
        local: threading.Lock,
        key: str,
        backend=None,
        ttl_seconds: float = 120.0,
        poll_seconds: float = 0.05,
        heartbeat_seconds: float | None = None,
        max_lease_seconds: float | None = None,
        outage_grace_seconds: float = _LOCK_OUTAGE_GRACE_SECONDS,
        store_seen: threading.Event | None = None,
    ):
        self._local = local
        self._key = key
        self._acquire_remote = getattr(backend, "lock_acquire", None)
        self._release_remote = getattr(backend, "lock_release", None)
        self._extend_remote = getattr(backend, "lock_extend", None)
        self._ttl = ttl_seconds
        self._poll = poll_seconds
        # Renew at a third of the TTL: two beats can be lost to a Redis blip
        # before the lock a live leader still holds could actually expire. The
        # floor keeps a tiny TTL from turning the beat into a busy loop.
        self._heartbeat_seconds = max(
            ttl_seconds / 3.0 if heartbeat_seconds is None else heartbeat_seconds, 0.01
        )
        self._max_lease = max(
            ttl_seconds * _MAX_LEASE_TTLS
            if max_lease_seconds is None
            else max_lease_seconds,
            0.0,
        )
        self._outage_grace = outage_grace_seconds
        # "Has the lock store ever answered?" is a property of the STORE, not of
        # one request's lock object, so it is shared by every lock a QueryCache
        # hands out (see flight_lock) and is sticky once set. A per-acquisition
        # flag would say nothing about whether a leader could have been elected
        # while the store was healthy - which is the only question that matters
        # here. Own Event when unshared, so a bare _FlightLock still works.
        self._store_seen = store_seen if store_seen is not None else threading.Event()
        self._token: str | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop: threading.Event | None = None

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
            self._start_heartbeat()
            return True
        # Another instance leads. Hand the local slot back so this process's
        # other waiters queue behind that leader instead of behind us.
        self._local.release()
        return False

    def _lead(self, blocking: bool, deadline: float | None) -> bool:
        if self._acquire_remote is None:
            return True  # no fleet-wide layer: the in-process lock IS the flight
        token = uuid.uuid4().hex  # unique per acquisition - see lock_release
        # An unbounded `with` wait must not park a request thread forever, so
        # one TTL is its cap and it leads once that runs out. Note this is a
        # WAIT cap, not proof the lock went stale: a live leader heartbeats
        # past its TTL, so that fallback trades dedup for not hanging. Every
        # caller that has a budget of its own (both of query.py's, and
        # get_or_compute) passes a deadline and falls through as a follower
        # instead.
        limit = deadline if deadline is not None else time.monotonic() + self._ttl
        lead_on_expiry = deadline is None
        outage_started: float | None = None  # when the CURRENT dark spell began
        while True:
            outcome = self._acquire_remote(self._key, token, self._ttl)
            if outcome is not UNAVAILABLE:
                self._store_seen.set()  # sticky, and shared across this backend
                outage_started = None
                if outcome:
                    self._token = token
                    return True
            else:
                # The store is dark. It may be hiding a leader elected while it
                # was healthy, so follow for a grace in case it comes back and
                # says so - but no longer, because nothing here can ever prove
                # who leads while it stays dark. See the class docstring for
                # what this deliberately does NOT guarantee.
                now = time.monotonic()
                if outage_started is None:
                    outage_started = now
                if (
                    not self._store_seen.is_set()
                    or now - outage_started >= self._outage_grace
                ):
                    return self._lead_degraded()
            if not blocking:
                # No budget to wait with. A dark store must not turn a
                # non-blocking caller into a follower: it would then sit out a
                # whole follower budget (query.py's streaming path waits two
                # minutes) on a leader nobody can confirm exists.
                return self._lead_degraded() if outcome is UNAVAILABLE else False
            remaining = limit - time.monotonic()
            if remaining <= 0:
                return lead_on_expiry
            time.sleep(min(self._poll, remaining))

    def _lead_degraded(self) -> bool:
        """Lead on the in-process lock alone, the remote store being unreachable.

        No token is set, so there is no remote lock to renew (no heartbeat) and
        none to release. Another instance may be leading the same key: with the
        store down that is per-process single-flight, which is what this layer
        degrades to rather than failing the query.
        """
        logger.warning(
            "Flight lock store unreachable for %s - leading on the in-process "
            "lock alone; another instance may be leading the same key",
            self._key,
        )
        return True

    def _start_heartbeat(self) -> None:
        """Keep this leader's remote lock alive while it computes.

        No token means there is no remote lock of ours to renew (no fleet-wide
        layer, or we led by failing open), so there is nothing to beat for.
        """
        if self._token is None or self._extend_remote is None:
            return
        stop = threading.Event()
        thread = threading.Thread(
            target=self._heartbeat,
            args=(self._token, stop, time.monotonic() + self._max_lease),
            name="flight-lock-heartbeat",
            daemon=True,  # a leaked beat must never hold the process open
        )
        self._heartbeat_stop = stop
        self._heartbeat_thread = thread
        thread.start()

    def _heartbeat(self, token: str, stop: threading.Event, lease_until: float) -> None:
        while not stop.wait(self._heartbeat_seconds):
            if time.monotonic() >= lease_until:
                # The lease is the TTL's replacement as the backstop: a flight
                # this long has either leaked (an acquire whose release never
                # ran) or is beyond anything a caller is still waiting for.
                # Stop renewing and the lock clears itself one TTL later, as it
                # did before the heartbeat existed.
                logger.error(
                    "Flight lock %s was never released within its %.0fs lease - "
                    "stopping the heartbeat so the TTL can clear it",
                    self._key,
                    self._max_lease,
                )
                return
            outcome = self._extend_remote(self._key, token, self._ttl)
            if outcome is UNAVAILABLE:
                continue  # a blip, not a verdict - try again next beat
            if not outcome:
                # The key is gone or a NEWER leader owns it: our token can
                # never come back, so further beats could only be no-ops.
                logger.warning(
                    "Flight lock %s is no longer ours - stopping the heartbeat",
                    self._key,
                )
                return

    def _stop_heartbeat(self) -> None:
        stop, thread = self._heartbeat_stop, self._heartbeat_thread
        self._heartbeat_stop = self._heartbeat_thread = None
        if stop is not None:
            stop.set()  # deterministic: the beat exits at its next wait
        if thread is not None and thread is not threading.current_thread():
            # Bounded join: a beat parked in a hung Redis call returns within
            # the client's socket timeout, and it is a daemon either way, so
            # release never becomes the thing that stalls a request.
            thread.join(timeout=_HEARTBEAT_JOIN_SECONDS)

    def release(self) -> None:
        # Clear the token FIRST: a double release must never reach Redis with a
        # token that a newer leader could still be holding. Stop the heartbeat
        # before the release for the same reason - no beat may outlive the
        # flight it was renewing.
        token, self._token = self._token, None
        self._stop_heartbeat()
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

    ``flight_ttl_seconds`` bounds a lock whose leader stopped renewing it -
    i.e. one that CRASHED - so the flight can't wedge for the fleet; it is not
    a budget a live leader has to finish inside, because while a leader holds
    the flight it heartbeats its lock forward (see ``_FlightLock``). A slow
    generation therefore keeps its lock instead of silently electing a second
    leader onto the same answer. ``flight_max_lease_seconds`` caps that renewal
    so a flight that never releases still frees the lock (one TTL after the
    lease runs out) instead of holding it for the life of the process; it
    defaults to ``_MAX_LEASE_TTLS`` times the flight TTL. ``flight_wait_seconds``
    is how long ``get_or_compute``'s followers wait for the leader before giving
    up and computing on their own.
    """

    def __init__(
        self,
        backend,
        ttl_seconds: float,
        serialize: Callable[[Any], str] = json.dumps,
        deserialize: Callable[[str], Any] = json.loads,
        flight_ttl_seconds: float = 120.0,
        flight_wait_seconds: float = 30.0,
        flight_max_lease_seconds: float | None = None,
    ):
        self._backend = backend
        self._ttl = ttl_seconds
        self._serialize = serialize
        self._deserialize = deserialize
        self._flight_ttl = flight_ttl_seconds
        self._flight_wait = flight_wait_seconds
        self._flight_max_lease = flight_max_lease_seconds
        self._key_locks: dict[str, threading.Lock] = {}
        self._key_locks_guard = threading.Lock()
        # Shared by every flight lock over this backend: whether the lock store
        # has ever answered is a fact about the STORE, and a lock built fresh
        # per request must not keep forgetting it (see _FlightLock._lead).
        self._flight_store_seen = threading.Event()

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
            max_lease_seconds=self._flight_max_lease,
            store_seen=self._flight_store_seen,
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
