"""The root .env.example must document every setting and carry no real secrets."""

from pathlib import Path
from urllib.parse import urlparse

from eventssound.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "db"}


def _parse_env_example() -> dict[str, str]:
    assert ENV_EXAMPLE.is_file(), f"{ENV_EXAMPLE} is missing"
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def test_every_setting_is_documented_in_env_example() -> None:
    documented = set(_parse_env_example())
    expected = {
        (field.validation_alias or name).upper() for name, field in Settings.model_fields.items()
    }
    assert expected <= documented, f"missing from .env.example: {sorted(expected - documented)}"


def test_env_example_documents_compose_and_frontend_variables() -> None:
    documented = set(_parse_env_example())
    assert {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "VITE_API_BASE_URL"} <= documented


def test_env_example_contains_only_local_placeholders() -> None:
    values = _parse_env_example()
    for key in ("DATABASE_URL", "DATABASE_URL_TEST"):
        if key in values:
            assert urlparse(values[key]).hostname in LOCAL_HOSTS, f"{key} must point at a local DB"
    assert values["APP_ENV"] != "production"
    assert "sslmode" not in values["DATABASE_URL"]
