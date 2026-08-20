from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Events Aggregator"
    app_host: str = "0.0.0.0"
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"

    database_url: str = Field(
        default="postgresql+asyncpg://events:events@localhost:5432/events",
        validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_CONNECTION_STRING"),
    )

    events_provider_base_url: str = "https://events-provider.dev-2.python-labs.ru"
    events_provider_api_key: Optional[SecretStr] = Field(
        default=None,
        validation_alias=AliasChoices(
            "EVENTS_PROVIDER_API_KEY",
            "EVENTS_PROVIDER_TOKEN",
            "EVENTS_API_KEY",
            "X_API_KEY",
        ),
    )
    events_provider_events_path: str = "/api/events/"
    events_provider_auth_mode: Literal["api_key", "token", "bearer"] = "api_key"
    events_provider_timeout_seconds: float = Field(default=10.0, gt=0)

    sync_enabled: bool = True
    sync_run_on_startup: bool = True
    sync_interval_seconds: float = Field(default=86_400, gt=0)
    sync_batch_size: int = Field(default=100, ge=1, le=10_000)
    sync_overlap_seconds: float = Field(default=1.0, ge=0, le=300)
    seats_cache_ttl_seconds: float = Field(default=30.0, gt=0)

    @field_validator("database_url")
    @classmethod
    def use_async_postgres_driver(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("events_provider_events_path")
    @classmethod
    def paths_start_with_slash(cls, value: str) -> str:
        value = value if value.startswith("/") else f"/{value}"
        return value if value.endswith("/") else f"{value}/"


@lru_cache
def get_settings() -> Settings:
    return Settings()
