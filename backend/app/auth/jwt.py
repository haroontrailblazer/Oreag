import uuid

import jwt as pyjwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from ..config import settings

bearer_scheme = HTTPBearer(auto_error=False)

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
) -> uuid.UUID:
    """Validate the Supabase access token and return the user id (sub)."""
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
    return uuid.UUID(payload["sub"])
