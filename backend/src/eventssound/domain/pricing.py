"""The quote value objects and `calculate_price`, the deterministic pricing oracle.

Prices never come from an LLM: the agent calls this pure function. No I/O, no clock, no
randomness, integer pesos only.
"""

import dataclasses
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from .catalog import Catalog
from .errors import (
    CurrencyMismatch,
    InvalidCatalog,
    InvalidEventRequest,
    InvalidQuote,
    InvalidRules,
)
from .event_request import EventRequest
from .money import Money
from .pricing_rules import PricingRules

_CURRENCY = re.compile(r"[A-Z]{3}")  # same format as money.py


class LineKind(StrEnum):
    ITEM = "item"
    PACKAGE = "package"
    PACKAGE_DISCOUNT = "package_discount"
    GUEST_SIZE = "guest_size"
    WEEKEND_HOLIDAY = "weekend_holiday"
    NIGHT = "night"
    DISTANCE = "distance"
    ROUNDING = "rounding"


def _require_int(value: object, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise InvalidQuote(f"{name} must be an int >= {minimum}")
    return value


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidQuote(f"{name} must be a non-empty string")
    return value


def _optional_money(value: object, name: str) -> Money | None:
    if value is not None and not isinstance(value, Money):
        raise InvalidQuote(f"{name} must be Money or None")
    return value


def _pesos(value: Money | None) -> int | None:
    return None if value is None else value.amount


@dataclass(frozen=True, slots=True)
class QuoteLine:
    """One explainable line. Unit lines: `quantity * periods * unit_amount`. Percentage lines:
    `basis.percent(rate_bps)`, negated for discounts. The rounding line is a signed adjustment."""

    kind: LineKind
    code: str
    label: str | None
    quantity: int
    periods: int
    unit_amount: Money | None
    rate_bps: int | None
    basis: Money | None
    amount: Money

    def __post_init__(self) -> None:
        if not isinstance(self.kind, LineKind):
            raise InvalidQuote("kind must be a LineKind")
        _require_text(self.code, "code")
        if self.label is not None:
            _require_text(self.label, "label")
        _require_int(self.quantity, "quantity", 1)
        _require_int(self.periods, "periods", 1)
        if self.rate_bps is not None:
            _require_int(self.rate_bps, "rate_bps", 0)
        _optional_money(self.unit_amount, "unit_amount")
        _optional_money(self.basis, "basis")
        if not isinstance(self.amount, Money):
            raise InvalidQuote("amount must be Money")

    def money(self) -> tuple[Money, ...]:
        return tuple(m for m in (self.unit_amount, self.basis, self.amount) if m is not None)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "code": self.code,
            "label": self.label,
            "quantity": self.quantity,
            "periods": self.periods,
            "unit_amount": _pesos(self.unit_amount),
            "rate_bps": self.rate_bps,
            "basis": _pesos(self.basis),
            "amount": self.amount.amount,
        }


def _as_quote_lines(value: object) -> tuple[QuoteLine, ...]:
    if isinstance(value, str | bytes):
        raise InvalidQuote("lines must be a collection of QuoteLine")
    try:
        lines = tuple(value)  # type: ignore[call-overload]
    except TypeError:
        raise InvalidQuote("lines must be a collection of QuoteLine") from None
    if not all(isinstance(line, QuoteLine) for line in lines):
        raise InvalidQuote("lines must contain only QuoteLine")
    return lines


@dataclass(frozen=True, slots=True)
class Quote:
    """An immutable, explainable price. `subtotal` is the raw total before the rounding line and
    `total` the sum of every line, so the lines always reconcile exactly with the total."""

    rules_version: str
    currency: str
    rental_days: int
    lines: tuple[QuoteLine, ...]
    subtotal: Money
    total: Money
    version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "lines", _as_quote_lines(self.lines))
        if type(self.version) is not int or self.version != 1:
            raise InvalidQuote("version must be 1")
        _require_text(self.rules_version, "rules_version")
        if type(self.currency) is not str or not _CURRENCY.fullmatch(self.currency):
            raise InvalidQuote("currency must be a 3-letter uppercase code")
        _require_int(self.rental_days, "rental_days", 1)
        if not isinstance(self.subtotal, Money) or not isinstance(self.total, Money):
            raise InvalidQuote("subtotal and total must be Money")
        monies = (self.subtotal, self.total, *(m for line in self.lines for m in line.money()))
        if any(m.currency != self.currency for m in monies):
            raise CurrencyMismatch("every amount in a quote must use the quote currency")
        rounding = [i for i, x in enumerate(self.lines) if x.kind is LineKind.ROUNDING]
        if rounding and rounding != [len(self.lines) - 1]:
            raise InvalidQuote("at most one rounding line is allowed and it must be last")
        raw = sum(x.amount.amount for x in self.lines if x.kind is not LineKind.ROUNDING)
        if self.subtotal.amount != raw:
            raise InvalidQuote("subtotal must equal the sum of the non-rounding lines")
        if self.total.amount != sum(line.amount.amount for line in self.lines):
            raise InvalidQuote("total must equal the sum of all lines")

    def to_dict(self) -> dict[str, object]:
        """JSON primitives only: whole-peso ints, one top-level currency, None for absent fields."""
        return {
            "version": self.version,
            "rules_version": self.rules_version,
            "currency": self.currency,
            "rental_days": self.rental_days,
            "lines": [line.to_dict() for line in self.lines],
            "subtotal": self.subtotal.amount,
            "total": self.total.amount,
        }


_DAY = timedelta(hours=24)


def _percent_line(kind: LineKind, code: str, basis: Money, bps: int) -> QuoteLine:
    return QuoteLine(kind, code, None, 1, 1, None, bps, basis, basis.percent(bps))


def _equipment_lines(
    request: EventRequest, catalog: Catalog, rules: PricingRules, days: int
) -> list[QuoteLine]:
    # Resolve every code first so the first unknown one is reported, items before packages.
    items = [(catalog.item(line.code), line.quantity) for line in request.items]
    packages = [(catalog.package(line.code), line.quantity) for line in request.packages]
    lines = [
        QuoteLine(
            LineKind.ITEM, item.code, item.name, qty, days, item.unit_price, None, None,
            item.unit_price * (qty * days),
        )
        for item, qty in items
    ]  # fmt: skip
    for package, qty in packages:
        unit = package.base_unit_price(catalog)
        amount = unit * (qty * days)
        lines.append(
            QuoteLine(
                LineKind.PACKAGE, package.code, package.name, qty, days, unit, None, None, amount
            )
        )
        rate = min(package.discount_bps, rules.max_package_discount_bps)
        if rate > 0:
            discount = _percent_line(LineKind.PACKAGE_DISCOUNT, package.code, amount, rate)
            lines.append(dataclasses.replace(discount, amount=-discount.amount))
    return lines


def _touched_dates(start: datetime, end: datetime, rules: PricingRules) -> list[date]:
    """Local dates touched by [start, end): the last instant is end minus one microsecond."""
    first = start.astimezone(rules.timezone).date()
    last = (end - timedelta(microseconds=1)).astimezone(rules.timezone).date()
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


def _is_weekend_or_holiday(dates: list[date], rules: PricingRules) -> bool:
    return any(d.weekday() in rules.weekend_days or d in rules.holidays for d in dates)


def _overlaps_night(start: datetime, end: datetime, dates: list[date], rules: PricingRules) -> bool:
    """Whether [start, end) meets the night window of a touched date or of the previous evening."""
    night = rules.night
    wraps = night.start > night.end
    for day in [dates[0] - timedelta(days=1), *dates]:
        window_start = datetime.combine(day, night.start, tzinfo=rules.timezone)
        window_end = datetime.combine(
            day + timedelta(days=1) if wraps else day, night.end, tzinfo=rules.timezone
        )
        # Compare absolute instants: aware datetimes sharing a tzinfo compare by wall clock.
        if window_start.astimezone(UTC) < end and window_end.astimezone(UTC) > start:
            return True
    return False


def _guest_surcharge_bps(guest_count: int, rules: PricingRules) -> int:
    return [t for t in rules.guest_tiers if t.min_guests <= guest_count][-1].surcharge_bps


def _distance_lines(distance_km: int, rules: PricingRules) -> list[QuoteLine]:
    lines: list[QuoteLine] = []
    floor = 0
    for number, band in enumerate(rules.distance_bands, start=1):
        ceiling = distance_km if band.up_to_km is None else min(distance_km, band.up_to_km)
        km = ceiling - floor
        if km > 0 and band.rate_per_km.amount > 0:
            code = f"distance_band_{number}"
            amount = band.rate_per_km * km
            lines.append(
                QuoteLine(
                    LineKind.DISTANCE, code, None, km, 1, band.rate_per_km, None, None, amount
                )
            )
        if band.up_to_km is not None:
            floor = band.up_to_km
    return lines


def calculate_price(request: EventRequest, catalog: Catalog, rules: PricingRules) -> Quote:
    """Price a request in the fixed order of design section 5; rounding happens once, last."""
    if not isinstance(request, EventRequest):
        raise InvalidEventRequest("request must be an EventRequest")
    if not isinstance(catalog, Catalog):
        raise InvalidCatalog("catalog must be a Catalog")
    if not isinstance(rules, PricingRules):
        raise InvalidRules("rules must be PricingRules")
    if any(item.unit_price.currency != rules.currency for item in catalog.items):
        raise CurrencyMismatch("catalog prices and pricing rules must share one currency")
    request = request.normalized()
    # Absolute instants: wall-clock arithmetic on a shared tzinfo would ignore offset changes.
    span = request.end.astimezone(UTC) - request.start.astimezone(UTC)
    days = max(1, -(-span // _DAY))
    lines = _equipment_lines(request, catalog, rules, days)
    equipment = Money.sum((line.amount for line in lines), rules.currency)
    guest_bps = _guest_surcharge_bps(request.guest_count, rules)
    if guest_bps > 0:
        lines.append(_percent_line(LineKind.GUEST_SIZE, "guest_size", equipment, guest_bps))
    start, end = request.start.astimezone(UTC), request.end.astimezone(UTC)
    dates = _touched_dates(start, end, rules)
    weekend_bps = rules.weekend_holiday_surcharge_bps
    if weekend_bps > 0 and _is_weekend_or_holiday(dates, rules):
        lines.append(
            _percent_line(LineKind.WEEKEND_HOLIDAY, "weekend_holiday", equipment, weekend_bps)
        )
    if rules.night.surcharge_bps > 0 and _overlaps_night(start, end, dates, rules):
        lines.append(_percent_line(LineKind.NIGHT, "night", equipment, rules.night.surcharge_bps))
    lines.extend(_distance_lines(request.distance_km, rules))
    raw = Money.sum((line.amount for line in lines), rules.currency)
    total = raw.round_to(rules.rounding_step)
    if total != raw:
        lines.append(
            QuoteLine(LineKind.ROUNDING, "rounding", None, 1, 1, None, None, None, total - raw)
        )
    return Quote(rules.version, rules.currency, days, tuple(lines), raw, total)
