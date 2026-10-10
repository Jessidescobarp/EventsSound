"""Application settings loaded from environment variables."""

from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def root_env_file(module: Path | None = None) -> Path | None:
    """Path of the repo-root `.env`, independent of the current working directory.

    Only resolves for the source checkout layout `<root>/backend/src/eventssound/config.py`.
    Any other layout (container image, site-packages) returns None: there, configuration
    comes from real environment variables. A missing file is harmless to pydantic-settings.
    """
    parents = (module or Path(__file__)).resolve().parents
    if len(parents) > 3 and parents[2].name == "backend" and parents[1].name == "src":
        return parents[3] / ".env"
    return None


class Settings(BaseSettings):
    # Environment variables always take precedence over the file.
    model_config = SettingsConfigDict(env_file=root_env_file(), extra="ignore")

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
