import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ApiKey

KEY_PREFIX = "oreag_sk_"

bearer_scheme = HTTPBearer(auto_error=False)


def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, sha256_hash, display_prefix)."""
    full_key = KEY_PREFIX + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, key_hash, full_key[:16]


def hash_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode()).hexdigest()


def require_api_key(
    project_id: uuid.UUID,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> ApiKey:
    """Authenticate a public /v1 request against the project's API keys."""
    if creds is None or not creds.credentials.startswith(KEY_PREFIX):
        raise HTTPException(status_code=401, detail="Missing or malformed API key")
    api_key = db.scalar(
        select(ApiKey).where(
            ApiKey.key_hash == hash_key(creds.credentials),
            ApiKey.project_id == project_id,
            ApiKey.revoked_at.is_(None),
        )
    )
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    api_key.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return api_key
