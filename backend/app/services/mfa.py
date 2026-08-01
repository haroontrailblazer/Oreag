"""Server-side second-factor enforcement.

The frontend shows a code prompt when a session is `aal1` and the account has
a factor enrolled. That is a courtesy, not a control: an `aal1` access token
taken out of the browser works against this API with curl unless the API checks
too. This module is that check.

Design notes:

- The decision needs one fact the JWT cannot carry - whether the user has a
  factor AT ALL - because `aal1` is the correct level both for "hasn't done 2FA
  yet" and for "has no 2FA". That fact comes from `public.user_has_verified_mfa`
  (migration 0019), which reads the auth schema behind SECURITY DEFINER.
- The lookup is memoised per user with a short TTL. Enrolling or removing a
  factor takes effect within that window without a restart, and the hot path
  costs no round trip. Same pattern as the pgvector capability probe in
  services/retrieval.py.
- **It fails OPEN.** If the function is missing (0019 not applied) or the query
  errors, users are let through. Failing closed would turn one bad migration or
  a transient database blip into a total, silent lockout of every account with
  two-factor enabled - a far worse outcome than briefly accepting an aal1 token
  from a user who was going to be prompted by the UI anyway.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings

logger = logging.getLogger(__name__)

# user_id -> (has_verified_factor, cached_at_monotonic)
_cache: dict[uuid.UUID, tuple[bool, float]] = {}
_lock = threading.Lock()

# Set once the helper function is found to be missing, so an unapplied
# migration costs one failed query per process rather than one per request.
_function_missing = False


def _cached(user_id: uuid.UUID) -> bool | None:
    with _lock:
        entry = _cache.get(user_id)
    if entry is None:
        return None
    value, cached_at = entry
    if time.monotonic() - cached_at > settings.mfa_cache_ttl_seconds:
        return None
    return value


def _store(user_id: uuid.UUID, value: bool) -> None:
    with _lock:
        # Cheap bound. The cache is keyed by user and each entry is tiny, but an
        # unbounded dict on a long-lived process is still a leak.
        if len(_cache) > 10_000:
            _cache.clear()
        _cache[user_id] = (value, time.monotonic())


def has_verified_factor(db: Session, user_id: uuid.UUID) -> bool:
    """Whether this user has at least one verified MFA factor.

    Returns False on any failure, which is the fail-open direction: no factor
    means no enforcement.
    """
    global _function_missing

    if _function_missing:
        return False

    cached = _cached(user_id)
    if cached is not None:
        return cached

    try:
        result = db.execute(
            text("select public.user_has_verified_mfa(:uid)"),
            {"uid": str(user_id)},
        ).scalar()
        value = bool(result)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see module docstring
        message = str(exc).lower()
        if "user_has_verified_mfa" in message and (
            "does not exist" in message or "undefined" in message
        ):
            # Migration 0019 has not been applied here. Say so once, loudly
            # enough to be actionable, then stop asking.
            _function_missing = True
            logger.warning(
                "MFA enforcement is INACTIVE: public.user_has_verified_mfa() is "
                "missing. Apply supabase/migrations/0019_mfa_enforcement.sql to "
                "enable it."
            )
        else:
            logger.warning("Could not check MFA factors; allowing", exc_info=True)
        # A failed lookup must not roll the caller's transaction into an
        # aborted state - every later statement in it would fail with
        # "current transaction is aborted".
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False

    _store(user_id, value)
    return value


def reset_cache() -> None:
    """Drop the memoised lookups. For tests, and for an admin-triggered flush."""
    global _function_missing
    with _lock:
        _cache.clear()
    _function_missing = False
