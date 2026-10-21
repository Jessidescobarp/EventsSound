"""The per-model price table: the environment model keeps its prices, `:free` ids cost 0."""

from types import SimpleNamespace

import pytest

from eventssound.domain.model_prices import ModelPrice, is_free_model, price_for


def env(model: str = "vendor/paid", inp: int = 300_000, out: int = 900_000) -> SimpleNamespace:
    return SimpleNamespace(
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
