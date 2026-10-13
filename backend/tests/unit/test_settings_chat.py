"""Chat settings: validation bounds and when the chat may serve answers."""

import pytest
from pydantic import ValidationError

from eventssound.config import Settings

DB = {"DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1:1/x"}
KEY = {"OPENROUTER_API_KEY": "sk-or-v1-abc", "LLM_MODEL": "a/b", "LLM_PROVIDER": "openrouter"}


def make(**values):
    return Settings(_env_file=None, **DB, **values)


def test_defaults_start_without_any_chat_setting_and_cost_nothing() -> None:
    settings = make()
    assert settings.chat_enabled and settings.llm_provider == "replay"
    assert settings.trusted_proxy_hops == 0 and settings.chat_active


@pytest.mark.parametrize(
    "bad",
    [
        {"TRUSTED_PROXY_HOPS": 4},
        {"TRUSTED_PROXY_HOPS": -1},
        {"CHAT_RATE_LIMIT_PER_MINUTE": 0},
        {"LLM_DAILY_TOKEN_CAP": -1},
        {"LLM_DAILY_COST_CAP_MICRO_USD": -1},
        {"LLM_INPUT_PRICE_MICRO_USD_PER_MTOK": -1},
        {"LLM_PROVIDER": "gpt"},
    ],
)
def test_out_of_range_values_are_rejected(bad) -> None:
    with pytest.raises(ValidationError):
        make(**bad)


@pytest.mark.parametrize(
    ("values", "active"),
    [
        ({"CHAT_ENABLED": False}, False),
        ({"APP_ENV": "production"}, False),
        ({**KEY, "APP_ENV": "production"}, True),
        ({**KEY, "OPENROUTER_API_KEY": ""}, False),
        ({**KEY, "LLM_MODEL": " "}, False),
        ({**KEY, "CHAT_ENABLED": False}, False),
    ],
)
def test_chat_active(values, active) -> None:
    assert make(**values).chat_active is active


def test_the_api_key_never_shows_in_repr() -> None:
    assert "sk-or-v1-abc" not in repr(make(**KEY))
