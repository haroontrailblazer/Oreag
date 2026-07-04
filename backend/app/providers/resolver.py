"""Resolve which API key to use for a project's embedding / LLM provider.

Precedence: per-project override -> owner's account-level key -> None.

Resolution is keyed on ``project.owner_id`` (NOT the request user) so it works
identically for the dashboard (JWT) and the public ``/v1`` endpoint, which has
no user token - only the project row.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto
from ..models import Project, ProviderKey

# Providers that run locally and need no API key.
KEYLESS_PROVIDERS = {"ollama", "sentence_transformers"}


def requires_key(provider: str) -> bool:
    return provider not in KEYLESS_PROVIDERS


def _account_key(db: Session, owner_id, provider: str) -> str | None:
    row = db.scalar(
        select(ProviderKey).where(
            ProviderKey.owner_id == owner_id,
            ProviderKey.provider == provider,
        )
    )
    return crypto.decrypt(row.encrypted_key) if row else None


def resolve_embedding_key(db: Session, project: Project) -> str | None:
    if not requires_key(project.embedding_provider):
        return None
    if project.embedding_key_encrypted:
        return crypto.decrypt(project.embedding_key_encrypted)
    return _account_key(db, project.owner_id, project.embedding_provider)


def resolve_llm_key(db: Session, project: Project) -> str | None:
    if not requires_key(project.llm_provider):
        return None
    if project.llm_key_encrypted:
        return crypto.decrypt(project.llm_key_encrypted)
    return _account_key(db, project.owner_id, project.llm_provider)
