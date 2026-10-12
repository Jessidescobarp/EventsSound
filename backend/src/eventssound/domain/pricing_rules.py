"""Pricing rules as validated data, plus the synthetic default rule set.

Percentages are integer basis points (1 bp = 0.01%) and money is whole pesos. The rules take a
`tzinfo` object, never a zone name, so only `default_pricing_rules()` touches the tz database.
"""

from dataclasses import dataclass
from datetime import date, time, tzinfo
from zoneinfo import ZoneInfo

from .errors import InvalidRules
from .money import Money

MAX_SURCHARGE_BPS = 100_000


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
        object.__setattr__(self, "guest_tiers", tuple(self.guest_tiers))
        object.__setattr__(self, "distance_bands", tuple(self.distance_bands))
        if not isinstance(self.version, str) or not self.version.strip():
            raise InvalidRules("version must not be empty")
        if not (len(self.currency) == 3 and self.currency.isascii() and self.currency.isupper()):
            raise InvalidRules("currency must be a 3-letter uppercase code")
        if not isinstance(self.timezone, tzinfo):
            raise InvalidRules("timezone must be a tzinfo")
        if not all(type(day) is int and 0 <= day <= 6 for day in self.weekend_days):
            raise InvalidRules("weekend_days must hold weekday numbers 0..6")
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
