"""Embedding settings: defaults, bounds and the OpenRouter requirements."""

import pytest
from pydantic import ValidationError

from eventssound.config import Settings

DB_URL = "postgresql+psycopg://user:pass@127.0.0.1:5432/db"
KEY = "sk-or-v1-supersecretvalue1234567890"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "APP_ENV", "DATABASE_URL", "EMBEDDING_PROVIDER", "EMBEDDING_MODEL",
        "EMBEDDING_DIMENSIONS", "OPENROUTER_API_KEY",
    ):  # fmt: skip
        monkeypatch.delenv(name, raising=False)


def make(**values: object) -> Settings:
    return Settings(_env_file=None, DATABASE_URL=DB_URL, **values)  # type: ignore[arg-type]


def test_defaults_keep_embeddings_off() -> None:
    settings = make()

    assert settings.embedding_provider == "off"
    assert settings.embedding_model == ""
    assert settings.embedding_dimensions == 1024
    assert settings.openrouter_api_key is None


@pytest.mark.parametrize("provider", ["off", "fake"])
def test_off_and_fake_need_no_key_or_model(provider: str) -> None:
    assert make(embedding_provider=provider).embedding_provider == provider


@pytest.mark.parametrize("provider", ["Fake", "openai", "", "ON"])
def test_unknown_providers_are_rejected(provider: str) -> None:
    with pytest.raises(ValidationError):
        make(embedding_provider=provider)


@pytest.mark.parametrize("dimensions", [0, -5, 2001])
def test_dimensions_are_bounded(dimensions: int) -> None:
    with pytest.raises(ValidationError):
        make(embedding_dimensions=dimensions)


@pytest.mark.parametrize("dimensions", [1, 2000])
def test_dimension_boundaries_are_accepted(dimensions: int) -> None:
    assert make(embedding_dimensions=dimensions).embedding_dimensions == dimensions


@pytest.mark.parametrize(
    "extra",
    [{}, {"embedding_model": "m"}, {"openrouter_api_key": KEY}, {"embedding_model": "  ",
     "openrouter_api_key": KEY}, {"embedding_model": "m", "openrouter_api_key": "  "}],
    ids=["nothing", "model-only", "key-only", "blank-model", "blank-key"],
)  # fmt: skip
def test_openrouter_requires_a_model_and_a_key(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as caught:
        make(embedding_provider="openrouter", **extra)

    assert KEY not in str(caught.value)


def test_openrouter_with_model_and_key_is_valid_and_the_key_is_masked() -> None:
    settings = make(embedding_provider="openrouter", embedding_model=" m1 ",
                    openrouter_api_key=KEY)  # fmt: skip

    assert settings.embedding_model == "m1"
    assert settings.openrouter_api_key.get_secret_value() == KEY
    assert KEY not in repr(settings) and KEY not in str(settings)


def test_a_blank_env_value_means_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")

    assert make().openrouter_api_key is None
