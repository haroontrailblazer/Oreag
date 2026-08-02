import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import ProviderKey
from ..providers import ollama_provider, openai_compat, st_provider
from ..providers.listing import merge_catalog
from ..providers.registry import CATALOG, deprecated_model_ids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/models")
def list_models(
    user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Provider/model catalog + live availability, so the wizard only offers
    options that will actually work. Key-based providers are available when the
    current user has supplied their own key (BYOK); local providers are probed."""
    # provider + its cached model list in ONE read. models_json is a plain
    # column - no decryption, no vendor call - so this route still does zero
    # network I/O; the listing was fetched when the key was saved.
    #
    # Tolerates an unapplied migration 0022 rather than 500-ing on it. Code
    # reaches Render before SQL reaches Supabase, and without this the gap is a
    # hard outage of the model pickers - i.e. nobody can create a project -
    # instead of the feature simply lying dormant. Same posture as the MFA gate
    # in services/mfa.py, which fails open on its own missing function.
    try:
        rows = db.execute(
            select(ProviderKey.provider, ProviderKey.models_json).where(
                ProviderKey.owner_id == user_id
            )
        ).all()
    except ProgrammingError:
        # The failed statement poisons the transaction; clear it before reusing
        # this session for the fallback query.
        db.rollback()
        logger.warning(
            "provider_keys.models_json is missing - apply migration 0022. "
            "Serving the full static catalog until then."
        )
        rows = [
            (provider, None)
            for provider in db.scalars(
                select(ProviderKey.provider).where(ProviderKey.owner_id == user_id)
            ).all()
        ]
    user_providers = {provider for provider, _ in rows}
    listings = {provider: models for provider, models in rows}
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
        "catalog": merge_catalog(CATALOG, listings),
        # Retired ids, reported alongside rather than removed from the catalog:
        # a project that already stores one must keep resolving, so the pickers
        # hide it instead. Additive field - older clients ignore it.
        "deprecated": deprecated_model_ids(),
        "availability": {
            **{provider: provider in user_providers for provider in keyed},
            "ollama": ollama_provider.is_available(),
            "lmstudio": openai_compat.lmstudio_is_available(),
            "sentence_transformers": st_provider.is_available(),
        },
    }
