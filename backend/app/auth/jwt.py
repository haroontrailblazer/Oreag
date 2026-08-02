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

_jwk_client: PyJWKClient | None = None


def _get_jwk_client() -> PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(
            f"{settings.supabase_url}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
        )
    return _jwk_client


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
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = creds.credentials
    try:
        if settings.jwt_mode == "hs256":
            payload = pyjwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience=settings.supabase_jwt_aud,
            )
        else:
            signing_key = _get_jwk_client().get_signing_key_from_jwt(token)
            payload = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience=settings.supabase_jwt_aud,
            )
    except pyjwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

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

    # Per-user budget for the whole dashboard API. Applied here for the same
    # reason as the check above: every authenticated route is covered by
    # construction, and a route added tomorrow cannot forget it. The expensive
    # endpoints additionally take `heavy_dashboard_limit` (see routers/deps.py).
    enforce_user_rate_limit(user_id)

    return user_id
