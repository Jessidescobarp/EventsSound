"""The chat limits follow the ACTIVE model's price; the environment pair is the fallback."""

import dataclasses
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from eventssound.adapters.usage.memory import InMemoryUsageBudget
from eventssound.adapters.usage.rate_limit import InMemoryRateLimiter
from eventssound.application.quote_chat import ChatTurn, quote_chat
from eventssound.entrypoints.api.container import (
    LazyQuoteAgent,
    make_chat_limits,
    make_chat_limits_source,
)

ENV = SimpleNamespace(
    llm_provider="openrouter",
    llm_model="vendor/paid",
    llm_input_price_micro_usd_per_mtok=300_000,
    llm_output_price_micro_usd_per_mtok=900_000,
    llm_model_prices={},
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
        assert source() == dataclasses.replace(make_chat_limits(ENV), model=model)  # type: ignore[arg-type]


def test_switching_the_active_model_changes_the_next_price() -> None:
    active = Active("vendor/paid")
    source = make_chat_limits_source(ENV, active)  # type: ignore[arg-type]

    before = prices(source)
    active.model = "vendor/other:free"
    after = prices(source)
    active.model = "vendor/paid"

    assert (before, after, prices(source)) == ((300_000, 900_000), (0, 0), (300_000, 900_000))


class Flip:
    """The active config changes between two reads of the model (a TTL refresh mid-request)."""

    def __init__(self, *models: str) -> None:
        self.models, self.reads = list(models), 0

    def current(self) -> Any:
        model = self.models[min(self.reads, len(self.models) - 1)]
        self.reads += 1
        return SimpleNamespace(config=SimpleNamespace(llm_model=model))


class Recorder:
    def __init__(self) -> None:
        self.built: list[str] = []
        self.called: list[str] = []

    def build(self, model: str) -> Any:
        self.built.append(model)
        return SimpleNamespace(run=lambda data: self.called.append(model))


class RecordingBudget(InMemoryUsageBudget):
    def __init__(self) -> None:
        super().__init__(token_cap=10**9, cost_cap_micro_usd=10**9)
        self.reserved: list[int] = []

    def reserve(self, tokens: int, cost_micro_usd: int) -> Any:
        self.reserved.append(cost_micro_usd)
        return super().reserve(tokens, cost_micro_usd)


@pytest.mark.parametrize(
    ("first", "second", "cost"),
    [("vendor/x:free", "vendor/paid", 0), ("vendor/paid", "vendor/x:free", 900_000)],
)
def test_the_priced_model_is_the_model_that_runs(first: str, second: str, cost: int) -> None:
    active, rec, budget = Flip(first, second), Recorder(), RecordingBudget()
    agent = LazyQuoteAgent(rec.build, lambda: active.current().config.llm_model)

    quote_chat(
        [ChatTurn("user", "Necesito sonido")],
        "ip",
        agent=agent,  # type: ignore[arg-type]
        budget=budget,
        limiter=InMemoryRateLimiter(100),
        clock=lambda: datetime(2026, 10, 21, tzinfo=UTC),
        limits=make_chat_limits_source(ENV, active)(),  # type: ignore[arg-type]
    )

    assert budget.reserved == [cost]  # priced from the first read...
    assert rec.called == [first]  # ...and exactly that model ran, never the second read


def test_a_pricing_failure_is_logged_by_class_only(caplog: pytest.LogCaptureFixture) -> None:
    source = make_chat_limits_source(ENV, Active(RuntimeError("secret-detail")))  # type: ignore[arg-type]

    with caplog.at_level("WARNING"):
        limits = source()

    assert limits == make_chat_limits(ENV)  # type: ignore[arg-type]
    assert "RuntimeError" in caplog.text and "secret-detail" not in caplog.text


def test_replay_pins_the_environment_model_whatever_is_active() -> None:
    env = SimpleNamespace(**{**vars(ENV), "llm_provider": "replay"})
    source = make_chat_limits_source(env, Active("vendor/other:free"))  # type: ignore[arg-type]

    assert source().model == "vendor/paid" and prices(source) == (300_000, 900_000)
