"""Application settings loaded from environment variables."""

from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    database_url: SecretStr = Field(validation_alias="DATABASE_URL")
    # Comma-separated in the environment; NoDecode skips the default JSON parsing.
    cors_allowed_origins: Annotated[list[str], NoDecode] = []
    log_level: str = "INFO"

    @field_validator("database_url", mode="before")
    @classmethod
    def _use_psycopg_driver(cls, value: object) -> object:
        # Neon and most providers hand out `postgres://` or `postgresql://`, which
        # SQLAlchemy would resolve to psycopg2; the project depends on psycopg 3.
        # Only the scheme is rewritten, so query params (sslmode, channel_binding) survive.
        if isinstance(value, str):
            for scheme in ("postgres://", "postgresql://"):
                if value.startswith(scheme):
                    return "postgresql+psycopg://" + value.removeprefix(scheme)
        return value

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            parts = (part.strip().rstrip("/") for part in value.split(","))
            return [part for part in parts if part]
        return value

    @model_validator(mode="after")
    def _reject_wildcard_origin_in_production(self) -> "Settings":
        if self.is_production and "*" in self.cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must not contain '*' in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"
