"""The per-model price table: env model keeps its prices, `:free` ids cost 0, others if declared."""

import json
from types import SimpleNamespace

import pytest

from eventssound.domain.model_prices import (
    MAX_PRICE_MICRO_USD_PER_MTOK,
    ModelPrice,
    is_free_model,
    parse_model_prices,
    price_for,
)


def env(
    model: str = "vendor/paid",
    inp: int = 300_000,
    out: int = 900_000,
    prices: dict[str, tuple[int, int]] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        llm_model_prices=prices or {},
        llm_model=model,
        llm_input_price_micro_usd_per_mtok=inp,
        llm_output_price_micro_usd_per_mtok=out,
    )


@pytest.mark.parametrize(
    ("model", "settings", "expected"),
    [
        ("vendor/paid", env(), ModelPrice(300_000, 900_000, False)),  # env model: env pair
        ("vendor/paid", env(inp=0, out=0), ModelPrice(0, 0, False)),  # even 0, not "free"
        ("vendor/x:free", env("vendor/x:free", 0, 0), ModelPrice(0, 0, True)),
        ("vendor/other:free", env(), ModelPrice(0, 0, True)),  # free suffix: 0 whatever the env
        (
            "vendor/x:free",
            env("vendor/x:free"),
            ModelPrice(300_000, 900_000, False),
        ),  # env pair wins
        ("vendor/other", env(), None),  # a paid extra has no price
        ("v/extra", env(prices={"v/extra": (5, 7)}), ModelPrice(5, 7, False)),  # declared
        ("v/z:free", env(prices={"v/z:free": (0, 0)}), ModelPrice(0, 0, True)),
        ("v/extra", env(prices={"v/extra": (0, 0)}), ModelPrice(0, 0, False)),  # 0 is not free
        ("", env(), None),
        *[
            (m, env(), None)
            for m in ("foo:free-extra", "foo:FREE", "free:foo", "foo:free ", "free")
        ],
    ],
)
def test_price_for(model: str, settings: SimpleNamespace, expected: ModelPrice | None) -> None:
    assert price_for(model, settings) == expected


@pytest.mark.parametrize(
    ("model", "free"),
    [("a/b:free", True), (":free", True), ("a/b", False), ("a/b:FREE", False), ("a:free:x", False)],
)
def test_is_free_model(model: str, free: bool) -> None:
    assert is_free_model(model) is free


GOOD = {"v/a": {"input": 3, "output": 9}, "v/b:free": {"input": 0, "output": 0}}
TOP = MAX_PRICE_MICRO_USD_PER_MTOK


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", {}),
        ("  ", {}),
        ("{}", {}),
        (json.dumps(GOOD), {"v/a": (3, 9), "v/b:free": (0, 0)}),
        (GOOD, {"v/a": (3, 9), "v/b:free": (0, 0)}),
        (json.dumps({"v/a": {"input": TOP, "output": 0}}), {"v/a": (TOP, 0)}),  # boundary
    ],
)
def test_parse_model_prices_accepts(raw: object, expected: dict[str, tuple[int, int]]) -> None:
    assert parse_model_prices(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "{not json sk-secret",
        "[]",
        "null",
        '"x"',
        {"bad id": {"input": 1, "output": 1}},
        {"a//b": {"input": 1, "output": 1}},
        {"v/a": {"input": 1}},
        {"v/a": {"input": 1, "output": 1, "extra": 1}},
        {"v/a": [1, 2]},
        {"v/a": {"input": -1, "output": 1}},
        {"v/a": {"input": TOP + 1, "output": 1}},
        {"v/a": {"input": 1.5, "output": 1}},
        {"v/a": {"input": "3", "output": 1}},
        {"v/a": {"input": True, "output": 1}},
        {f"v/m{i}": {"input": 1, "output": 1} for i in range(51)},
    ],
)
def test_parse_model_prices_rejects_without_echoing_the_input(raw: object) -> None:
    with pytest.raises(ValueError) as raised:
        parse_model_prices(raw if isinstance(raw, str | dict) else json.dumps(raw))
    assert "sk-secret" not in str(raised.value) and "bad id" not in str(raised.value)
