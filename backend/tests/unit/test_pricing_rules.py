"""PricingRules: validation of the rule data and the synthetic defaults."""

import dataclasses
from collections.abc import Callable
from datetime import date, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from eventssound.domain.errors import InvalidRules
from eventssound.domain.money import Money
from eventssound.domain.pricing_rules import (
    DistanceBand,
    GuestTier,
    NightWindow,
    PricingRules,
    default_pricing_rules,
)


def make_rules(**overrides: Any) -> PricingRules:
    return dataclasses.replace(default_pricing_rules(), **overrides)


def band(up_to: int | None, rate: int = 1000) -> DistanceBand:
    return DistanceBand(up_to, Money(rate))


def test_default_rules_match_the_design() -> None:
    rules = default_pricing_rules()
    assert rules.version == "synthetic-v1"
    assert rules.currency == "COP"
    assert rules.guest_tiers == (
        GuestTier(1, 0),
        GuestTier(101, 1000),
        GuestTier(301, 2500),
        GuestTier(601, 4000),
    )
    assert rules.weekend_days == frozenset({5, 6})
    assert rules.holidays == frozenset()
    assert rules.weekend_holiday_surcharge_bps == 1500
    assert rules.distance_bands == (band(20, 0), band(60, 3000), band(None, 4500))
    assert rules.max_package_discount_bps == 2000
    assert rules.rounding_step == 1000


def test_default_night_window_wraps_midnight_in_bogota() -> None:
    rules = default_pricing_rules()
    assert rules.night == NightWindow(time(22, 0), time(6, 0), 2000)
    assert rules.night.start > rules.night.end
    assert rules.timezone == ZoneInfo("America/Bogota")


def test_rules_are_frozen_and_hashable() -> None:
    rules = default_pricing_rules()
    with pytest.raises(dataclasses.FrozenInstanceError):
        rules.rounding_step = 1  # type: ignore[misc]
    assert hash(rules) == hash(default_pricing_rules())


def test_swapping_data_needs_no_code_change() -> None:
    assert make_rules(rounding_step=500).rounding_step == 500
    assert make_rules(holidays=frozenset({date(2026, 12, 25)})).holidays
    assert make_rules(timezone=ZoneInfo("America/Lima")).timezone.key == "America/Lima"


def test_collections_are_coerced_to_tuples() -> None:
    rules = make_rules(guest_tiers=[GuestTier(1, 0)], distance_bands=[band(None)])
    assert isinstance(rules.guest_tiers, tuple)
    assert isinstance(rules.distance_bands, tuple)


INVALID: dict[str, Callable[[], PricingRules]] = {
    "no-tiers": lambda: make_rules(guest_tiers=()),
    "first-tier-not-one": lambda: make_rules(guest_tiers=(GuestTier(2, 0),)),
    "tiers-not-increasing": lambda: make_rules(guest_tiers=(GuestTier(1, 0), GuestTier(1, 5))),
    "tier-surcharge-decreases": lambda: make_rules(
        guest_tiers=(GuestTier(1, 500), GuestTier(10, 100))
    ),
    "tier-negative-bps": lambda: make_rules(guest_tiers=(GuestTier(1, -1),)),
    "tier-bps-too-high": lambda: make_rules(guest_tiers=(GuestTier(1, 100_001),)),
    "tier-zero-guests": lambda: make_rules(guest_tiers=(GuestTier(0, 0),)),
    "tier-float-guests": lambda: make_rules(guest_tiers=(GuestTier(1.0, 0),)),
    "no-bands": lambda: make_rules(distance_bands=()),
    "bands-not-increasing": lambda: make_rules(distance_bands=(band(20), band(15), band(None))),
    "bands-equal-limits": lambda: make_rules(distance_bands=(band(20), band(20), band(None))),
    "open-band-not-last": lambda: make_rules(distance_bands=(band(None), band(20))),
    "last-band-bounded": lambda: make_rules(distance_bands=(band(20), band(60))),
    "band-zero-limit": lambda: make_rules(distance_bands=(band(0), band(None))),
    "band-negative-rate": lambda: make_rules(distance_bands=(band(None, -1),)),
    "band-mixed-currency": lambda: make_rules(
        distance_bands=(band(20), DistanceBand(None, Money(1, "USD")))
    ),
    "night-start-equals-end": lambda: make_rules(night=NightWindow(time(6), time(6), 2000)),
    "night-negative-bps": lambda: make_rules(night=NightWindow(time(22), time(6), -1)),
    "night-aware-time": lambda: make_rules(
        night=NightWindow(time(22, tzinfo=ZoneInfo("UTC")), time(6), 2000)
    ),
    "step-zero": lambda: make_rules(rounding_step=0),
    "step-float": lambda: make_rules(rounding_step=1000.0),
    "no-timezone": lambda: make_rules(timezone=None),
    "weekend-bps-negative": lambda: make_rules(weekend_holiday_surcharge_bps=-1),
    "weekend-day-out-of-range": lambda: make_rules(weekend_days=frozenset({7})),
    "discount-cap-over-100": lambda: make_rules(max_package_discount_bps=10_001),
    "discount-cap-negative": lambda: make_rules(max_package_discount_bps=-1),
    "empty-version": lambda: make_rules(version=" "),
    "bad-currency": lambda: make_rules(currency="cop"),
    "band-currency-differs-from-rules": lambda: make_rules(currency="USD"),
}


@pytest.mark.parametrize("build", INVALID.values(), ids=INVALID.keys())
def test_invalid_rules_are_rejected(build: Callable[[], PricingRules]) -> None:
    with pytest.raises(InvalidRules):
        build()


def test_single_open_band_and_single_tier_are_valid() -> None:
    rules = make_rules(guest_tiers=(GuestTier(1, 0),), distance_bands=(band(None, 0),))
    assert rules.distance_bands[0].up_to_km is None
