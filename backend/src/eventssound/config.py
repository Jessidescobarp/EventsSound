"""Application settings loaded from environment variables."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from eventssound.domain.model_prices import FREE_SUFFIX, is_free_model


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


MIN_JWT_SECRET_CHARS = 32
_PLACEHOLDERS = ("changeme", "replace-with", "your-secret", "placeholder")


class Settings(BaseSettings):
    # Environment variables always take precedence over the file.
    # hide_input_in_errors: a ValidationError would otherwise print the raw input values
    # (the database URL, the API key) into logs and tracebacks.
    model_config = SettingsConfigDict(
        env_file=root_env_file(), extra="ignore", hide_input_in_errors=True
    )

    app_env: str = "local"
    database_url: SecretStr = Field(validation_alias="DATABASE_URL")
    # Comma-separated in the environment; NoDecode skips the default JSON parsing.
    cors_allowed_origins: Annotated[list[str], NoDecode] = []
    log_level: str = "INFO"
    # Embeddings (vector retrieval). `off` means keyword search only.
    embedding_provider: Literal["off", "fake", "openrouter"] = "off"
    embedding_model: str = ""
    embedding_dimensions: int = 1024
    openrouter_api_key: SecretStr | None = None
    # Public quote chat. The kill switch and the replay default mean a forgotten variable
    # can never spend money.
    chat_enabled: bool = True
    llm_provider: Literal["replay", "openrouter"] = "replay"
    llm_model: str = ""
    # Models an admin may select, comma-separated. Empty means only `llm_model`.
    llm_model_allowlist: Annotated[list[str], NoDecode] = []
    llm_input_price_micro_usd_per_mtok: Annotated[int, Field(ge=0)] = 0
    llm_output_price_micro_usd_per_mtok: Annotated[int, Field(ge=0)] = 0
    llm_daily_token_cap: Annotated[int, Field(ge=0)] = 100_000
    llm_daily_cost_cap_micro_usd: Annotated[int, Field(ge=0)] = 1_000_000
    chat_rate_limit_per_minute: Annotated[int, Field(ge=1, le=1000)] = 5
    # Login. An unset, short or placeholder secret disables the auth routes in production.
    jwt_secret: SecretStr | None = None
    jwt_access_ttl_minutes: Annotated[int, Field(ge=1, le=1440)] = 60
    login_rate_limit_per_minute: Annotated[int, Field(ge=1, le=1000)] = 5
    # How many reverse proxies sit in front of the app (Render: 1). 0 ignores X-Forwarded-For.
    trusted_proxy_hops: Annotated[int, Field(ge=0, le=3)] = 0

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

    @field_validator("openrouter_api_key", mode="before")
    @classmethod
    def _blank_key_is_missing(cls, value: object) -> object:
        # `OPENROUTER_API_KEY=` in .env.example means "not set".
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("jwt_secret", mode="after")
    @classmethod
    def _weak_secret_is_missing(cls, value: SecretStr | None) -> SecretStr | None:
        # Fewer than 32 characters or an obvious placeholder is the same as not set.
        if value is None:
            return None
        text = value.get_secret_value().strip()
        weak = len(text) < MIN_JWT_SECRET_CHARS or any(w in text.lower() for w in _PLACEHOLDERS)
        return None if weak else value

    @field_validator("app_env", "llm_provider", mode="before")
    @classmethod
    def _normalize_case(cls, value: object) -> object:
        # ' Production ' is production; a casing typo must not crash the whole API at startup.
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("embedding_model", "llm_model", mode="after")
    @classmethod
    def _strip_model(cls, value: str) -> str:
        return value.strip()

    @field_validator("embedding_dimensions")
    @classmethod
    def _dimensions_match_the_column(cls, value: int) -> int:
        # vector(1024) is frozen in migration 0003; another size is a new revision plus a refresh.
        if value != 1024:
            raise ValueError("EMBEDDING_DIMENSIONS must be 1024 (the size of the table column)")
        return value

    @model_validator(mode="after")
    def _fake_embeddings_never_run_in_production(self) -> "Settings":
        if self.is_production and self.embedding_provider == "fake":
            raise ValueError("EMBEDDING_PROVIDER=fake is not allowed in production")
        return self

    @model_validator(mode="after")
    def _openrouter_embeddings_need_a_key_and_model(self) -> "Settings":
        if self.embedding_provider == "openrouter" and not (
            self.embedding_model and self.openrouter_api_key
        ):
            raise ValueError("EMBEDDING_PROVIDER=openrouter needs EMBEDDING_MODEL and the API key")
        return self

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

    @field_validator("llm_model_allowlist", mode="before")
    @classmethod
    def _split_models(cls, value: object) -> object:
        if isinstance(value, str):
            return [part for part in (p.strip() for p in value.split(",")) if part]
        return value

    @model_validator(mode="after")
    def _allowlist_extras_must_be_free(self) -> "Settings":
        # Fail closed: only the environment model has a configured price, every other selectable
        # model must be free, so a model switch can never spend money the cost cap cannot see.
        for model in self.llm_model_allowlist:
            if model != self.llm_model and not is_free_model(model):
                raise ValueError(
                    f"LLM_MODEL_ALLOWLIST entry {model!r} must be LLM_MODEL or end with "
                    f"{FREE_SUFFIX!r}"
                )
        return self

    @property
    def allowed_llm_models(self) -> tuple[str, ...]:
        """Models an admin may pick: the allowlist, or just the configured one when it is empty."""
        if self.llm_model_allowlist:
            return tuple(dict.fromkeys(self.llm_model_allowlist))
        return (self.llm_model,) if self.llm_model else ()

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def chat_active(self) -> bool:
        """Whether `POST /quote/chat` may serve answers.

        A misconfigured chat disables itself instead of failing startup, so the catalog API
        stays up. The replay provider only serves fixtures and never runs in production.
        """
        if not self.chat_enabled:
            return False
        if self.llm_provider == "openrouter":
            return bool(self.llm_model and self.openrouter_api_key)
        return not self.is_production
