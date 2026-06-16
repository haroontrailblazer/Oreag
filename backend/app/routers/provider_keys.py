import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto
from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import ProviderKey
from ..schemas import ProviderKeyCreate, ProviderKeyOut

router = APIRouter(prefix="/api/provider-keys", tags=["provider-keys"])


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
    existing = db.scalar(
        select(ProviderKey).where(
            ProviderKey.owner_id == user_id,
            ProviderKey.provider == body.provider,
        )
    )
    if existing:
        existing.encrypted_key = crypto.encrypt(body.key)
        existing.last4 = crypto.last4(body.key)
        existing.label = body.label
        key = existing
    else:
        key = ProviderKey(
            owner_id=user_id,
            provider=body.provider,
            label=body.label,
            encrypted_key=crypto.encrypt(body.key),
            last4=crypto.last4(body.key),
        )
        db.add(key)
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
