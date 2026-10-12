"""calculate_price: equipment lines, rental days, rounding and input validation."""

import dataclasses
import functools
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from eventssound.domain.catalog import (
    Catalog,
    EquipmentCategory,
    EquipmentItem,
    PackageLine,
    ServicePackage,
)
from eventssound.domain.errors import (
    CurrencyMismatch,
    DomainError,
    InvalidCatalog,
    InvalidEventRequest,
    InvalidRules,
    UnknownCatalogEntry,
)
from eventssound.domain.event_request import EventRequest, EventType, RequestedLine, VenueType
from eventssound.domain.money import Money
from eventssound.domain.pricing import LineKind, Quote, QuoteLine, calculate_price
from eventssound.domain.pricing_rules import (
    DistanceBand,
    GuestTier,
    NightWindow,
    PricingRules,
    default_pricing_rules,
)

BOGOTA = ZoneInfo("America/Bogota")


def local(day: int, hour: int = 0, minute: int = 0, month: int = 10, second: int = 0) -> datetime:
    """A Bogota wall-clock time in 2026. 2026-10-14 is a Wednesday, 2026-10-10 a Saturday."""
    return datetime(2026, month, day, hour, minute, second, tzinfo=BOGOTA)


def _item(code: str, price: int, stock: int = 10) -> EquipmentItem:
    return EquipmentItem(code, code, EquipmentCategory.SOUND, stock, Money(price))


def make_catalog() -> Catalog:
    return Catalog(
        items=(
            _item("speaker_active", 120_000),
            _item("mixer_16ch", 79_900),
            _item("truss_big", 1_000_000),
            _item("cable_xlr", 1_005),
        ),
        packages=(
            ServicePackage(
                "pkg_party",
                "Party",
                (PackageLine("speaker_active", 2), PackageLine("mixer_16ch", 1)),
                1000,
            ),
            ServicePackage("pkg_deluxe", "Deluxe", (PackageLine("truss_big", 1),), 1000),
            ServicePackage("pkg_capped", "Capped", (PackageLine("truss_big", 1),), 3000),
            ServicePackage("pkg_plain", "Plain", (PackageLine("mixer_16ch", 1),), 0),
        ),
    )


def make_request(**overrides: Any) -> EventRequest:
    """Wednesday 14:00-18:00 Bogota: a weekday, daytime event, one rental day."""
    values: dict[str, Any] = {
        "event_type": EventType.CORPORATE,
        "start": local(14, 14),
        "end": local(14, 18),
        "guest_count": 50,
        "distance_km": 0,
        "venue": VenueType.INDOOR,
        "items": (RequestedLine("speaker_active", 1),),
    }
    values.update(overrides)
    return EventRequest(**values)


def neutral_rules(**overrides: Any) -> PricingRules:
    """Every adjustment off and no rounding: the quote is just the equipment subtotal."""
    values: dict[str, Any] = {
        "guest_tiers": (GuestTier(1, 0),),
        "weekend_holiday_surcharge_bps": 0,
        "night": NightWindow(
            default_pricing_rules().night.start, default_pricing_rules().night.end, 0
        ),
        "distance_bands": (DistanceBand(None, Money(0)),),
        "rounding_step": 1,
    }
    values.update(overrides)
    return dataclasses.replace(default_pricing_rules(), **values)


def price(request: EventRequest | None = None, rules: PricingRules | None = None) -> Quote:
    return calculate_price(request or make_request(), make_catalog(), rules or neutral_rules())


def lines_of(quote: Quote, kind: LineKind) -> list[QuoteLine]:
    return [line for line in quote.lines if line.kind is kind]


# --- equipment lines -----------------------------------------------------------------------


def test_item_line_is_unit_price_times_quantity() -> None:
    quote = price(make_request(items=(RequestedLine("speaker_active", 3),)))
    (line,) = quote.lines
    assert (line.kind, line.code, line.label) == (LineKind.ITEM, "speaker_active", "speaker_active")
    assert (line.quantity, line.periods, line.unit_amount) == (3, 1, Money(120_000))
    assert line.amount == Money(360_000)
    assert quote.subtotal == quote.total == Money(360_000)
    assert quote.rules_version == "synthetic-v1"
    assert quote.currency == "COP"


def test_package_line_and_discount_net_to_the_discounted_amount() -> None:
    quote = price(make_request(items=(), packages=(RequestedLine("pkg_deluxe", 1),)))
    package, discount = quote.lines
    assert (package.kind, package.amount) == (LineKind.PACKAGE, Money(1_000_000))
    assert package.unit_amount == Money(1_000_000)
    assert (discount.kind, discount.code) == (LineKind.PACKAGE_DISCOUNT, "pkg_deluxe")
    assert (discount.rate_bps, discount.basis) == (1000, Money(1_000_000))
    assert discount.amount == Money(-100_000)
    assert quote.total == Money(900_000)


def test_package_unit_price_sums_members_and_scales_with_quantity() -> None:
    quote = price(make_request(items=(), packages=(RequestedLine("pkg_party", 2),)))
    package, discount = quote.lines
    assert package.unit_amount == Money(319_900)  # 2 x 120000 + 79900
    assert (package.quantity, package.amount) == (2, Money(639_800))
    assert discount.amount == Money(-63_980)


def test_discount_is_capped_by_the_rules() -> None:
    request = make_request(items=(), packages=(RequestedLine("pkg_capped", 1),))
    capped = price(request)  # package asks 30%, default cap is 20%
    assert lines_of(capped, LineKind.PACKAGE_DISCOUNT)[0].rate_bps == 2000
    assert capped.total == Money(800_000)
    raised = price(request, neutral_rules(max_package_discount_bps=5000))
    assert raised.total == Money(700_000)


def test_package_without_discount_emits_no_discount_line() -> None:
    quote = price(make_request(items=(), packages=(RequestedLine("pkg_plain", 1),)))
    assert [line.kind for line in quote.lines] == [LineKind.PACKAGE]


def test_zero_cap_removes_the_discount_line() -> None:
    request = make_request(items=(), packages=(RequestedLine("pkg_deluxe", 1),))
    quote = price(request, neutral_rules(max_package_discount_bps=0))
    assert [line.kind for line in quote.lines] == [LineKind.PACKAGE]


def test_lines_follow_the_order_of_application() -> None:
    request = make_request(
        items=(RequestedLine("mixer_16ch", 1), RequestedLine("speaker_active", 1)),
        packages=(RequestedLine("pkg_party", 1), RequestedLine("pkg_deluxe", 1)),
    )
    kinds = [(line.kind, line.code) for line in price(request).lines]
    assert kinds == [
        (LineKind.ITEM, "mixer_16ch"),
        (LineKind.ITEM, "speaker_active"),
        (LineKind.PACKAGE, "pkg_deluxe"),
        (LineKind.PACKAGE_DISCOUNT, "pkg_deluxe"),
        (LineKind.PACKAGE, "pkg_party"),
        (LineKind.PACKAGE_DISCOUNT, "pkg_party"),
    ]


def test_duplicate_codes_merge_and_input_order_is_irrelevant() -> None:
    split = make_request(
        items=(
            RequestedLine("speaker_active", 1),
            RequestedLine("mixer_16ch", 1),
            RequestedLine("speaker_active", 2),
        )
    )
    merged = make_request(
        items=(RequestedLine("mixer_16ch", 1), RequestedLine("speaker_active", 3))
    )
    assert price(split) == price(merged)
    assert [line.quantity for line in price(split).lines] == [1, 3]


# --- rental days ---------------------------------------------------------------------------

DAY = timedelta(hours=24)


@pytest.mark.parametrize(
    ("start", "end", "days"),
    [
        pytest.param(local(14, 22), local(15, 3), 1, id="overnight-22h-to-03h-is-one-day"),
        pytest.param(local(14, 14), local(14, 14, 1), 1, id="one-minute"),
        pytest.param(local(14, 14), local(14, 14) + DAY, 1, id="exactly-24h"),
        pytest.param(local(14, 14), local(14, 14, 1) + DAY, 2, id="24h-plus-one-minute"),
        pytest.param(local(14, 14), local(14, 14) + 2 * DAY, 2, id="exactly-48h"),
        pytest.param(local(1, 8), local(1, 8) + 31 * DAY, 31, id="max-31-days"),
        pytest.param(local(14, 20), local(15, 23), 2, id="calendar-days-touched-do-not-count"),
    ],
)
def test_rental_days_are_ceil_of_24_hour_blocks(start: datetime, end: datetime, days: int) -> None:
    quote = price(make_request(start=start, end=end))
    assert quote.rental_days == days
    (line,) = quote.lines
    assert (line.periods, line.amount) == (days, Money(120_000 * days))


def test_rental_days_use_absolute_time_not_wall_clock() -> None:
    # Same instants expressed in UTC give the same quote as in Bogota.
    start, end = local(14, 14), local(14, 14) + DAY + timedelta(hours=1)
    utc = ZoneInfo("UTC")
    assert price(make_request(start=start, end=end)) == price(
        make_request(start=start.astimezone(utc), end=end.astimezone(utc))
    )


# --- rounding ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unit_price", "total", "rounding"),
    [
        pytest.param(1_500, 2_000, 500, id="half-rounds-up"),
        pytest.param(1_499, 1_000, -499, id="below-half-rounds-down"),
        pytest.param(2_000, 2_000, None, id="already-on-the-step"),
        pytest.param(100, 0, -100, id="small-amount-rounds-to-zero"),
    ],
)
def test_total_is_rounded_once_with_an_explicit_signed_rounding_line(
    unit_price: int, total: int, rounding: int | None
) -> None:
    catalog = Catalog((_item("odd_item", unit_price),), ())
    request = make_request(items=(RequestedLine("odd_item", 1),))
    quote = calculate_price(request, catalog, neutral_rules(rounding_step=1000))
    assert quote.subtotal == Money(unit_price)
    assert quote.total == Money(total)
    rounding_lines = lines_of(quote, LineKind.ROUNDING)
    assert [line.amount.amount for line in rounding_lines] == (
        [] if rounding is None else [rounding]
    )
    assert sum(line.amount.amount for line in quote.lines) == total


def test_rounding_line_is_last_and_shaped_as_a_pure_adjustment() -> None:
    quote = price(
        make_request(items=(RequestedLine("cable_xlr", 1),)), neutral_rules(rounding_step=1000)
    )
    last = quote.lines[-1]
    assert last.kind is LineKind.ROUNDING and last.code == "rounding"
    assert (last.label, last.unit_amount, last.rate_bps, last.basis) == (None, None, None, None)
    assert (quote.subtotal, quote.total, last.amount) == (Money(1_005), Money(1_000), Money(-5))


def test_rounding_step_swap_needs_no_code_change() -> None:
    request = make_request(items=(RequestedLine("cable_xlr", 7),))  # 7035
    assert price(request, neutral_rules(rounding_step=1000)).total == Money(7_000)
    assert price(request, neutral_rules(rounding_step=100)).total == Money(7_000)
    assert price(request, neutral_rules(rounding_step=500)).total == Money(7_000)
    assert price(request, neutral_rules(rounding_step=50)).total == Money(7_050)
    assert price(request, neutral_rules(rounding_step=1)).total == Money(7_035)


# --- purity, determinism, errors -----------------------------------------------------------


def test_same_input_gives_equal_hashable_output_and_inputs_are_untouched() -> None:
    request = make_request(
        items=(RequestedLine("speaker_active", 1), RequestedLine("speaker_active", 2))
    )
    catalog, rules = make_catalog(), neutral_rules()
    first = calculate_price(request, catalog, rules)
    second = calculate_price(request, catalog, rules)
    assert first == second and hash(first) == hash(second)
    assert request.items == (RequestedLine("speaker_active", 1), RequestedLine("speaker_active", 2))
    assert catalog == make_catalog() and rules == neutral_rules()


@pytest.mark.parametrize(
    "request_kwargs",
    [
        pytest.param({"items": (RequestedLine("ghost_item", 1),)}, id="unknown-item"),
        pytest.param(
            {"items": (), "packages": (RequestedLine("pkg_ghost", 1),)}, id="unknown-package"
        ),
        pytest.param({"items": (RequestedLine("pkg_party", 1),)}, id="package-code-as-item"),
        pytest.param(
            {"items": (), "packages": (RequestedLine("mixer_16ch", 1),)}, id="item-code-as-package"
        ),
    ],
)
def test_unknown_codes_raise_a_domain_error_naming_the_code(request_kwargs: dict[str, Any]) -> None:
    request = make_request(**request_kwargs)
    code = (request.items + request.packages)[0].code
    with pytest.raises(UnknownCatalogEntry, match=code) as error:
        price(request)
    assert error.value.code == code


def test_catalog_and_rules_currencies_must_match() -> None:
    usd = Catalog(
        (EquipmentItem("speaker_active", "x", EquipmentCategory.SOUND, 1, Money(5, "USD")),), ()
    )
    with pytest.raises(CurrencyMismatch):
        calculate_price(make_request(), usd, neutral_rules())


def usd_catalog() -> Catalog:
    item = EquipmentItem("speaker_active", "x", EquipmentCategory.SOUND, 5, Money(100, "USD"))
    package = ServicePackage("pkg_usd", "Usd", (PackageLine("speaker_active", 2),), 1000)
    return Catalog((item,), (package,))


def test_package_in_a_non_default_currency_is_priced_in_that_currency() -> None:
    rules = neutral_rules(currency="USD", distance_bands=(DistanceBand(None, Money(0, "USD")),))
    request = make_request(items=(), packages=(RequestedLine("pkg_usd", 1),))
    quote = calculate_price(request, usd_catalog(), rules)
    assert quote.currency == "USD"
    assert [line.amount for line in quote.lines] == [Money(200, "USD"), Money(-20, "USD")]
    assert quote.total == Money(180, "USD")


def test_package_catalog_and_rules_currencies_must_match() -> None:
    request = make_request(items=(), packages=(RequestedLine("pkg_usd", 1),))
    with pytest.raises(CurrencyMismatch):
        calculate_price(request, usd_catalog(), neutral_rules())  # COP rules


@pytest.mark.parametrize(
    ("args", "error"),
    [
        pytest.param((None, make_catalog(), neutral_rules()), InvalidEventRequest, id="request"),
        pytest.param((make_request(), "catalog", neutral_rules()), InvalidCatalog, id="catalog"),
        pytest.param(
            (make_request(), make_catalog(), {"rounding_step": 1}), InvalidRules, id="rules"
        ),
    ],
)
def test_wrong_argument_types_raise_domain_errors(
    args: tuple[Any, ...], error: type[DomainError]
) -> None:
    with pytest.raises(error):
        calculate_price(*args)


# --- surcharges (default rules, truss_big: E = 1,000,000 per rental day) --------------------


def priced(
    start: datetime, end: datetime, rules: PricingRules | None = None, **overrides: Any
) -> Quote:
    values: dict[str, Any] = {"items": (RequestedLine("truss_big", 1),)}
    values.update(overrides)
    request = make_request(start=start, end=end, **values)
    return calculate_price(request, make_catalog(), rules or default_pricing_rules())


def flags(start: datetime, end: datetime, rules: PricingRules | None = None) -> tuple[int, int]:
    """How many WEEKEND_HOLIDAY and NIGHT lines the quote has (a surcharge is flat: 0 or 1)."""
    quote = priced(start, end, rules)
    return len(lines_of(quote, LineKind.WEEKEND_HOLIDAY)), len(lines_of(quote, LineKind.NIGHT))


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_worked_example_follows_the_design_order_and_rounds_once() -> None:
    request = make_request(
        start=local(10, 20),  # Saturday
        end=local(10, 23, 30),
        guest_count=150,
        distance_km=45,
        items=(RequestedLine("speaker_active", 2), RequestedLine("mixer_16ch", 1)),
    )
    quote = calculate_price(request, make_catalog(), default_pricing_rules())
    assert [(line.kind, line.code, line.amount.amount) for line in quote.lines] == [
        (LineKind.ITEM, "mixer_16ch", 79_900),
        (LineKind.ITEM, "speaker_active", 240_000),
        (LineKind.GUEST_SIZE, "guest_size", 31_990),
        (LineKind.WEEKEND_HOLIDAY, "weekend_holiday", 47_985),
        (LineKind.NIGHT, "night", 63_980),
        (LineKind.DISTANCE, "distance_band_2", 75_000),
        (LineKind.ROUNDING, "rounding", 145),
    ]
    assert (quote.subtotal, quote.total) == (Money(538_855), Money(539_000))
    percentage = {line.kind: (line.rate_bps, line.basis) for line in quote.lines if line.basis}
    assert percentage[LineKind.GUEST_SIZE] == (1000, Money(319_900))
    assert percentage[LineKind.WEEKEND_HOLIDAY] == (1500, Money(319_900))
    assert percentage[LineKind.NIGHT] == (2000, Money(319_900))


def test_percentages_are_additive_and_use_the_net_equipment_subtotal() -> None:
    quote = priced(local(10, 20), local(10, 23), guest_count=101)
    assert [line.amount.amount for line in quote.lines] == [
        1_000_000,
        100_000,
        150_000,
        200_000,
    ]  # not compounded: 1.1 * 1.15 * 1.2 would give 1,518,000
    net = priced(
        local(10, 20),
        local(10, 23),
        guest_count=101,
        items=(),
        packages=(RequestedLine("pkg_deluxe", 1),),
    )
    assert lines_of(net, LineKind.GUEST_SIZE)[0].basis == Money(900_000)


def test_percentage_lines_round_to_the_peso_and_only_the_total_to_the_step() -> None:
    request = make_request(guest_count=101, items=(RequestedLine("cable_xlr", 1),))
    quote = calculate_price(request, make_catalog(), default_pricing_rules())
    guest = lines_of(quote, LineKind.GUEST_SIZE)[0]
    assert guest.amount == Money(101)  # 100.5 pesos, half-up
    assert (quote.subtotal, quote.total) == (Money(1_106), Money(1_000))
    assert quote.lines[-1].amount == Money(-106)


@pytest.mark.parametrize(
    ("guests", "bps"),
    [
        pytest.param(1, None, id="1"),
        pytest.param(100, None, id="100"),
        pytest.param(101, 1000, id="101"),
        pytest.param(300, 1000, id="300"),
        pytest.param(301, 2500, id="301"),
        pytest.param(600, 2500, id="600"),
        pytest.param(601, 4000, id="601"),
        pytest.param(100_000, 4000, id="max"),
    ],
)
def test_guest_tier_boundaries(guests: int, bps: int | None) -> None:
    quote = priced(local(14, 14), local(14, 18), guest_count=guests)
    found = lines_of(quote, LineKind.GUEST_SIZE)
    assert [(line.rate_bps, line.amount.amount) for line in found] == (
        [] if bps is None else [(bps, 1_000_000 * bps // 10_000)]
    )


@pytest.mark.parametrize(
    ("km", "expected"),
    [
        pytest.param(0, [], id="0"),
        pytest.param(19, [], id="19"),
        pytest.param(20, [], id="20"),
        pytest.param(21, [("distance_band_2", 1, 3_000)], id="21"),
        pytest.param(60, [("distance_band_2", 40, 120_000)], id="60"),
        pytest.param(
            61, [("distance_band_2", 40, 120_000), ("distance_band_3", 1, 4_500)], id="61"
        ),
        pytest.param(
            100, [("distance_band_2", 40, 120_000), ("distance_band_3", 40, 180_000)], id="100"
        ),
    ],
)
def test_distance_is_charged_marginally_per_band(
    km: int, expected: list[tuple[str, int, int]]
) -> None:
    quote = priced(local(14, 14), local(14, 18), distance_km=km)
    found = lines_of(quote, LineKind.DISTANCE)
    assert [(line.code, line.quantity, line.amount.amount) for line in found] == expected
    assert all(line.periods == 1 for line in found)  # one delivery per event, not per day


def test_distance_is_not_multiplied_by_rental_days() -> None:
    quote = priced(local(14, 14), local(16, 14, 1), distance_km=21)  # 3 rental days
    assert quote.rental_days == 3
    assert lines_of(quote, LineKind.DISTANCE)[0].amount == Money(3_000)


@pytest.mark.parametrize(
    ("start", "end", "night"),
    [
        pytest.param(local(14, 14), local(14, 20), False, id="14-20"),
        pytest.param(local(14, 16), local(14, 22), False, id="16-22-ends-at-window-start"),
        pytest.param(local(14, 21, 59), local(14, 22), False, id="21:59-22:00"),
        pytest.param(local(14, 8), local(14, 12), False, id="morning"),
        pytest.param(local(14, 6), local(14, 10), False, id="06-10-starts-at-window-end"),
        pytest.param(local(14, 18), local(14, 23), True, id="18-23"),
        pytest.param(local(14, 22), local(14, 22, 1), True, id="22:00-22:01"),
        pytest.param(local(14, 5), local(14, 8), True, id="05-08"),
        pytest.param(local(14, 5, 59), local(14, 10), True, id="05:59-10"),
        pytest.param(local(14, 1), local(14, 2), True, id="01-02-previous-evening-window"),
        pytest.param(local(14, 0), local(14, 6), True, id="00-06"),
        pytest.param(local(14, 12), local(15, 12), True, id="24h-event"),
    ],
)
def test_night_surcharge_boundaries_are_half_open(
    start: datetime, end: datetime, night: bool
) -> None:
    assert flags(start, end)[1] == (1 if night else 0)


def test_night_surcharge_applies_once_even_when_several_windows_overlap() -> None:
    quote = priced(local(14, 20), local(16, 8))  # Wed 20:00 - Fri 08:00 crosses two windows
    assert quote.rental_days == 2
    (night,) = lines_of(quote, LineKind.NIGHT)
    assert night.amount == Money(400_000)  # 20% of E = 2 days x 1,000,000, not per window


@pytest.mark.parametrize(
    ("start", "end", "weekend"),
    [
        pytest.param(local(14, 14), local(14, 18), False, id="wednesday"),
        pytest.param(local(10, 14), local(10, 18), True, id="saturday"),
        pytest.param(local(11, 14), local(11, 18), True, id="sunday"),
        pytest.param(local(12, 14), local(12, 18), False, id="monday"),
        pytest.param(local(9, 23), local(10, 2), True, id="friday-23-to-saturday-02"),
        pytest.param(local(9, 20), local(10, 0), False, id="ends-exactly-at-saturday-midnight"),
        pytest.param(
            local(9, 20), local(10, 0, 0, second=1), True, id="ends-one-second-into-saturday"
        ),
        pytest.param(local(11, 20), local(12, 0), True, id="sunday-to-monday-midnight"),
        pytest.param(local(11, 23), local(12, 2), True, id="sunday-23-to-monday-02"),
        pytest.param(local(12, 0), local(12, 4), False, id="starts-monday-midnight"),
        pytest.param(local(9, 20), local(12, 8), True, id="friday-to-monday"),
        pytest.param(
            utc(2026, 10, 10, 3), utc(2026, 10, 10, 4), False, id="utc-saturday-is-local-friday"
        ),
        pytest.param(
            utc(2026, 10, 11, 3), utc(2026, 10, 11, 4), True, id="utc-sunday-is-local-saturday"
        ),
        pytest.param(
            utc(2026, 10, 12, 3), utc(2026, 10, 12, 4), True, id="utc-monday-is-local-sunday"
        ),
        pytest.param(
            utc(2026, 10, 10, 4, 59), utc(2026, 10, 10, 5), False, id="local-friday-23:59"
        ),
        pytest.param(utc(2026, 10, 10, 5), utc(2026, 10, 10, 6), True, id="local-saturday-00:00"),
    ],
)
def test_weekend_is_classified_in_the_pricing_timezone(
    start: datetime, end: datetime, weekend: bool
) -> None:
    assert flags(start, end)[0] == (1 if weekend else 0)


def test_friday_to_monday_event_pays_the_weekend_surcharge_once() -> None:
    quote = priced(local(9, 20), local(12, 8))
    assert quote.rental_days == 3
    (weekend,) = lines_of(quote, LineKind.WEEKEND_HOLIDAY)
    assert weekend.amount == Money(450_000)  # 15% of 3 days x 1,000,000


def test_holidays_and_custom_weekend_days_are_rule_data() -> None:
    monday = (local(12, 14), local(12, 18))
    assert flags(*monday)[0] == 0
    assert flags(*monday, make_holiday_rules(date(2026, 10, 12)))[0] == 1
    friday_rules = dataclasses.replace(default_pricing_rules(), weekend_days=frozenset({4}))
    assert flags(local(9, 14), local(9, 18), friday_rules)[0] == 1
    assert flags(local(10, 14), local(10, 18), friday_rules)[0] == 0


def make_holiday_rules(*days: date) -> PricingRules:
    return dataclasses.replace(default_pricing_rules(), holidays=frozenset(days))


def test_classification_uses_the_rules_timezone_not_the_request_offset() -> None:
    tokyo = dataclasses.replace(default_pricing_rules(), timezone=timezone(timedelta(hours=9)))
    start, end = utc(2026, 10, 9, 16), utc(2026, 10, 9, 17)  # Saturday 01:00 in Tokyo
    assert flags(start, end) == (0, 0)  # Friday 11:00 in Bogota
    assert flags(start, end, tokyo) == (1, 1)
    assert priced(start, end, tokyo) == priced(
        start.astimezone(BOGOTA), end.astimezone(BOGOTA), tokyo
    )


def test_non_wrapping_night_window_is_supported() -> None:
    siesta = dataclasses.replace(
        default_pricing_rules(), night=NightWindow(time(13, 0), time(15, 0), 2000)
    )
    assert flags(local(14, 12), local(14, 13), siesta)[1] == 0
    assert flags(local(14, 12), local(14, 14), siesta)[1] == 1
    assert flags(local(14, 15), local(14, 18), siesta)[1] == 0
    assert flags(local(14, 22), local(15, 3), siesta)[1] == 0


# --- invariants over a fixed grid (hand-written, no Hypothesis) ----------------------------

EVENTS = {
    "weekday-day": (local(14, 14), local(14, 18)),
    "overnight-weekday": (local(14, 22), local(15, 3)),
    "saturday-night": (local(10, 20), local(11, 1)),
    "friday-to-monday": (local(9, 20), local(12, 8)),
}
QUANTITIES = (1, 2, 5, 40)
DISTANCES = (0, 19, 20, 21, 60, 61, 200)
GUESTS = (1, 100, 101, 300, 301, 601, 5_000)
STEPS = (1, 500, 1_000)
GridKey = tuple[str, int, int, int, int]


def grid_request(event: str, quantity: int, km: int, guests: int) -> EventRequest:
    start, end = EVENTS[event]
    return make_request(
        start=start,
        end=end,
        guest_count=guests,
        distance_km=km,
        items=(RequestedLine("speaker_active", quantity), RequestedLine("cable_xlr", 3)),
        packages=(RequestedLine("pkg_party", 1),),
    )


@functools.cache
def grid() -> dict[GridKey, Quote]:
    catalog = make_catalog()
    return {
        (event, quantity, km, guests, step): calculate_price(
            grid_request(event, quantity, km, guests),
            catalog,
            dataclasses.replace(default_pricing_rules(), rounding_step=step),
        )
        for event in EVENTS
        for quantity in QUANTITIES
        for km in DISTANCES
        for guests in GUESTS
        for step in STEPS
    }


def test_grid_is_not_vacuous() -> None:
    quotes = grid()
    assert len(quotes) == len(EVENTS) * len(QUANTITIES) * len(DISTANCES) * len(GUESTS) * len(STEPS)
    assert {k for q in quotes.values() for k in (x.kind for x in q.lines)} == set(LineKind)


def assert_line_is_reproducible(line: QuoteLine) -> None:
    match line.kind:
        case LineKind.ITEM | LineKind.PACKAGE:
            assert line.unit_amount is not None
            assert line.amount == line.unit_amount * (line.quantity * line.periods)
        case LineKind.DISTANCE:
            assert line.unit_amount is not None
            assert line.amount == line.unit_amount * line.quantity
        case LineKind.ROUNDING:
            assert line.amount.amount != 0
        case _:
            assert line.basis is not None and line.rate_bps is not None
            expected = line.basis.percent(line.rate_bps)
            assert line.amount == (
                -expected if line.kind is LineKind.PACKAGE_DISCOUNT else expected
            )


def test_totals_are_non_negative_rounded_integers_that_reconcile() -> None:
    for (_, _, _, _, step), quote in grid().items():
        assert quote.total.amount >= 0
        assert quote.total.amount % step == 0
        assert sum(line.amount.amount for line in quote.lines) == quote.total.amount
        assert -step < 2 * (quote.total.amount - quote.subtotal.amount) <= step  # half-up
        assert type(quote.total.amount) is int and type(quote.subtotal.amount) is int
        assert all(type(line.amount.amount) is int for line in quote.lines)
        assert len([x for x in quote.lines if x.kind is LineKind.ROUNDING]) <= 1


def test_every_line_is_reproducible_from_its_own_fields() -> None:
    for quote in grid().values():
        for line in quote.lines:
            assert_line_is_reproducible(line)


def test_rounding_is_idempotent() -> None:
    for (_, _, _, _, step), quote in grid().items():
        assert quote.total.round_to(step) == quote.total


@pytest.mark.parametrize(
    "axis",
    [
        pytest.param((1, QUANTITIES), id="quantity"),
        pytest.param((2, DISTANCES), id="distance"),
        pytest.param((3, GUESTS), id="guests"),
    ],
)
def test_total_never_decreases_when_quantity_distance_or_guests_grow(
    axis: tuple[int, tuple[int, ...]],
) -> None:
    position, values = axis
    quotes = grid()
    checked = 0
    for key in quotes:
        if key[position] != values[0]:
            continue
        totals = [quotes[(*key[:position], value, *key[position + 1 :])].total for value in values]
        assert totals == sorted(totals), key
        checked += 1
    assert checked > 0


def test_to_dict_never_contains_floats() -> None:
    def walk(value: object) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        else:
            assert type(value) in (int, str, type(None))

    for quote in grid().values():
        walk(quote.to_dict())
