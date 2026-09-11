"""Application configuration, loaded from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- App -----
    app_name: str = "Tilly Trading"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # ----- Database -----
    # Defaults to a local SQLite file so the app runs with zero external
    # services. Docker Compose overrides these with the Postgres URLs.
    database_url: str = "sqlite+aiosqlite:///./tilly.db"
    database_url_sync: str = "sqlite:///./tilly.db"
    # Set true for hosted Postgres that requires SSL (Supabase, RDS, etc.).
    database_ssl: bool = False
    # Set true when using the Supabase connection pooler (pgBouncer, port 6543).
    database_pgbouncer: bool = False
    # Echo every SQL statement (very verbose) — off by default.
    db_echo: bool = False

    # ----- Redis / Celery -----
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ----- Auth -----
    jwt_secret_key: str = "change-me-to-a-long-random-string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # ----- CORS -----
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # ----- Broker (MetaAPI) -----
    metaapi_token: str = ""
    metaapi_region: str = "new-york"
    metaapi_default_account_id: str = ""

    # ----- AI presets (optional) -----
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        """Allow a comma-separated string in the env file."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
