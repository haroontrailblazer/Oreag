import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import ProviderKey
from ..providers import ollama_provider, openai_compat, st_provider
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
    keyed = [
        "openai",
        "gemini",
        "anthropic",
        "azure",
        "sarvam",
        "xai",
        "groq",
        "mistral",
        "deepseek",
        "cohere",
        "together",
        "fireworks",
        "openrouter",
        "perplexity",
        "voyage",
        "jina",
    ]
    return {
        "catalog": CATALOG,
        "availability": {
            **{provider: provider in user_providers for provider in keyed},
            "ollama": ollama_provider.is_available(),
            "lmstudio": openai_compat.lmstudio_is_available(),
            "sentence_transformers": st_provider.is_available(),
        },
    }
