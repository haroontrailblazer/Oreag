"""Service-role Supabase admin operations (auth user management)."""
from functools import lru_cache

from supabase import Client, create_client

from ..config import settings


@lru_cache(maxsize=1)
def _admin() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def delete_auth_user(user_id: str) -> None:
    """Permanently delete a Supabase auth user.

    The user's rows in `projects` and `provider_keys` reference
    `auth.users(id) ON DELETE CASCADE`, so this also removes every project,
    file, chunk, api_key, query_log and provider key they own.
    """
    _admin().auth.admin.delete_user(user_id)
