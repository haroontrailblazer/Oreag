import uuid

import jwt as pyjwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..services.mfa import has_verified_factor
from ..services.rate_limit import enforce_user_rate_limit

bearer_scheme = HTTPBearer(auto_error=False)

# Sent with the 403 below so the frontend can tell "finish two-factor" apart
# from "your session expired" WITHOUT string-matching a human message. Getting
# this wrong bounces users to the login page in a loop: they sign in, get a
# 403, get logged out, sign in again.
MFA_REQUIRED_HEADER = "X-MFA-Required"

# Sent with the 403 when the session has no second factor AND has not proved
# control of the mailbox. A separate header from the one above because the two
# lead to DIFFERENT pages - a user sent to the authenticator prompt with no
# authenticator has nowhere to go.
EMAIL_VERIFICATION_HEADER = "X-Email-Verification-Required"

# Sign-in methods that prove only "knows a secret" or "has a linked account".
# Neither demonstrates control of the mailbox at THIS sign-in:
#
#   - `password` is a shared secret that leaks in breaches, which is the exact
#     attack an emailed code is being added to stop.
#   - `oauth` proves the Google/GitHub account, and those addresses can differ
#     from the one on file or be re-pointed at the provider.
#
# Anything else in `amr` - otp, magiclink, a passkey, a cleared factor - is
# accepted, so a user with a real factor or a passkey is never asked for a code
# on top.
_WEAK_AMR_METHODS = frozenset({"password", "oauth", "sso/saml", "web3", "anonymous"})


def _proved_email_control(payload: dict) -> bool:
    """Did this session use a method stronger than password/OAuth alone?

    Reads the `amr` claim, which lists every method the session was minted
    with. A missing or unparseable claim returns True - FAIL OPEN.

    That direction is deliberate. This check is a hardening step, and the cost
    of the two failure modes is wildly asymmetric: failing open lets a session
    through that should have seen one extra email, while failing closed on an
    unexpected token shape locks EVERY user out of the product with no way back
    in, because the remedy is behind the same gate. A claim we cannot read is a
    surprise about Supabase, not evidence of an attack.
    """
    amr = payload.get("amr")
    if not isinstance(amr, list) or not amr:
        return True
    methods = set()
    for entry in amr:
        if isinstance(entry, dict) and isinstance(entry.get("method"), str):
            methods.add(entry["method"])
        elif isinstance(entry, str):
            methods.add(entry)
    if not methods:
        return True
    return bool(methods - _WEAK_AMR_METHODS)

_jwk_client: PyJWKClient | None = None


def _get_jwk_client() -> PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(
            f"{settings.supabase_url}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
        )
    return _jwk_client


def _decode(creds: HTTPAuthorizationCredentials | None) -> dict:
    """Validate the bearer token's signature and audience, or 401."""
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = creds.credentials
    try:
        if settings.jwt_mode == "hs256":
            return pyjwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience=settings.supabase_jwt_aud,
            )
        signing_key = _get_jwk_client().get_signing_key_from_jwt(token)
        return pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience=settings.supabase_jwt_aud,
        )
    except pyjwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


def get_user_pending_mfa(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> uuid.UUID:
    """Authenticate WITHOUT the two-factor gate.

    Exists for exactly one thing: the recovery-code endpoint. A user who has
    lost their authenticator is stuck at aal1 by definition, so every route
    behind ``get_current_user`` answers 403 - including the one route that
    could get them unstuck. This is the chicken-and-egg the recovery flow has
    to break.

    The token is still fully verified: signature, audience, expiry. All that is
    skipped is the aal check. Do NOT reuse this anywhere else - it is a hole in
    the gate, kept honest by having a single caller whose own rate limit and
    single-use codes are the real protection.
    """
    payload = _decode(creds)
    user_id = uuid.UUID(payload["sub"])
    enforce_user_rate_limit(user_id, heavy=True)
    return user_id


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    """Validate the Supabase access token and return the user id (sub).

    Also enforces two-factor authentication. The token carries an ``aal``
    claim - ``aal2`` once a second factor has been cleared - but that claim
    alone is not a rule, because ``aal1`` is equally correct for an account
    with no second factor at all. So a token below ``aal2`` is only rejected
    once the database confirms the user actually has a verified factor.

    Doing this here rather than per-router means every authenticated endpoint
    is covered by construction, and a new route cannot forget it. ``get_db`` is
    dependency-cached by FastAPI, so routes that already take a session share
    it and this costs no extra connection.

    Public ``/v1`` traffic authenticates with API keys through a different
    dependency and is deliberately untouched: an API key is not a person and
    has no second factor to present.
    """
    payload = _decode(creds)
    user_id = uuid.UUID(payload["sub"])

    # 403, never 401: the token is valid and the session is real, it just has
    # not cleared the second factor. A 401 would read as "signed out" to every
    # client and trigger a re-login that lands in exactly the same state.
    if settings.mfa_enforce_aal2 and payload.get("aal") != "aal2":
        if has_verified_factor(db, user_id):
            raise HTTPException(
                status_code=403,
                detail="Two-factor authentication required for this session.",
                headers={MFA_REQUIRED_HEADER: "1"},
            )
        # No factor enrolled. An emailed code is then the ONLY thing standing
        # between a leaked password (or a compromised Google/GitHub account)
        # and this session, so require it here rather than in the UI - a
        # client-side prompt is skipped by anyone calling the API directly,
        # which is precisely the caller worth stopping.
        #
        # Checked in this branch only: an account WITH a factor already had a
        # real challenge, and asking it for a code as well would be a second
        # gate for no extra assurance.
        elif settings.email_verification_required and not _proved_email_control(
            payload
        ):
            raise HTTPException(
                status_code=403,
                detail="Confirm your email to finish signing in.",
                headers={EMAIL_VERIFICATION_HEADER: "1"},
            )

    # Per-user budget for the whole dashboard API. Applied here for the same
    # reason as the check above: every authenticated route is covered by
    # construction, and a route added tomorrow cannot forget it. The expensive
    # endpoints additionally take `heavy_dashboard_limit` (see routers/deps.py).
    enforce_user_rate_limit(user_id)

    return user_id
