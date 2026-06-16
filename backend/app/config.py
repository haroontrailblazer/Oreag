from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    storage_bucket: str = "project-files"

    jwt_mode: str = "jwks"  # "jwks" (new Supabase projects) or "hs256" (legacy)
    supabase_jwt_secret: str = ""
    supabase_jwt_aud: str = "authenticated"

    # BYOK: users supply their own provider keys; no shared server key is used.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    app_encryption_key: str = ""

    openai_api_key: str = ""  # deprecated — kept only so old .env files don't error
    ollama_base_url: str = "http://localhost:11434"

    cors_origins: str = "http://localhost:3000,http://192.168.56.1:3000"

    max_upload_bytes: int = 50 * 1024 * 1024


settings = Settings()
