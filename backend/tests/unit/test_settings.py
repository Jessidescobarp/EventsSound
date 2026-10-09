import pytest
from pydantic import ValidationError

from eventssound.config import Settings

DB_URL = "postgresql+psycopg://user:pass@localhost:5432/db"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_ENV", "DATABASE_URL", "CORS_ALLOWED_ORIGINS", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)


def test_missing_database_url_names_the_variable() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, cors_allowed_origins="http://localhost:5173")

    assert "DATABASE_URL" in str(exc_info.value).upper()


def test_cors_origins_are_split_and_trailing_slash_stripped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS", "http://localhost:5173/, https://app.example/ ,https://b.example"
    )

    settings = Settings(_env_file=None)

    assert settings.cors_allowed_origins == [
        "http://localhost:5173",
        "https://app.example",
        "https://b.example",
    ]


def test_defaults_and_production_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    local = Settings(_env_file=None)
    assert local.app_env == "local"
    assert local.log_level == "INFO"
    assert local.cors_allowed_origins == []
    assert local.is_production is False

    monkeypatch.setenv("APP_ENV", "production")
    assert Settings(_env_file=None).is_production is True
