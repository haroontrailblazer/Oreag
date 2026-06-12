import uuid

from fastapi import APIRouter, Depends

from ..auth.jwt import get_current_user
from ..config import settings
from ..providers import ollama_provider, st_provider
from ..providers.registry import CATALOG

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/models")
def list_models(user_id: uuid.UUID = Depends(get_current_user)):
    """Provider/model catalog + live availability, so the wizard only offers
    options that will actually work."""
    return {
        "catalog": CATALOG,
        "availability": {
            "openai": bool(settings.openai_api_key),
            "ollama": ollama_provider.is_available(),
            "sentence_transformers": st_provider.is_available(),
        },
    }
