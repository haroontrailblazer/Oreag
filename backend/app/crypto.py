"""Symmetric encryption for user-supplied provider API keys (BYOK).

Keys are encrypted at rest with Fernet (AES-128-CBC + HMAC) using the app-wide
APP_ENCRYPTION_KEY. We only ever store ciphertext + the last 4 chars for masked
display, so a database dump never leaks usable credentials.
"""
from functools import lru_cache

from cryptography.fernet import Fernet

from .config import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    if not settings.app_encryption_key:
        raise RuntimeError(
            "APP_ENCRYPTION_KEY is not configured — generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and set it in the environment."
        )
    return Fernet(settings.app_encryption_key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def last4(plaintext: str) -> str:
    """The trailing 4 chars, stored alongside the ciphertext for masked display."""
    return plaintext[-4:]


def apply_override(value: str | None) -> tuple[str | None, str | None] | None:
    """Map an incoming per-project key override to ``(encrypted, last4)``.

    Returns ``None`` when ``value`` is ``None`` (leave the columns untouched);
    ``(None, None)`` when ``value`` is an empty string (clear the override and
    fall back to the account key); otherwise the encrypted pair.
    """
    if value is None:
        return None
    if value == "":
        return (None, None)
    return (encrypt(value), last4(value))
