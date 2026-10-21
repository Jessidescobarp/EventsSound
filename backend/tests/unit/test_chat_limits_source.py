"""The chat limits follow the ACTIVE model's price; the environment pair is the fallback."""

from types import SimpleNamespace
from typing import Any

import pytest

from eventssound.entrypoints.api.container import make_chat_limits, make_chat_limits_source

ENV = SimpleNamespace(
    llm_model="vendor/paid",
    llm_input_price_micro_usd_per_mtok=300_000,
    llm_output_price_micro_usd_per_mtok=900_000,
)


class Active:
    def __init__(self, model: str | Exception) -> None:
        self.model = model

    def current(self) -> Any:
        if isinstance(self.model, Exception):
            raise self.model
        return SimpleNamespace(config=SimpleNamespace(llm_model=self.model))


def prices(source: Any) -> tuple[int, int]:
    limits = source()
    return limits.input_price_micro_usd, limits.output_price_micro_usd


def test_without_an_active_provider_it_is_the_env_pair() -> None:
    assert make_chat_limits_source(ENV, None)() == make_chat_limits(ENV)  # type: ignore[arg-type]
    assert prices(make_chat_limits_source(ENV, None)) == (300_000, 900_000)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("vendor/paid", (300_000, 900_000)),  # the env model: byte for byte today's limits
        ("vendor/other:free", (0, 0)),
        ("vendor/unpriced", (300_000, 900_000)),  # no price: fall back to the env pair
        (RuntimeError("boom"), (300_000, 900_000)),  # any failure: the env pair
    ],
)
def test_prices_come_from_the_active_model(
    model: str | Exception, expected: tuple[int, int]
) -> None:
    source = make_chat_limits_source(ENV, Active(model))  # type: ignore[arg-type]

    assert prices(source) == expected
    assert source().request_token_ceiling == make_chat_limits(ENV).request_token_ceiling  # type: ignore[arg-type]
    if model == "vendor/paid":
        assert source() == make_chat_limits(ENV)  # type: ignore[arg-type]


def test_switching_the_active_model_changes_the_next_price() -> None:
    active = Active("vendor/paid")
    source = make_chat_limits_source(ENV, active)  # type: ignore[arg-type]

    before = prices(source)
    active.model = "vendor/other:free"
    after = prices(source)
    active.model = "vendor/paid"

    assert (before, after, prices(source)) == ((300_000, 900_000), (0, 0), (300_000, 900_000))
