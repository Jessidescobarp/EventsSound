"""Money value object: construction, arithmetic, rounding."""

import dataclasses

import pytest

from eventssound.domain.errors import CurrencyMismatch, DomainError, InvalidMoney
from eventssound.domain.money import Money


def test_construct_defaults_to_cop() -> None:
    money = Money(150000)

    assert money.amount == 150000
    assert money.currency == "COP"


@pytest.mark.parametrize(
    "amount",
    [1500.5, True, "1000", None],
    ids=["float", "bool", "str", "none"],
)
def test_non_int_amount_is_rejected(amount: object) -> None:
    with pytest.raises(InvalidMoney):
        Money(amount)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "currency", ["cop", "COPP", "", "C0P"], ids=["lower", "long", "empty", "digit"]
)
def test_invalid_currency_is_rejected(currency: str) -> None:
    with pytest.raises(InvalidMoney):
        Money(1, currency)


def test_negative_amount_is_allowed() -> None:
    assert Money(-1).amount == -1


def test_money_is_immutable() -> None:
    money = Money(1000)

    with pytest.raises(dataclasses.FrozenInstanceError):
        money.amount = 5  # type: ignore[misc]


def test_domain_errors_share_a_base() -> None:
    assert issubclass(InvalidMoney, DomainError)
    assert issubclass(CurrencyMismatch, DomainError)


def test_add_and_multiply() -> None:
    assert Money(1000) + Money(2500) == Money(3500)
    assert Money(1000) * 3 == Money(3000)
    assert 3 * Money(1000) == Money(3000)


def test_subtract_and_negate_allow_negative_results() -> None:
    assert Money(1000) - Money(2000) == Money(-1000)
    assert -Money(500) == Money(-500)


@pytest.mark.parametrize("factor", [1.5, True, "2"], ids=["float", "bool", "str"])
def test_multiplication_only_accepts_int(factor: object) -> None:
    with pytest.raises(TypeError):
        Money(1000) * factor  # type: ignore[operator]


def test_currency_mismatch_raises_on_arithmetic_and_ordering() -> None:
    cop, usd = Money(1000, "COP"), Money(1000, "USD")

    with pytest.raises(CurrencyMismatch):
        cop + usd
    with pytest.raises(CurrencyMismatch):
        cop - usd
    with pytest.raises(CurrencyMismatch):
        assert cop < usd


def test_ordering_within_a_currency() -> None:
    assert Money(1) < Money(2)
    assert Money(2) >= Money(2)
    assert max(Money(1), Money(3)) == Money(3)


def test_equality_distinguishes_currency() -> None:
    assert Money(1, "COP") != Money(1, "USD")


def test_zero_and_sum() -> None:
    assert Money.zero() == Money(0)
    assert Money.sum([Money(1), Money(2), Money(3)]) == Money(6)
    assert Money.sum([], "USD") == Money(0, "USD")


def test_sum_rejects_mixed_currencies() -> None:
    with pytest.raises(CurrencyMismatch):
        Money.sum([Money(1), Money(1, "USD")])


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(0, 0), (499, 0), (500, 1000), (1499, 1000), (1500, 2000), (1999, 2000), (2500, 3000)],
)
def test_round_to_thousand_half_up(amount: int, expected: int) -> None:
    assert Money(amount).round_to(1000) == Money(expected)


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(-499, 0), (-500, 0), (-501, -1000), (-1500, -1000), (-1501, -2000)],
)
def test_round_to_negative_rounds_half_toward_positive_infinity(amount: int, expected: int) -> None:
    assert Money(amount).round_to(1000) == Money(expected)


@pytest.mark.parametrize("step", [0, -1, 1.5, True], ids=["zero", "negative", "float", "bool"])
def test_round_to_rejects_invalid_step(step: object) -> None:
    with pytest.raises(InvalidMoney):
        Money(1500).round_to(step)  # type: ignore[arg-type]


def test_round_to_step_one_is_identity() -> None:
    assert Money(1234).round_to(1) == Money(1234)


@pytest.mark.parametrize(
    ("amount", "bps", "expected"),
    [
        (319900, 1000, 31990),
        (319900, 1500, 47985),
        (319900, 2000, 63980),
        (1, 5000, 1),
        (1, 4999, 0),
        (3, 5000, 2),
        (-1000, 1000, -100),
        (1000, 0, 0),
        (1000, 10000, 1000),
    ],
    ids=[
        "ten-percent",
        "fifteen-percent",
        "twenty-percent",
        "half-up-tie",
        "below-tie",
        "tie-1.5",
        "negative-base",
        "zero-rate",
        "hundred-percent",
    ],
)
def test_percent_is_integer_half_up(amount: int, bps: int, expected: int) -> None:
    assert Money(amount).percent(bps) == Money(expected)


def test_percent_rejects_non_int_bps() -> None:
    with pytest.raises(InvalidMoney):
        Money(1000).percent(0.1)  # type: ignore[arg-type]


def test_operations_with_non_money_operands_raise_type_error() -> None:
    with pytest.raises(TypeError):
        Money(1) + 1  # type: ignore[operator]
    with pytest.raises(TypeError):
        Money(1) - 1  # type: ignore[operator]
    with pytest.raises(TypeError):
        assert Money(1) < 1  # type: ignore[operator]
