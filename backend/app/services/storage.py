from functools import lru_cache

from supabase import Client, create_client

from ..config import settings


@lru_cache(maxsize=1)
def _client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def upload_pdf(path: str, data: bytes) -> None:
    _client().storage.from_(settings.storage_bucket).upload(
        path, data, file_options={"content-type": "application/pdf"}
    )


def download(path: str) -> bytes:
    return _client().storage.from_(settings.storage_bucket).download(path)


def delete(paths: list[str]) -> None:
    if paths:
        _client().storage.from_(settings.storage_bucket).remove(paths)
