"""Money in whole currency units (COP has no practical minor unit). Integers only, never floats."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import total_ordering

from .errors import CurrencyMismatch, InvalidMoney

_CURRENCY = re.compile(r"[A-Z]{3}")


def _require_int(value: object, name: str) -> int:
    if type(value) is not int:
        raise InvalidMoney(f"{name} must be an int")
    return value


@total_ordering
@dataclass(frozen=True, slots=True)
class Money:
    """Immutable amount in whole pesos. Any sign is allowed (discount lines are negative)."""

    amount: int
    currency: str = "COP"

    def __post_init__(self) -> None:
        _require_int(self.amount, "amount")
        if type(self.currency) is not str or not _CURRENCY.fullmatch(self.currency):
            raise InvalidMoney("currency must be a 3-letter uppercase code")

    @classmethod
    def zero(cls, currency: str = "COP") -> "Money":
        return cls(0, currency)

    @classmethod
    def sum(cls, values: Iterable["Money"], currency: str = "COP") -> "Money":
        total = cls.zero(currency)
        for value in values:
            total = total + value
        return total

    def _check(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(f"cannot combine {self.currency} with {other.currency}")

    def __add__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)

    def __mul__(self, factor: object) -> "Money":
        if type(factor) is not int:
            return NotImplemented
        return Money(self.amount * factor, self.currency)

    __rmul__ = __mul__

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._check(other)
        return self.amount < other.amount

    def percent(self, bps: int) -> "Money":
        """Basis points of this amount, integer half-up (1500 bps = 15%)."""
        _require_int(bps, "bps")
        return Money((2 * self.amount * bps + 10_000) // 20_000, self.currency)

    def round_to(self, step: int) -> "Money":
        """Round to the nearest multiple of `step`; ties go toward positive infinity."""
        if _require_int(step, "step") < 1:
            raise InvalidMoney("step must be >= 1")
        return Money((2 * self.amount + step) // (2 * step) * step, self.currency)
