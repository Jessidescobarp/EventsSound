"""AgentConfig validation, ceilings and the settings fallback."""

import logging
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from eventssound.adapters.openrouter_http import check_model_id
from eventssound.application.agent_config import defaults_from_settings, load_active_config
from eventssound.application.errors import InvalidStoredData, RepositoryUnavailable
from eventssound.application.llm import LlmValidationError
from eventssound.domain.agent_config import (
    MODEL_ID_PATTERN,
    AgentConfig,
    StoredAgentConfig,
    validate_config,
)
from eventssound.domain.errors import InvalidAgentConfig

ALLOWED = ("vendor/model-a", "vendor/model-b")
SETTINGS = SimpleNamespace(
    llm_model="vendor/model-a",
    llm_daily_token_cap=100_000,
    llm_daily_cost_cap_micro_usd=1_000_000,
    chat_rate_limit_per_minute=5,
    allowed_llm_models=ALLOWED,
)
VALID = {
    "tone": "cercano",
    "off_topic_policy": "strict",
    "refusal_message": "Solo cotizo eventos.",
    "closing_message": "Gracias por escribirnos.",
    "welcome_message": "Hola, cuentame de tu evento.",
    "llm_model": "vendor/model-a",
    "daily_token_cap": 50_000,
    "daily_cost_cap_micro_usd": 500_000,
    "chat_rate_limit_per_minute": 10,
}


def parse(**changes: object) -> AgentConfig:
    return AgentConfig.from_mapping({**VALID, **changes}, ALLOWED)


def test_valid_mapping_round_trips_and_stores_normalized_text() -> None:
    config = parse(refusal_message="  Linea uno\n\n\n\nlinea ｄｏｓ  ")
    assert config.refusal_message == "Linea uno\n\nlinea dos"
    assert AgentConfig.from_mapping(config.to_dict(), ALLOWED) == config


# The literals below are the one pin of the hard ceilings (1M tokens, 10 USD, 60 per minute).
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("daily_token_cap", 1),
        ("daily_token_cap", 1_000_000),
        ("daily_cost_cap_micro_usd", 1),
        ("daily_cost_cap_micro_usd", 10_000_000),
        ("chat_rate_limit_per_minute", 1),
        ("chat_rate_limit_per_minute", 60),
        ("refusal_message", "x" * 400),
        ("tone", "formal"),
        ("off_topic_policy", "normal"),
        ("welcome_message", "Evento el 2026-10-25 o el 25.10.2026, a las 10.30."),
        ("welcome_message", "Hola.\nQue evento tienes?\nCuentame."),
    ],
)
def test_boundaries_are_accepted(field: str, value: object) -> None:
    assert getattr(parse(**{field: value}), field) == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("daily_token_cap", 1_000_001),
        ("daily_cost_cap_micro_usd", 10_000_001),
        ("chat_rate_limit_per_minute", 61),
        ("daily_token_cap", 0),
        ("daily_cost_cap_micro_usd", -1),
        ("chat_rate_limit_per_minute", 0),
        ("daily_token_cap", True),
        ("chat_rate_limit_per_minute", 5.0),
        ("daily_cost_cap_micro_usd", "100"),
        ("tone", "sarcastic"),
        ("tone", None),
        ("off_topic_policy", "lax"),
        ("llm_model", "vendor/other"),
        ("llm_model", ""),
        ("llm_model", 7),
        ("refusal_message", ""),
        ("refusal_message", "   "),
        ("closing_message", "x" * 401),
        ("welcome_message", 5),
        ("welcome_message", "a\nb\nc\nd"),
        ("welcome_message", "<b>hola</b>"),
        ("welcome_message", "a > b"),
        ("welcome_message", "＜b＞hola"),
        ("welcome_message", "[aqui](x)"),
        ("welcome_message", "usa `codigo`"),
        ("welcome_message", "Tom &amp; Jerry"),
        ("welcome_message", "visita http://x.co"),
        ("welcome_message", "visita HTTPS://x.co"),
        ("welcome_message", "visita ｈｔｔｐｓ：//x"),
        ("welcome_message", "entra a www.sitio.com"),
        ("welcome_message", "entra a w\u200bww.sitio.com"),
        ("welcome_message", "entra a sitio.\u200bcom"),
        ("welcome_message", "entra a sitio.xyz"),
        ("welcome_message", "escribe a ana@correo.com"),
        ("welcome_message", "escribe a ana＠correo"),
        ("welcome_message", "llamanos al 300 123 4567"),
        ("welcome_message", "llama +57-300-1234567"),
        ("welcome_message", "llama 3001234567"),
        ("welcome_message", "llama 555-1234"),
        ("welcome_message", "bad\x00char"),
        ("welcome_message", "bad\x85char"),
        ("welcome_message", "bad\u202echar"),
        ("welcome_message", "bad\u2028char"),
        ("welcome_message", "bad\tchar"),
    ],
)
def test_invalid_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(InvalidAgentConfig):
        parse(**{field: value})


@pytest.mark.parametrize(
    "mapping", [{**VALID, "extra": 1}, {k: v for k, v in VALID.items() if k != "tone"}, []]
)
def test_unknown_missing_or_non_mapping_is_rejected(mapping: object) -> None:
    with pytest.raises(InvalidAgentConfig):
        AgentConfig.from_mapping(mapping, ALLOWED)  # type: ignore[arg-type]


def test_error_never_echoes_the_value() -> None:
    with pytest.raises(InvalidAgentConfig) as raised:
        parse(welcome_message="escribe a ana@correo.com")
    assert "ana@" not in str(raised.value)


@pytest.mark.parametrize("model", ["vendor/model-a", "a b", "-x", "", "x" * 121, "a;b"])
def test_model_check_agrees_with_the_adapter(model: str) -> None:
    try:
        check_model_id(model)
        adapter_ok = True
    except LlmValidationError:
        adapter_ok = False
    assert bool(MODEL_ID_PATTERN.fullmatch(model)) is adapter_ok
    if not adapter_ok:  # an allowlisted entry that is not a valid id is still rejected
        with pytest.raises(InvalidAgentConfig):
            validate_config(replace(parse(), llm_model=model), (model,))


def test_default_texts_pass_the_validator() -> None:
    defaults = defaults_from_settings(SETTINGS)
    assert validate_config(defaults, ALLOWED) == defaults


def test_defaults_keep_unmetered_and_out_of_bounds_values() -> None:
    odd = SimpleNamespace(
        **{**vars(SETTINGS), "llm_daily_token_cap": 0, "chat_rate_limit_per_minute": 100}
    )
    defaults = defaults_from_settings(odd)
    assert (defaults.daily_token_cap, defaults.chat_rate_limit_per_minute) == (0, 100)


class FakeRepo:
    def __init__(self, active: StoredAgentConfig | None = None, error: Exception | None = None):
        self.active, self.error = active, error

    def get_active(self) -> StoredAgentConfig | None:
        if self.error:
            raise self.error
        return self.active


def stored(**changes: object) -> StoredAgentConfig:
    config = replace(parse(), **changes)
    return StoredAgentConfig(config, 3, datetime(2026, 10, 20, tzinfo=UTC), None)


def test_load_returns_the_stored_config() -> None:
    result = load_active_config(FakeRepo(stored()), SETTINGS)  # type: ignore[arg-type]
    assert result.config == parse() and result.version == 3


@pytest.mark.parametrize(
    "repo",
    [
        FakeRepo(None),
        FakeRepo(error=RepositoryUnavailable()),
        FakeRepo(error=RuntimeError("boom")),
        FakeRepo(error=InvalidStoredData()),
        FakeRepo(stored(daily_token_cap=1_000_001)),
        FakeRepo(stored(llm_model="vendor/removed")),
    ],
)
def test_load_falls_back_to_defaults_without_raising(
    repo: FakeRepo, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        result = load_active_config(repo, SETTINGS)  # type: ignore[arg-type]
    assert result.config == defaults_from_settings(SETTINGS) and result.version == 0
    assert "vendor/removed" not in caplog.text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ()),
        ("a/b:free, c/d:free ,,a/b:free", ("a/b:free", "c/d:free")),
    ],
)
def test_settings_allowlist_parsing(raw: str, expected: tuple[str, ...]) -> None:
    from eventssound.config import Settings

    settings = Settings(DATABASE_URL="postgresql://u:p@127.0.0.1/x", llm_model_allowlist=raw)  # type: ignore[arg-type]
    assert settings.allowed_llm_models == expected
    only_default = Settings(DATABASE_URL="postgresql://u:p@127.0.0.1/x", llm_model="v/m")
    assert only_default.allowed_llm_models == ("v/m",)


def _settings(**over: object) -> Any:
    from eventssound.config import Settings

    return Settings(_env_file=None, DATABASE_URL="postgresql://u:p@127.0.0.1/x", **over)  # type: ignore[call-arg, arg-type]


@pytest.mark.parametrize("extra", ["v/m:free", "v/m,v/m2:free,v/m3:free", " v/m:free ,v/m2:free "])
def test_startup_accepts_the_env_model_and_free_extras(extra: str) -> None:
    settings = _settings(llm_model="v/m", llm_model_allowlist=extra)

    assert settings.allowed_llm_models == tuple(p.strip() for p in extra.split(","))


@pytest.mark.parametrize(
    "allowlist",
    [
        "v/m,v/paid",
        "v/m:free,v/paid-model",
        "v/other:FREE",
        "v/x:free-extra",
        "free:v/x",
        "v/xFf1afree",  # fullwidth colon
        "v/x:free00a0",  # non-breaking space is not trimmed
        "v/x:free:",
    ],
)
def test_startup_rejects_a_paid_extra_naming_it_without_secrets(allowlist: str) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as raised:
        _settings(llm_model="v/m", llm_model_allowlist=allowlist, openrouter_api_key="sk-secret-1")

    text = str(raised.value)
    offender = next(m for m in allowlist.split(",") if m not in ("v/m", "v/m:free"))
    assert offender in text and "sk-secret-1" not in text and "postgresql" not in text


@pytest.mark.parametrize("model", ["v/m:free", "a:free"])
def test_the_free_suffix_is_a_valid_model_id_for_both_checks(model: str) -> None:
    check_model_id(model)
    assert MODEL_ID_PATTERN.fullmatch(model)
    assert validate_config(replace(parse(), llm_model=model), (model,)).llm_model == model
    with pytest.raises(InvalidAgentConfig):
        validate_config(replace(parse(), llm_model=model), ALLOWED)  # not in the allowlist


@pytest.mark.parametrize(
    "model",
    ["a/b:free\n", "a/b :free", "a//b:free", "https://a.b:free", "a\\b:free", "a/b:fr\x00ee"],
)
def test_free_lookalikes_with_bad_shapes_are_still_rejected(model: str) -> None:
    assert not MODEL_ID_PATTERN.fullmatch(model)
    with pytest.raises(LlmValidationError):
        check_model_id(model)


@pytest.mark.parametrize("field", ["closing_message", "refusal_message", "welcome_message"])
@pytest.mark.parametrize("text", ["total $1.000 COP", "descuento 100%", "solo $"])
def test_every_text_rejects_money_and_percent_symbols(field: str, text: str) -> None:
    with pytest.raises(InvalidAgentConfig, match=field):
        parse(**{field: text})


@pytest.mark.parametrize("field", ["closing_message", "refusal_message"])
@pytest.mark.parametrize("text", ["total 5", "ciento １２", "Cotiza ya 2x1"])
def test_closing_and_refusal_reject_any_digit(field: str, text: str) -> None:
    with pytest.raises(InvalidAgentConfig, match=field) as raised:
        parse(**{field: text})
    assert text not in str(raised.value)


def test_welcome_keeps_digits_for_opening_hours() -> None:
    assert parse(welcome_message="Atendemos de 8 a 18 h").welcome_message == "Atendemos de 8 a 18 h"


PRICES = '{"v/paid": {"input": 3000000, "output": 15000000}}'


@pytest.mark.parametrize(
    ("allowlist", "prices"),
    [
        ("v/m,v/paid", PRICES),
        ("v/paid,v/x:free", PRICES),
        ("v/m,v/x:free", '{"v/x:free": {"input": 0, "output": 0}}'),
        ("v/m", '{"v/m": {"input": 1, "output": 2}}'),  # table agrees with the env pair
    ],
)
def test_startup_accepts_a_paid_extra_with_a_declared_price(allowlist: str, prices: str) -> None:
    settings = _settings(
        llm_model="v/m",
        llm_model_allowlist=allowlist,
        llm_model_prices=prices,
        llm_input_price_micro_usd_per_mtok=1,
        llm_output_price_micro_usd_per_mtok=2,
    )
    assert set(settings.llm_model_prices) <= set(settings.allowed_llm_models)


@pytest.mark.parametrize(
    ("allowlist", "prices"),
    [
        ("v/m,v/other", PRICES),  # unpriced paid extra
        ("v/m", PRICES),  # priced model not in the allowlist
        ("v/m,v/x:free", '{"v/x:free": {"input": 1, "output": 0}}'),  # ':free' but priced
        ("v/m", '{"v/m": {"input": 9, "output": 2}}'),  # disagrees with the env pair
        ("v/m,v/paid", '{"v/paid": {"input": 0, "output": 0}}'),  # paid but priced 0/0
        ("v/m,v/paid", "{oops sk-secret-1"),  # malformed JSON
        ("v/m,v/paid", '{"v/paid": {"input": 2000000000, "output": 1}}'),  # over the ceiling
    ],
)
def test_startup_rejects_bad_price_tables_without_secrets(allowlist: str, prices: str) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as raised:
        _settings(
            llm_model="v/m",
            llm_model_allowlist=allowlist,
            llm_model_prices=prices,
            llm_input_price_micro_usd_per_mtok=1,
            llm_output_price_micro_usd_per_mtok=2,
            openrouter_api_key="sk-secret-1",
        )
    assert "sk-secret-1" not in str(raised.value) and "postgresql" not in str(raised.value)
