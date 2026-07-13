"""Identifier-first login helper.

Given an email, report which sign-in methods the account has (password and/or
which OAuth providers) so the login UI can route the user to the right step -
show the password field, or point them at "Continue with Google" - instead of
letting a Google-only user hit a confusing "invalid credentials" wall.

This deliberately reveals whether an email has an account (the same tradeoff
Google / Slack / Amazon accept for identifier-first login). It is rate-limited
per IP to blunt enumeration, and reads Supabase's `auth` schema directly
through the backend's existing DB connection - no service-role key, no schema
change.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..services.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth-helper"])


class AuthMethodsRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class AuthMethodsResponse(BaseModel):
    exists: bool
    has_password: bool
    providers: list[str]  # oauth providers only, e.g. ["google", "github"]


# auth.identities.provider is "email" for the password credential and the
# provider name (google/github/...) for OAuth. encrypted_password is the
# reliable password check.
_LOOKUP_SQL = text(
    """
    SELECT
        (u.encrypted_password IS NOT NULL AND u.encrypted_password <> '') AS has_password,
        coalesce(
            array_agg(DISTINCT i.provider) FILTER (WHERE i.provider IS NOT NULL),
            ARRAY[]::text[]
        ) AS providers
    FROM auth.users u
    LEFT JOIN auth.identities i ON i.user_id = u.id
    WHERE lower(u.email) = :email
    GROUP BY u.id
    LIMIT 1
    """
)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/methods", response_model=AuthMethodsResponse)
def auth_methods(
    body: AuthMethodsRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    allowed, retry_after = limiter.hit(
        f"authmethods:{_client_ip(request)}",
        settings.auth_methods_rate_per_minute,
    )
    if not allowed:
        raise HTTPException(
            429,
            "Too many requests - please slow down.",
            headers={"Retry-After": str(max(retry_after, 1))},
        )

    email = body.email.strip().lower()
    try:
        row = db.execute(_LOOKUP_SQL, {"email": email}).first()
    except Exception:
        # If the auth schema isn't reachable, degrade to "unknown" so the UI
        # falls back to showing the password field - login must never break
        # because this optional hint failed.
        logger.warning("auth methods lookup failed", exc_info=True)
        raise HTTPException(503, "Sign-in method lookup is unavailable")

    if row is None:
        return AuthMethodsResponse(exists=False, has_password=False, providers=[])
    providers = [p for p in row.providers if p and p != "email"]
    return AuthMethodsResponse(
        exists=True, has_password=bool(row.has_password), providers=providers
    )
