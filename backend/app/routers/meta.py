import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import ProviderKey
from ..providers import ollama_provider, st_provider
from ..providers.registry import CATALOG

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/models")
def list_models(
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Provider/model catalog + live availability, so the wizard only offers
    options that will actually work. Key-based providers are available when the
    current user has supplied their own key (BYOK); local providers are probed."""
    user_providers = set(
        db.scalars(
            select(ProviderKey.provider).where(ProviderKey.owner_id == user_id)
        ).all()
    )
    return {
        "catalog": CATALOG,
        "availability": {
            "openai": "openai" in user_providers,
            "gemini": "gemini" in user_providers,
            "anthropic": "anthropic" in user_providers,
            "sarvam": "sarvam" in user_providers,
            "ollama": ollama_provider.is_available(),
            "sentence_transformers": st_provider.is_available(),
        },
    }
