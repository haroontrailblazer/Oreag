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

import hashlib
import logging
import re
import secrets
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


# ── recovery codes ──────────────────────────────────────────────────────────
#
# The way back in when the authenticator is lost. A code does NOT raise the
# assurance level - only Supabase can issue an aal2 session - it REMOVES the
# user's factors. The account then genuinely has no second factor, so aal1 is
# correct for it and the gate in auth/jwt.py opens by itself. See migration
# 0021 for the full reasoning.

RECOVERY_CODE_COUNT = 10
# 10 chars from an unambiguous alphabet ~= 51 bits. Brute force is bounded by
# the login rate limit long before the keyspace matters, and the alphabet omits
# 0/O/1/I/L so a code read off paper is not mistyped.
_RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RECOVERY_CODE_LENGTH = 10


def _hash_code(code: str) -> str:
    """Normalised so formatting never decides whether a code works."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", code).upper()
    return hashlib.sha256(cleaned.encode()).hexdigest()


def generate_recovery_codes(db: Session, user_id: uuid.UUID) -> list[str]:
    """Replace this user's codes with a fresh set. Returns them in PLAINTEXT.

    The only time they can ever be read: nothing but the hash is stored, so a
    caller that loses this response cannot recover it and must regenerate.

    Regenerating invalidates the old set on purpose - a printed sheet that is
    no longer valid must not keep working.
    """
    codes = [
        "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))
        for _ in range(RECOVERY_CODE_COUNT)
    ]
    db.execute(
        text("delete from public.mfa_recovery_codes where user_id = :uid"),
        {"uid": str(user_id)},
    )
    for code in codes:
        db.execute(
            text(
                "insert into public.mfa_recovery_codes (user_id, code_hash)"
                " values (:uid, :hash)"
            ),
            {"uid": str(user_id), "hash": _hash_code(code)},
        )
    db.commit()
    return codes


def unused_recovery_code_count(db: Session, user_id: uuid.UUID) -> int:
    try:
        return int(
            db.execute(
                text(
                    "select count(*) from public.mfa_recovery_codes"
                    " where user_id = :uid and used_at is null"
                ),
                {"uid": str(user_id)},
            ).scalar()
            or 0
        )
    except Exception:  # noqa: BLE001 - table may not exist yet (0021 unapplied)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return 0


def consume_recovery_code(db: Session, user_id: uuid.UUID, code: str) -> bool:
    """Spend one code and strip the user's second factors.

    Returns False for an unknown, already-used or malformed code - the caller
    must not distinguish between those in what it tells the user, since the
    difference is only useful to somebody guessing.

    The UPDATE ... WHERE used_at IS NULL RETURNING is what makes it single-use
    under concurrency: two simultaneous submissions of the same code cannot
    both match, because the first one's write makes the second's predicate
    false.
    """
    row = db.execute(
        text(
            "update public.mfa_recovery_codes set used_at = now()"
            " where user_id = :uid and code_hash = :hash and used_at is null"
            " returning id"
        ),
        {"uid": str(user_id), "hash": _hash_code(code)},
    ).first()
    if row is None:
        db.rollback()
        return False

    # Only now, and in the same transaction, so a failure here cannot leave a
    # code burned with the factor still in place.
    db.execute(
        text("select public.remove_mfa_factors(:uid)"), {"uid": str(user_id)}
    )
    db.commit()

    # The gate memoises "does this user have a factor" for 60 s; without this
    # the user would keep getting 403 for up to a minute after recovering.
    with _lock:
        _cache.pop(user_id, None)
    return True


def reset_cache() -> None:
    """Drop the memoised lookups. For tests, and for an admin-triggered flush."""
    global _function_missing
    with _lock:
        _cache.clear()
    _function_missing = False


# --- second-factor PROMPT preference --------------------------------------
#
# Separate cache from the factor lookup above: the two answer different
# questions ("is a factor enrolled" vs "does this user want to be challenged")
# and change for different reasons, so sharing one entry would let enrolling a
# factor silently reset the preference's freshness, or vice versa.
_prompt_cache: dict[uuid.UUID, tuple[bool, float]] = {}
_prompt_lock = threading.Lock()
_prompt_function_missing = False


def two_factor_prompt_enabled(db: Session, user_id: uuid.UUID) -> bool:
    """Does this user want to be challenged for their second factor?

    TRUE unless they have explicitly turned the prompt off. Every failure path
    also returns True, and that direction is the whole point: the value is only
    ever consulted to decide whether to SKIP enforcement, so an unreadable
    preference must never be the reason a gate opens. An unapplied migration
    0027 therefore behaves exactly like today.
    """
    global _prompt_function_missing

    if _prompt_function_missing:
        return True

    with _prompt_lock:
        entry = _prompt_cache.get(user_id)
    if entry is not None:
        value, cached_at = entry
        if time.monotonic() - cached_at <= settings.mfa_cache_ttl_seconds:
            return value

    try:
        result = db.execute(
            text("select public.two_factor_prompt_enabled(:uid)"),
            {"uid": str(user_id)},
        ).scalar()
        value = True if result is None else bool(result)
    except Exception as exc:  # noqa: BLE001 - see module docstring
        message = str(exc).lower()
        if "two_factor_prompt_enabled" in message and (
            "does not exist" in message or "undefined" in message
        ):
            _prompt_function_missing = True
            logger.info(
                "public.two_factor_prompt_enabled() is missing (migration 0027 "
                "not applied); every account keeps its second-factor prompt."
            )
        else:
            logger.warning("Could not read the 2FA preference; prompting", exc_info=True)
        try:
            db.rollback()
        except Exception:
            logger.debug("Rollback after preference lookup failed", exc_info=True)
        return True

    with _prompt_lock:
        if len(_prompt_cache) > 10_000:
            _prompt_cache.clear()
        _prompt_cache[user_id] = (value, time.monotonic())
    return value


def forget_two_factor_prompt(user_id: uuid.UUID) -> None:
    """Drop the cached preference after a write, so the next request sees it.

    Without this the user flips the switch, the API says OK, and the gate keeps
    firing for up to mfa_cache_ttl_seconds - which reads as the setting not
    working.
    """
    with _prompt_lock:
        _prompt_cache.pop(user_id, None)
