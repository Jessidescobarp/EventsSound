"""Application settings loaded from environment variables."""

from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    database_url: str = Field(validation_alias="DATABASE_URL")
    # Comma-separated in the environment; NoDecode skips the default JSON parsing.
    cors_allowed_origins: Annotated[list[str], NoDecode] = []
    log_level: str = "INFO"

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            parts = (part.strip().rstrip("/") for part in value.split(","))
            return [part for part in parts if part]
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"
