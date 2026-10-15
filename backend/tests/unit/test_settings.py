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


def test_wildcard_cors_origin_is_rejected_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example,*")

    with pytest.raises(ValidationError, match="CORS_ALLOWED_ORIGINS"):
        Settings(_env_file=None)


def test_wildcard_cors_origin_is_allowed_outside_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")

    assert Settings(_env_file=None).cors_allowed_origins == ["*"]


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_database_url_scheme_is_mapped_to_psycopg(
    monkeypatch: pytest.MonkeyPatch, scheme: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"{scheme}://user:pass@host:5432/db")

    url = Settings(_env_file=None).database_url.get_secret_value()

    assert url == "postgresql+psycopg://user:pass@host:5432/db"


def test_database_url_keeps_query_params(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgres://u:p@h/db?sslmode=require&channel_binding=require"
    )

    url = Settings(_env_file=None).database_url.get_secret_value()

    assert url == "postgresql+psycopg://u:p@h/db?sslmode=require&channel_binding=require"


def test_database_url_is_hidden_from_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:s3cret@host/db")

    settings = Settings(_env_file=None)

    assert "s3cret" not in repr(settings)
    assert "s3cret" not in str(settings)


@pytest.mark.parametrize(
    ("value", "usable"),
    [
        ("s" * 32, True),
        ("s" * 31, False),
        ("", False),
        ("   ", False),
        ("changeme" * 5, False),
        ("replace-with-a-long-random-secret-0000", False),
    ],
    ids=["ok", "short", "empty", "blank", "placeholder", "template-text"],
)
def test_jwt_secret_counts_as_set_only_when_long_and_not_a_placeholder(
    value: str, usable: bool
) -> None:
    settings = Settings(_env_file=None, DATABASE_URL=DB_URL, jwt_secret=value)  # type: ignore[arg-type]

    assert (settings.jwt_secret is not None) is usable


def test_auth_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, DATABASE_URL=DB_URL)  # type: ignore[arg-type]

    assert settings.jwt_secret is None
    assert settings.jwt_access_ttl_minutes == 60
    assert settings.login_rate_limit_per_minute == 5
