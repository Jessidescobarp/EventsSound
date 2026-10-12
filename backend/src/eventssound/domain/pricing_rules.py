"""Pricing rules as validated data, plus the synthetic default rule set.

Percentages are integer basis points (1 bp = 0.01%) and money is whole pesos. The rules take a
`tzinfo` object, never a zone name, so only `default_pricing_rules()` touches the tz database.
"""

import re
from dataclasses import dataclass
from datetime import date, time, tzinfo
from zoneinfo import ZoneInfo

from .errors import InvalidRules
from .money import Money

MAX_SURCHARGE_BPS = 100_000
_CURRENCY = re.compile(r"[A-Z]{3}")  # same format as money.py


def _collect[T: (tuple, frozenset)](value: object, kind: type[T], name: str) -> T:
    """Coerce to an immutable collection; a string is never a collection of rule data."""
    if isinstance(value, str | bytes):
        raise InvalidRules(f"{name} must be a collection")
    try:
        return kind(value)  # type: ignore[call-arg]
    except TypeError:
        raise InvalidRules(f"{name} must be a collection") from None


def _require_int(value: object, name: str) -> int:
    if type(value) is not int:
        raise InvalidRules(f"{name} must be an int")
    return value


def _check_bps(value: object, name: str, upper: int = MAX_SURCHARGE_BPS) -> int:
    if not 0 <= _require_int(value, name) <= upper:
        raise InvalidRules(f"{name} must be within 0..{upper} basis points")
    return value


@dataclass(frozen=True, slots=True)
class GuestTier:
    """Surcharge that applies from `min_guests` guests upward."""

    min_guests: int
    surcharge_bps: int

    def __post_init__(self) -> None:
        if _require_int(self.min_guests, "min_guests") < 1:
            raise InvalidRules("min_guests must be >= 1")
        _check_bps(self.surcharge_bps, "surcharge_bps")


@dataclass(frozen=True, slots=True)
class DistanceBand:
    """Marginal rate per km up to `up_to_km` (None = open-ended last band)."""

    up_to_km: int | None
    rate_per_km: Money

    def __post_init__(self) -> None:
        if self.up_to_km is not None and _require_int(self.up_to_km, "up_to_km") < 1:
            raise InvalidRules("up_to_km must be >= 1")
        if not isinstance(self.rate_per_km, Money) or self.rate_per_km.amount < 0:
            raise InvalidRules("rate_per_km must be non-negative Money")


@dataclass(frozen=True, slots=True)
class NightWindow:
    """Local-time window with a flat surcharge; it wraps midnight when start > end."""

    start: time
    end: time
    surcharge_bps: int

    def __post_init__(self) -> None:
        for name, value in (("start", self.start), ("end", self.end)):
            if not isinstance(value, time) or value.tzinfo is not None:
                raise InvalidRules(f"night {name} must be a naive local time")
        if self.start == self.end:
            raise InvalidRules("night start and end must differ")
        _check_bps(self.surcharge_bps, "night surcharge_bps")


@dataclass(frozen=True, slots=True)
class PricingRules:
    version: str
    currency: str
    timezone: tzinfo
    guest_tiers: tuple[GuestTier, ...]
    weekend_days: frozenset[int]
    holidays: frozenset[date]
    weekend_holiday_surcharge_bps: int
    night: NightWindow
    distance_bands: tuple[DistanceBand, ...]
    max_package_discount_bps: int
    rounding_step: int

    def __post_init__(self) -> None:
        guest_tiers = _collect(self.guest_tiers, tuple, "guest_tiers")
        bands = _collect(self.distance_bands, tuple, "distance_bands")
        weekend_days = _collect(self.weekend_days, frozenset, "weekend_days")
        holidays = _collect(self.holidays, frozenset, "holidays")
        object.__setattr__(self, "guest_tiers", guest_tiers)
        object.__setattr__(self, "distance_bands", bands)
        object.__setattr__(self, "weekend_days", weekend_days)
        object.__setattr__(self, "holidays", holidays)
        if not isinstance(self.version, str) or not self.version.strip():
            raise InvalidRules("version must not be empty")
        if type(self.currency) is not str or not _CURRENCY.fullmatch(self.currency):
            raise InvalidRules("currency must be a 3-letter uppercase code")
        if not isinstance(self.timezone, tzinfo):
            raise InvalidRules("timezone must be a tzinfo")
        if not isinstance(self.night, NightWindow):
            raise InvalidRules("night must be a NightWindow")
        if not all(isinstance(t, GuestTier) for t in guest_tiers):
            raise InvalidRules("guest_tiers must contain only GuestTier")
        if not all(isinstance(b, DistanceBand) for b in bands):
            raise InvalidRules("distance_bands must contain only DistanceBand")
        if not weekend_days or not all(type(d) is int and 0 <= d <= 6 for d in weekend_days):
            raise InvalidRules("weekend_days must be a non-empty set of weekday numbers 0..6")
        if not all(type(d) is date for d in holidays):
            raise InvalidRules("holidays must contain only dates")
        _check_bps(self.weekend_holiday_surcharge_bps, "weekend_holiday_surcharge_bps")
        _check_bps(self.max_package_discount_bps, "max_package_discount_bps", 10_000)
        if _require_int(self.rounding_step, "rounding_step") < 1:
            raise InvalidRules("rounding_step must be >= 1")
        self._check_tiers()
        self._check_bands()

    def _check_tiers(self) -> None:
        tiers = self.guest_tiers
        if not tiers or tiers[0].min_guests != 1:
            raise InvalidRules("guest tiers must start at 1 guest")
        for previous, current in zip(tiers, tiers[1:], strict=False):
            if current.min_guests <= previous.min_guests:
                raise InvalidRules("guest tiers must be strictly increasing")
            if current.surcharge_bps < previous.surcharge_bps:
                raise InvalidRules("guest tier surcharges must not decrease")

    def _check_bands(self) -> None:
        bands = self.distance_bands
        if not bands or bands[-1].up_to_km is not None:
            raise InvalidRules("distance bands must end with an open-ended band")
        limits = [b.up_to_km for b in bands[:-1]]
        if None in limits or limits != sorted(set(limits)):
            raise InvalidRules("distance band limits must be strictly increasing")
        if any(b.rate_per_km.currency != self.currency for b in bands):
            raise InvalidRules("distance band rates must use the rules currency")


def default_pricing_rules() -> PricingRules:
    """Synthetic owner rules, version `synthetic-v1`."""
    return PricingRules(
        version="synthetic-v1",
        currency="COP",
        timezone=ZoneInfo("America/Bogota"),
        guest_tiers=(
            GuestTier(1, 0),
            GuestTier(101, 1000),
            GuestTier(301, 2500),
            GuestTier(601, 4000),
        ),
        weekend_days=frozenset({5, 6}),
        holidays=frozenset(),
        weekend_holiday_surcharge_bps=1500,
        night=NightWindow(time(22, 0), time(6, 0), 2000),
        distance_bands=(
            DistanceBand(20, Money(0)),
            DistanceBand(60, Money(3000)),
            DistanceBand(None, Money(4500)),
        ),
        max_package_discount_bps=2000,
        rounding_step=1000,
    )
