"""Quote and QuoteLine: validation, immutability and serialisation."""

import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from eventssound.domain.errors import CurrencyMismatch, DomainError, InvalidQuote
from eventssound.domain.money import Money
from eventssound.domain.pricing import LineKind, Quote, QuoteLine


def make_line(**overrides: Any) -> QuoteLine:
    values: dict[str, Any] = {
        "kind": LineKind.ITEM,
        "code": "speaker_active",
        "label": "Speaker",
        "quantity": 2,
        "periods": 1,
        "unit_amount": Money(120_000),
        "rate_bps": None,
        "basis": None,
        "amount": Money(240_000),
    }
    values.update(overrides)
    return QuoteLine(**values)


def make_quote(**overrides: Any) -> Quote:
    values: dict[str, Any] = {
        "rules_version": "synthetic-v1",
        "currency": "COP",
        "rental_days": 1,
        "lines": (make_line(),),
        "subtotal": Money(240_000),
        "total": Money(240_000),
    }
    values.update(overrides)
    return Quote(**values)


def rounding_line(amount: int) -> QuoteLine:
    return make_line(
        kind=LineKind.ROUNDING,
        code="rounding",
        label=None,
        quantity=1,
        unit_amount=None,
        amount=Money(amount),
    )


def test_line_kinds_match_the_contract() -> None:
    assert [kind.value for kind in LineKind] == [
        "item",
        "package",
        "package_discount",
        "guest_size",
        "weekend_holiday",
        "night",
        "distance",
        "rounding",
    ]


def test_quote_is_frozen_hashable_and_defaults_to_version_1() -> None:
    quote = make_quote(lines=[make_line()])  # a list is coerced to a tuple
    assert quote.version == 1
    assert isinstance(quote.lines, tuple)
    assert hash(quote) == hash(make_quote())
    assert quote == make_quote()
    with pytest.raises(dataclasses.FrozenInstanceError):
        quote.rental_days = 2  # type: ignore[misc]
    assert hash(make_line()) == hash(make_line())


def test_subtotal_is_the_sum_of_non_rounding_lines_and_total_the_sum_of_all() -> None:
    quote = make_quote(
        lines=(make_line(amount=Money(240_500)), rounding_line(-500)),
        subtotal=Money(240_500),
        total=Money(240_000),
    )
    assert quote.total == Money(240_000)


INVALID_LINES: dict[str, Callable[[], QuoteLine]] = {
    "kind-is-a-string": lambda: make_line(kind="item"),
    "empty-code": lambda: make_line(code=""),
    "int-code": lambda: make_line(code=7),
    "int-label": lambda: make_line(label=5),
    "bool-quantity": lambda: make_line(quantity=True),
    "zero-quantity": lambda: make_line(quantity=0),
    "float-quantity": lambda: make_line(quantity=1.5),
    "zero-periods": lambda: make_line(periods=0),
    "int-unit-amount": lambda: make_line(unit_amount=120_000),
    "negative-rate": lambda: make_line(rate_bps=-1),
    "float-rate": lambda: make_line(rate_bps=1.5),
    "str-basis": lambda: make_line(basis="1000"),
    "int-amount": lambda: make_line(amount=240_000),
}


@pytest.mark.parametrize("build", INVALID_LINES.values(), ids=INVALID_LINES.keys())
def test_invalid_line_is_rejected(build: Callable[[], QuoteLine]) -> None:
    with pytest.raises(InvalidQuote):
        build()


INVALID_QUOTES: dict[str, Callable[[], Quote]] = {
    "string-lines": lambda: make_quote(lines="abc"),
    "non-iterable-lines": lambda: make_quote(lines=5),
    "non-line-element": lambda: make_quote(lines=(make_line(), "x")),
    "float-total": lambda: make_quote(total=240_000.0),
    "int-subtotal": lambda: make_quote(subtotal=240_000),
    "total-differs-from-lines": lambda: make_quote(total=Money(240_001)),
    "subtotal-differs-from-lines": lambda: make_quote(subtotal=Money(1)),
    "version-2": lambda: make_quote(version=2),
    "bool-version": lambda: make_quote(version=True),
    "zero-rental-days": lambda: make_quote(rental_days=0),
    "bool-rental-days": lambda: make_quote(rental_days=True),
    "empty-rules-version": lambda: make_quote(rules_version=" "),
    "lowercase-currency": lambda: make_quote(currency="cop"),
    "trailing-newline-currency": lambda: make_quote(currency="COP\n"),
}


@pytest.mark.parametrize("build", INVALID_QUOTES.values(), ids=INVALID_QUOTES.keys())
def test_invalid_quote_is_rejected(build: Callable[[], Quote]) -> None:
    with pytest.raises(DomainError):
        build()


@pytest.mark.parametrize(
    "build",
    [
        lambda: make_quote(total=Money(240_000, "USD")),
        lambda: make_quote(lines=(make_line(amount=Money(240_000, "USD")),)),
        lambda: make_quote(lines=(make_line(unit_amount=Money(120_000, "USD")),)),
        lambda: make_quote(lines=(make_line(basis=Money(1, "USD")),)),
    ],
    ids=["total", "line-amount", "line-unit-amount", "line-basis"],
)
def test_money_in_another_currency_is_rejected(build: Callable[[], Quote]) -> None:
    with pytest.raises(CurrencyMismatch):
        build()


def test_to_dict_contains_only_json_primitives() -> None:
    quote = make_quote(
        lines=(make_line(amount=Money(240_500)), rounding_line(-500)),
        subtotal=Money(240_500),
        total=Money(240_000),
    )
    data = quote.to_dict()
    assert data["version"] == 1
    assert data["currency"] == "COP"
    assert data["total"] == 240_000

    def walk(value: object) -> None:
        if isinstance(value, dict):
            assert all(type(key) is str for key in value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        else:
            assert value is None or type(value) in (int, str)

    walk(data)
