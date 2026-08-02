import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from .. import crypto
from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import ProviderKey
from ..providers.listing import fetch_models
from ..providers.openai_compat import join_azure_credential
from ..schemas import ProviderKeyCreate, ProviderKeyOut
from .deps import ensure_valid_provider_key, heavy_dashboard_limit

router = APIRouter(prefix="/api/provider-keys", tags=["provider-keys"])

logger = logging.getLogger(__name__)

# Whether migration 0022 has been applied, probed once per process.
#
# Without this, deploying the code before running the SQL makes EVERY key save
# fail at flush - a far worse outage than the feature being absent, since it
# locks users out of adding the credential the whole app runs on. Read path has
# the matching guard in routers/meta.py.
_listing_column: bool | None = None


def _can_store_listing(db: Session) -> bool:
    global _listing_column
    if _listing_column is None:
        try:
            db.execute(select(ProviderKey.models_json).limit(1)).all()
            _listing_column = True
        except ProgrammingError:
            db.rollback()
            logger.warning(
                "provider_keys.models_json is missing - apply migration 0022. "
                "Keys still save; per-key model lists stay disabled."
            )
            _listing_column = False
    return _listing_column


@router.get("", response_model=list[ProviderKeyOut])
def list_provider_keys(
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)
):
    return db.scalars(
        select(ProviderKey)
        .where(ProviderKey.owner_id == user_id)
        .order_by(ProviderKey.provider)
    ).all()


@router.put("", response_model=ProviderKeyOut)
def upsert_provider_key(
    body: ProviderKeyCreate,
    user_id: uuid.UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add or replace the account-level key for a provider (one per provider)."""
    # Azure OpenAI is per-resource: the endpoint travels inside the encrypted
    # credential so the rest of key resolution stays a plain string.
    secret = body.key
    if body.provider == "azure":
        if not body.endpoint or not body.endpoint.startswith("https://"):
            raise HTTPException(
                422,
                "Azure OpenAI needs your resource endpoint, e.g. "
                "https://<resource>.openai.azure.com",
            )
        secret = join_azure_credential(body.endpoint, body.key)

    # Ask the provider before trusting the key. Until this existed, any string
    # saved cleanly and turned the provider "available" in /api/models, so a
    # wrong or revoked key was indistinguishable from a good one until a query
    # failed. Runs before the upsert so a rejected key also cannot displace the
    # working one it was meant to replace.
    # `secret`, not body.key: Azure's probe needs the endpoint, which only the
    # joined credential carries.
    ensure_valid_provider_key(body.provider, secret)

    # Ask the vendor what this key can actually reach, here and nowhere else.
    # The pickers read the answer from the column; /api/models never calls a
    # vendor, so a slow or dead provider cannot delay a dashboard load. None
    # means "could not enumerate", which readers treat as no opinion.
    listing = fetch_models(body.provider, secret) if _can_store_listing(db) else None

    existing = db.scalar(
        select(ProviderKey).where(
            ProviderKey.owner_id == user_id,
            ProviderKey.provider == body.provider,
        )
    )
    if existing:
        existing.encrypted_key = crypto.encrypt(secret)
        existing.last4 = crypto.last4(body.key)
        existing.label = body.label
        key = existing
    else:
        key = ProviderKey(
            owner_id=user_id,
            provider=body.provider,
            label=body.label,
            encrypted_key=crypto.encrypt(secret),
            last4=crypto.last4(body.key),
        )
        db.add(key)
    # Only overwrite a previous listing when we have a real one. A failed fetch
    # on a re-save must not throw away a good list from last time - that would
    # silently widen the pickers back to the full catalog.
    if listing is not None:
        key.models_json = listing
        key.models_fetched_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(key)
    return key


@router.post("/{provider}/refresh", response_model=ProviderKeyOut)
def refresh_provider_key_models(
    provider: str,
    user_id: uuid.UUID = Depends(heavy_dashboard_limit),
    db: Session = Depends(get_db),
):
    """Re-ask the provider which models this key can reach.

    Without this the listing could only ever be captured at save time, so every
    key saved before the feature existed would stay unnarrowed for ever and the
    only way to switch it on would be to re-paste a working credential - asking
    the user to re-enter a secret to fix a display problem.

    Also the escape hatch when a vendor grants new access: entitlements change
    (a paid upgrade, a project allowlist edit) without the key itself changing,
    and nothing else would notice.

    On the heavy limiter because it makes an outbound vendor call.
    """
    key = db.scalar(
        select(ProviderKey).where(
            ProviderKey.owner_id == user_id,
            ProviderKey.provider == provider,
        )
    )
    if key is None:
        raise HTTPException(404, "No key saved for this provider")
    if not _can_store_listing(db):
        raise HTTPException(
            503,
            "Per-key model lists are not available yet - migration 0022 has "
            "not been applied.",
        )
    listing = fetch_models(provider, crypto.decrypt(key.encrypted_key))
    if listing is None:
        raise HTTPException(
            502,
            f"Could not read the model list from {provider}. The key is "
            "unchanged and every model stays available.",
        )
    key.models_json = listing
    key.models_fetched_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(key)
    return key


@router.delete("/{provider}", status_code=204)
def delete_provider_key(
    provider: str,
    user_id: uuid.UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    key = db.scalar(
        select(ProviderKey).where(
            ProviderKey.owner_id == user_id,
            ProviderKey.provider == provider,
        )
    )
    if key is not None:
        db.delete(key)
        db.commit()
