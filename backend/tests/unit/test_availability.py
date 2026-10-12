"""Availability: half-open intervals, buffer, peak concurrency, packages and validation."""

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from eventssound.domain.availability import (
    Availability,
    AvailabilityReport,
    AvailabilityRules,
    Booking,
    BookingStatus,
    available_units,
    check_availability,
    check_request_availability,
    default_availability_rules,
    required_units,
)
from eventssound.domain.catalog import (
    Catalog,
    EquipmentCategory,
    EquipmentItem,
    PackageLine,
    ServicePackage,
)
from eventssound.domain.errors import (
    DomainError,
    InvalidAvailability,
    InvalidRules,
    UnknownCatalogEntry,
)
from eventssound.domain.event_request import EventRequest, EventType, RequestedLine, VenueType
from eventssound.domain.money import Money

BOGOTA = timezone(timedelta(hours=-5))
TWO_HOURS = default_availability_rules()
NO_BUFFER = AvailabilityRules(buffer=timedelta(0))


def at(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """A UTC instant in November 2026 (the 6th is a Friday)."""
    return datetime(2026, 11, day, hour, minute, second, tzinfo=UTC)


def make_item(code: str = "sound_speaker", stock: int = 1) -> EquipmentItem:
    return EquipmentItem(code, "Item", EquipmentCategory.SOUND, stock, Money(1000))


def book(
    start: datetime,
    end: datetime,
    quantity: int = 1,
    item_code: str = "sound_speaker",
    status: BookingStatus = BookingStatus.CONFIRMED,
    code: str = "bk_1",
) -> Booking:
    return Booking(code, item_code, quantity, start, end, status)


# --- rules and value objects ------------------------------------------------------------------


def test_default_rules_use_a_two_hour_buffer_as_data() -> None:
    assert TWO_HOURS.buffer == timedelta(hours=2)
    assert AvailabilityRules(buffer=timedelta(minutes=90)).buffer == timedelta(minutes=90)


def test_blocking_statuses_exclude_cancelled() -> None:
    assert BookingStatus.blocking() == frozenset({BookingStatus.PENDING, BookingStatus.CONFIRMED})


INVALID_RULES: dict[str, Any] = {
    "negative": timedelta(minutes=-1),
    "seconds": timedelta(minutes=90, seconds=1),
    "microseconds": timedelta(minutes=1, microseconds=1),
    "over-a-week": timedelta(days=7, minutes=1),
    "int": 120,
    "float": 7200.0,
    "none": None,
    "string": "2h",
}


@pytest.mark.parametrize("buffer", INVALID_RULES.values(), ids=INVALID_RULES.keys())
def test_invalid_buffer_is_rejected(buffer: Any) -> None:
    with pytest.raises(InvalidRules):
        AvailabilityRules(buffer=buffer)


def test_value_objects_are_frozen_and_hashable() -> None:
    booking = book(at(6, 10), at(6, 14))
    availability = check_availability(make_item(), at(6, 16), at(6, 20), (booking,), TWO_HOURS)
    report = AvailabilityReport(items=[availability])  # type: ignore[arg-type]
    assert report.items == (availability,)
    assert len({booking, book(at(6, 10), at(6, 14)), TWO_HOURS, availability, report}) == 4
    with pytest.raises(dataclasses.FrozenInstanceError):
        booking.quantity = 5  # type: ignore[misc]


INVALID_BOOKINGS: dict[str, Callable[[], Booking]] = {
    "naive-start": lambda: book(datetime(2026, 11, 6, 10), at(6, 14)),
    "naive-end": lambda: book(at(6, 10), datetime(2026, 11, 6, 14)),
    "non-datetime": lambda: book("2026-11-06", at(6, 14)),  # type: ignore[arg-type]
    "end-equals-start": lambda: book(at(6, 10), at(6, 10)),
    "end-before-start": lambda: book(at(6, 10), at(6, 9)),
    "zero-quantity": lambda: book(at(6, 10), at(6, 14), quantity=0),
    "negative-quantity": lambda: book(at(6, 10), at(6, 14), quantity=-1),
    "bool-quantity": lambda: book(at(6, 10), at(6, 14), quantity=True),
    "float-quantity": lambda: book(at(6, 10), at(6, 14), quantity=1.0),  # type: ignore[arg-type]
    "bad-item-code": lambda: book(at(6, 10), at(6, 14), item_code="Bad Code"),
    "trailing-newline-item-code": lambda: book(at(6, 10), at(6, 14), item_code="abc\n"),
    "non-string-item-code": lambda: book(at(6, 10), at(6, 14), item_code=None),  # type: ignore[arg-type]
    "empty-code": lambda: book(at(6, 10), at(6, 14), code=""),
    "trailing-newline-code": lambda: book(at(6, 10), at(6, 14), code="bk_1\n"),
    "plain-string-status": lambda: book(at(6, 10), at(6, 14), status="confirmed"),  # type: ignore[arg-type]
    "offset-overflow": lambda: book(
        datetime.min.replace(tzinfo=timezone(timedelta(hours=5))), at(6, 14)
    ),
}


@pytest.mark.parametrize("build", INVALID_BOOKINGS.values(), ids=INVALID_BOOKINGS.keys())
def test_invalid_booking_raises_a_domain_error(build: Callable[[], Booking]) -> None:
    with pytest.raises(InvalidAvailability):
        build()


# --- single item: buffer edges, overlap shapes, multi-day, offsets ----------------------------

BOOKED = (at(6, 10), at(6, 14))  # [10:00, 14:00)
FRIDAY_NIGHT = (at(6, 18), at(8, 2))  # Friday 18:00 to Sunday 02:00

BOUNDARY_CASES = [
    # (booking, buffer, request start, request end, expected available)
    pytest.param(BOOKED, NO_BUFFER, at(6, 14), at(6, 18), True, id="zero-buffer-back-to-back"),
    pytest.param(BOOKED, NO_BUFFER, at(6, 6), at(6, 10), True, id="zero-buffer-just-before"),
    pytest.param(
        BOOKED, NO_BUFFER, at(6, 13, 59, 59), at(6, 18), False, id="zero-buffer-overlap-1s-after"
    ),
    pytest.param(
        BOOKED, NO_BUFFER, at(6, 6), at(6, 10, 0, 1), False, id="zero-buffer-overlap-1s-before"
    ),
    pytest.param(BOOKED, TWO_HOURS, at(6, 14), at(6, 18), False, id="default-back-to-back"),
    pytest.param(BOOKED, TWO_HOURS, at(6, 16), at(6, 20), True, id="exactly-buffer-after"),
    pytest.param(BOOKED, TWO_HOURS, at(6, 15, 59), at(6, 20), False, id="one-minute-inside"),
    pytest.param(
        BOOKED, TWO_HOURS, at(6, 15, 59, 59), at(6, 20), False, id="one-second-inside-after"
    ),
    pytest.param(BOOKED, TWO_HOURS, at(6, 4), at(6, 8), True, id="exactly-buffer-before"),
    pytest.param(BOOKED, TWO_HOURS, at(6, 4), at(6, 8, 0, 1), False, id="one-second-inside-before"),
    pytest.param(BOOKED, TWO_HOURS, at(6, 11), at(6, 12), False, id="request-contained"),
    pytest.param(BOOKED, TWO_HOURS, at(6, 8), at(6, 18), False, id="request-containing"),
    pytest.param(BOOKED, TWO_HOURS, at(6, 10), at(6, 14), False, id="identical-to-booking"),
    pytest.param(BOOKED, TWO_HOURS, at(6, 12), at(6, 16), False, id="partial-overlap-end"),
    pytest.param((at(6, 8), at(6, 12)), TWO_HOURS, at(6, 14), at(6, 22), True, id="turnaround-ok"),
    pytest.param(
        (at(6, 8), at(6, 12)), TWO_HOURS, at(6, 13), at(6, 22), False, id="turnaround-too-tight"
    ),
    pytest.param(FRIDAY_NIGHT, TWO_HOURS, at(7, 10), at(7, 14), False, id="multi-day-overlap"),
    pytest.param(FRIDAY_NIGHT, TWO_HOURS, at(8, 4), at(8, 8), True, id="multi-day-exact-buffer"),
    pytest.param(
        FRIDAY_NIGHT, TWO_HOURS, at(8, 3, 59, 59), at(8, 8), False, id="multi-day-1s-inside"
    ),
    pytest.param(FRIDAY_NIGHT, TWO_HOURS, at(5, 8), at(6, 16), True, id="multi-day-exact-before"),
    pytest.param(
        FRIDAY_NIGHT, TWO_HOURS, at(5, 8), at(6, 16, 0, 1), False, id="multi-day-1s-inside-before"
    ),
    pytest.param(
        BOOKED,
        AvailabilityRules(buffer=timedelta(minutes=1)),
        at(6, 14, 1),
        at(6, 18),
        True,
        id="one-minute-buffer-edge",
    ),
    pytest.param(
        BOOKED,
        AvailabilityRules(buffer=timedelta(minutes=1)),
        at(6, 14, 0, 59),
        at(6, 18),
        False,
        id="one-minute-buffer-inside",
    ),
    pytest.param((at(6, 10), at(6, 14)), NO_BUFFER, at(6, 10), at(6, 14), False, id="zero-same"),
]


@pytest.mark.parametrize(("window", "rules", "start", "end", "expected"), BOUNDARY_CASES)
def test_single_unit_boundaries(
    window: tuple[datetime, datetime],
    rules: AvailabilityRules,
    start: datetime,
    end: datetime,
    expected: bool,
) -> None:
    assert BOUNDARY_CASES  # guard against a vacuous parametrization
    result = check_availability(make_item(stock=1), start, end, (book(*window),), rules)
    assert result.is_available is expected
    assert result.remaining == (1 if expected else 0)


def test_equivalent_instants_in_different_offsets_are_the_same_interval() -> None:
    booking = book(at(6, 15), at(6, 19))  # 15:00-19:00 UTC
    local_start = datetime(2026, 11, 6, 10, tzinfo=BOGOTA)  # 15:00 UTC
    local_end = datetime(2026, 11, 6, 14, tzinfo=BOGOTA)  # 19:00 UTC
    same = check_availability(make_item(), local_start, local_end, (booking,), NO_BUFFER)
    assert not same.is_available
    after = check_availability(
        make_item(), local_end, local_end + timedelta(hours=4), (booking,), NO_BUFFER
    )
    assert after.is_available


def test_booking_in_another_offset_is_compared_by_instant() -> None:
    booking = book(
        datetime(2026, 11, 6, 10, tzinfo=BOGOTA), datetime(2026, 11, 6, 14, tzinfo=BOGOTA)
    )  # 15:00-19:00 UTC
    assert not check_availability(
        make_item(), at(6, 18), at(6, 20), (booking,), NO_BUFFER
    ).is_available
    assert check_availability(make_item(), at(6, 19), at(6, 20), (booking,), NO_BUFFER).is_available


# --- stock and peak concurrency ---------------------------------------------------------------


def test_free_calendar_has_all_stock_remaining() -> None:
    result = check_availability(make_item(stock=4), at(6, 10), at(6, 14), (), TWO_HOURS, 4)
    assert result == Availability("sound_speaker", requested=4, stock=4, remaining=4)
    assert result.is_available
    assert result.shortfall == 0


def test_partial_consumption_reports_the_shortfall() -> None:
    bookings = (book(at(6, 10), at(6, 14), quantity=3),)
    result = check_availability(make_item(stock=4), at(6, 12), at(6, 16), bookings, TWO_HOURS, 2)
    assert (result.remaining, result.requested, result.shortfall) == (1, 2, 1)
    assert not result.is_available


def test_pending_and_confirmed_consume_cancelled_does_not() -> None:
    window = (at(6, 10), at(6, 14))
    for status, remaining in (
        (BookingStatus.PENDING, 0),
        (BookingStatus.CONFIRMED, 0),
        (BookingStatus.CANCELLED, 1),
    ):
        booking = book(*window, status=status)
        assert available_units(make_item(), *window, (booking,), TWO_HOURS) == remaining


def test_other_items_are_ignored() -> None:
    bookings = (book(at(6, 10), at(6, 14), quantity=5, item_code="light_par"),)
    assert available_units(make_item(stock=2), at(6, 10), at(6, 14), bookings, TWO_HOURS) == 2


def test_far_away_bookings_do_not_consume_stock() -> None:
    bookings = (book(at(20, 10), at(20, 14), quantity=2), book(at(1, 10), at(1, 14), quantity=2))
    assert available_units(make_item(stock=2), at(6, 10), at(6, 14), bookings, TWO_HOURS) == 2


def test_zero_stock_is_never_available() -> None:
    result = check_availability(make_item(stock=0), at(6, 10), at(6, 14), (), TWO_HOURS)
    assert (result.remaining, result.is_available) == (0, False)


def test_requested_quantity_above_stock_is_unavailable_with_full_remaining() -> None:
    result = check_availability(make_item(stock=2), at(6, 10), at(6, 14), (), TWO_HOURS, 3)
    assert (result.remaining, result.shortfall, result.is_available) == (2, 1, False)


def test_remaining_never_goes_negative_when_existing_data_overbooks() -> None:
    bookings = (book(at(6, 10), at(6, 14), 3), book(at(6, 10), at(6, 14), 3, code="bk_2"))
    assert available_units(make_item(stock=4), at(6, 10), at(6, 14), bookings, TWO_HOURS) == 0


def in_both_orders(bookings: tuple[Booking, ...]) -> list[tuple[Booking, ...]]:
    """The same bookings as given and reversed: the sweep must not rely on input order."""
    return [bookings, bookings[::-1]]


def test_sequential_bookings_inside_one_request_count_as_peak_not_sum() -> None:
    bookings = (
        book(at(6, 8), at(6, 10), code="bk_1"),
        book(at(6, 10), at(6, 12), code="bk_2"),
        book(at(6, 12), at(6, 14), code="bk_3"),
    )
    for ordered in in_both_orders(bookings):
        assert available_units(make_item(stock=2), at(6, 8), at(6, 14), ordered, NO_BUFFER) == 1


def test_bookings_that_individually_fit_but_together_exceed_stock() -> None:
    # Stock 3: each booking of 2 fits alone, but [12:00, 14:00) holds 4 units at once.
    bookings = (
        book(at(6, 10), at(6, 14), quantity=2, code="bk_1"),
        book(at(6, 12), at(6, 16), quantity=2, code="bk_2"),
    )
    item = make_item(stock=3)
    for single in bookings:
        assert available_units(item, at(6, 11), at(6, 13), (single,), NO_BUFFER) == 1
    assert available_units(item, at(6, 11), at(6, 13), bookings, NO_BUFFER) == 0


def test_peak_counts_only_what_is_concurrent() -> None:
    # A(2)+B(2) overlap and C(3) overlaps only B: the peak is B+C = 5, not A+B+C = 7.
    bookings = (
        book(at(6, 8), at(6, 12), quantity=2, code="bk_a"),
        book(at(6, 10), at(6, 14), quantity=2, code="bk_b"),
        book(at(6, 13), at(6, 16), quantity=3, code="bk_c"),
    )
    for ordered in in_both_orders(bookings):
        assert available_units(make_item(stock=9), at(6, 8), at(6, 16), ordered, NO_BUFFER) == 4
    # A releases at 12:00, before C acquires at 13:00, so A+C are never concurrent.
    for ordered in in_both_orders(bookings[::2]):
        assert available_units(make_item(stock=9), at(6, 8), at(6, 16), ordered, NO_BUFFER) == 6


def test_release_precedes_acquisition_at_the_same_instant_in_any_input_order() -> None:
    # A ends exactly when B starts. Listing B first must not make them look concurrent.
    bookings = (
        book(at(6, 8), at(6, 12), 1, code="bk_a"),
        book(at(6, 12), at(6, 16), 1, code="bk_b"),
    )
    for ordered in in_both_orders(bookings):
        assert available_units(make_item(stock=2), at(6, 8), at(6, 16), ordered, NO_BUFFER) == 1


def test_long_booking_over_two_short_ones_peaks_with_the_buffer() -> None:
    # L spans the day; S1 and S2 are 1h apart. Without a buffer S1 and S2 never overlap (peak 2);
    # with a 2h buffer they cannot share a unit, so all three are concurrent (peak 3).
    bookings = (
        book(at(6, 8), at(6, 20), code="bk_l"),
        book(at(6, 10), at(6, 11), code="bk_s1"),
        book(at(6, 12), at(6, 13), code="bk_s2"),
    )
    for ordered in in_both_orders(bookings):
        assert available_units(make_item(stock=4), at(6, 9), at(6, 14), ordered, NO_BUFFER) == 2
        assert available_units(make_item(stock=4), at(6, 9), at(6, 14), ordered, TWO_HOURS) == 1


def test_duplicate_booking_rows_each_count() -> None:
    # (code, item_code) is expected to be unique per booking; a duplicate errs toward unavailable.
    row = book(at(6, 10), at(6, 14))
    assert available_units(make_item(stock=2), at(6, 10), at(6, 14), (row, row), TWO_HOURS) == 0


def test_far_future_booking_does_not_poison_unrelated_windows() -> None:
    far = book(at(6, 10), datetime.max.replace(tzinfo=UTC), code="bk_far")
    unrelated = (at(6, 10), at(6, 14))
    # far overlaps [10:00, 14:00) on 6 Nov, so this window is rejected (fail closed)...
    with pytest.raises(InvalidAvailability):
        available_units(make_item(stock=2), *unrelated, (far,), TWO_HOURS)
    # ...but a window that ends before the booking starts is answered normally.
    assert available_units(make_item(stock=2), at(1, 10), at(1, 14), (far,), TWO_HOURS) == 2
    near_max = book(
        datetime.max.replace(tzinfo=UTC) - timedelta(hours=1), datetime.max.replace(tzinfo=UTC)
    )
    assert available_units(make_item(stock=2), *unrelated, (near_max,), TWO_HOURS) == 2


def test_buffer_of_exactly_seven_days_is_valid_and_applied() -> None:
    rules = AvailabilityRules(buffer=timedelta(days=7))
    booking = book(at(6, 10), at(6, 14))
    # Gap of exactly 7 days is allowed, one second less is not.
    assert available_units(make_item(), at(13, 14), at(13, 18), (booking,), rules) == 1
    assert available_units(make_item(), at(13, 13, 59, 59), at(13, 18), (booking,), rules) == 0


def test_buffer_makes_near_bookings_concurrent() -> None:
    # 1h apart with a 2h buffer: they cannot share a unit, so two units are needed.
    bookings = (
        book(at(6, 8), at(6, 10), code="bk_a"),
        book(at(6, 11), at(6, 13), code="bk_b"),
    )
    assert available_units(make_item(stock=2), at(6, 9), at(6, 12), bookings, TWO_HOURS) == 0
    assert available_units(make_item(stock=2), at(6, 9), at(6, 12), bookings, NO_BUFFER) == 1


def test_accepts_any_iterable_of_bookings() -> None:
    bookings = [book(at(6, 10), at(6, 14))]
    assert available_units(make_item(), at(6, 10), at(6, 14), iter(bookings), TWO_HOURS) == 0


def _invalid_query(**overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "item": make_item(),
        "start": at(6, 10),
        "end": at(6, 14),
        "bookings": (),
        "rules": TWO_HOURS,
        "quantity": 1,
    }
    kwargs.update(overrides)
    return check_availability(**kwargs)


INVALID_QUERIES: dict[str, dict[str, Any]] = {
    "naive-start": {"start": datetime(2026, 11, 6, 10)},
    "naive-end": {"end": datetime(2026, 11, 6, 14)},
    "non-datetime-start": {"start": "2026-11-06"},
    "end-equals-start": {"end": at(6, 10)},
    "end-before-start": {"end": at(6, 9)},
    "zero-quantity": {"quantity": 0},
    "negative-quantity": {"quantity": -1},
    "bool-quantity": {"quantity": True},
    "float-quantity": {"quantity": 1.0},
    "none-quantity": {"quantity": None},
    "item-not-an-item": {"item": "sound_speaker"},
    "string-bookings": {"bookings": "abc"},
    "bytes-bookings": {"bookings": b"abc"},
    "non-iterable-bookings": {"bookings": 5},
    "booking-element-not-a-booking": {"bookings": (book(at(6, 10), at(6, 14)), "x")},
    "rules-not-rules": {"rules": timedelta(hours=2)},
    "rules-none": {"rules": None},
    "request-end-overflows": {"end": datetime.max.replace(tzinfo=UTC)},
    "request-start-overflows": {"start": datetime.min.replace(tzinfo=UTC), "end": at(6, 14)},
    "request-offset-overflows": {
        "start": datetime.min.replace(tzinfo=timezone(timedelta(hours=5)))
    },
    "booking-end-overflows": {"bookings": (book(at(6, 10), datetime.max.replace(tzinfo=UTC)),)},
}


@pytest.mark.parametrize("overrides", INVALID_QUERIES.values(), ids=INVALID_QUERIES.keys())
def test_invalid_query_raises_a_domain_error(overrides: dict[str, Any]) -> None:
    with pytest.raises(InvalidAvailability) as caught:
        _invalid_query(**overrides)
    assert isinstance(caught.value, DomainError)


def test_valid_query_baseline_is_accepted() -> None:
    assert _invalid_query().is_available


# --- requests and packages --------------------------------------------------------------------


def make_catalog() -> Catalog:
    items = (
        make_item("sound_speaker", 3),
        make_item("sound_mixer", 2),
        make_item("light_par", 10),
    )
    packages = (
        ServicePackage(
            "pkg_basic", "Basic", (PackageLine("sound_speaker", 2), PackageLine("sound_mixer", 1))
        ),
    )
    return Catalog(items, packages)


EVENT_START = at(6, 18)
EVENT_END = at(7, 2)


def make_request(
    items: tuple[RequestedLine, ...] = (),
    packages: tuple[RequestedLine, ...] = (),
    start: datetime = EVENT_START,
    end: datetime = EVENT_END,
) -> EventRequest:
    return EventRequest(
        EventType.WEDDING, start, end, 100, 10, VenueType.INDOOR, items=items, packages=packages
    )


def test_required_units_aggregates_items_and_package_members() -> None:
    request = make_request(
        items=(RequestedLine("sound_speaker", 2), RequestedLine("light_par", 4)),
        packages=(RequestedLine("pkg_basic", 2),),
    )
    assert required_units(request, make_catalog()) == {
        "light_par": 4,
        "sound_mixer": 2,
        "sound_speaker": 6,
    }
    assert list(required_units(request, make_catalog())) == [
        "light_par",
        "sound_mixer",
        "sound_speaker",
    ]


def test_required_units_merges_duplicate_lines() -> None:
    request = make_request(
        items=(RequestedLine("light_par", 1), RequestedLine("light_par", 2)),
    )
    assert required_units(request, make_catalog()) == {"light_par": 3}


UNKNOWN_CODE_REQUESTS: dict[str, EventRequest] = {
    "unknown-item": make_request(items=(RequestedLine("sound_unknown", 1),)),
    "unknown-package": make_request(packages=(RequestedLine("pkg_unknown", 1),)),
    "package-code-used-as-item": make_request(items=(RequestedLine("pkg_basic", 1),)),
    "item-code-used-as-package": make_request(packages=(RequestedLine("sound_speaker", 1),)),
}


@pytest.mark.parametrize(
    "request_", UNKNOWN_CODE_REQUESTS.values(), ids=UNKNOWN_CODE_REQUESTS.keys()
)
def test_unknown_codes_raise_a_domain_error(request_: EventRequest) -> None:
    with pytest.raises(UnknownCatalogEntry):
        required_units(request_, make_catalog())
    with pytest.raises(UnknownCatalogEntry):
        check_request_availability(request_, make_catalog(), (), TWO_HOURS)


def test_request_and_catalog_types_are_checked() -> None:
    request = make_request(items=(RequestedLine("light_par", 1),))
    with pytest.raises(InvalidAvailability):
        required_units("request", make_catalog())  # type: ignore[arg-type]
    with pytest.raises(InvalidAvailability):
        required_units(request, "catalog")  # type: ignore[arg-type]
    with pytest.raises(InvalidAvailability):
        check_request_availability(request, make_catalog(), (), None)  # type: ignore[arg-type]
    with pytest.raises(InvalidAvailability):
        check_request_availability(request, make_catalog(), "bookings", TWO_HOURS)  # type: ignore[arg-type]


def test_package_with_all_members_available() -> None:
    request = make_request(packages=(RequestedLine("pkg_basic", 1),))
    report = check_request_availability(request, make_catalog(), (), TWO_HOURS)
    assert report.is_available
    assert report.shortages == ()
    assert [(a.item_code, a.requested, a.remaining) for a in report.items] == [
        ("sound_mixer", 1, 2),
        ("sound_speaker", 2, 3),
    ]


def test_package_with_one_member_short_names_the_limiting_item() -> None:
    bookings = (book(at(6, 20), at(7, 1), quantity=2),)  # 2 of 3 speakers are out
    request = make_request(packages=(RequestedLine("pkg_basic", 1),))
    report = check_request_availability(request, make_catalog(), bookings, TWO_HOURS)
    assert not report.is_available
    assert [(s.item_code, s.requested, s.remaining, s.shortfall) for s in report.shortages] == [
        ("sound_speaker", 2, 1, 1)
    ]
    assert [a.item_code for a in report.items] == ["sound_mixer", "sound_speaker"]


def test_shared_member_quantities_are_aggregated_before_checking() -> None:
    # The package needs 2 speakers and 2 more are requested: 4 needed, 3 in stock.
    request = make_request(
        items=(RequestedLine("sound_speaker", 2),), packages=(RequestedLine("pkg_basic", 1),)
    )
    report = check_request_availability(request, make_catalog(), (), TWO_HOURS)
    assert not report.is_available
    assert [(s.item_code, s.requested, s.remaining) for s in report.shortages] == [
        ("sound_speaker", 4, 3)
    ]


def test_each_requested_item_exactly_at_stock_is_available() -> None:
    request = make_request(
        items=(RequestedLine("sound_speaker", 1),), packages=(RequestedLine("pkg_basic", 1),)
    )
    assert check_request_availability(request, make_catalog(), (), TWO_HOURS).is_available


def test_several_short_items_are_all_reported_sorted_by_code() -> None:
    bookings = (
        book(at(6, 20), at(7, 1), quantity=3, item_code="sound_speaker"),
        book(at(6, 20), at(7, 1), quantity=2, item_code="sound_mixer", code="bk_2"),
    )
    request = make_request(
        items=(RequestedLine("light_par", 1),), packages=(RequestedLine("pkg_basic", 1),)
    )
    report = check_request_availability(request, make_catalog(), bookings, TWO_HOURS)
    assert [s.item_code for s in report.shortages] == ["sound_mixer", "sound_speaker"]
    assert [a.item_code for a in report.items] == ["light_par", "sound_mixer", "sound_speaker"]


def test_request_availability_respects_cancelled_and_buffer() -> None:
    request = make_request(items=(RequestedLine("sound_mixer", 2),), start=at(6, 18), end=at(7, 2))
    cancelled = (book(at(6, 10), at(6, 18), 2, "sound_mixer", BookingStatus.CANCELLED),)
    back_to_back = (book(at(6, 10), at(6, 18), 2, "sound_mixer"),)
    assert check_request_availability(request, make_catalog(), cancelled, TWO_HOURS).is_available
    assert not check_request_availability(
        request, make_catalog(), back_to_back, TWO_HOURS
    ).is_available
    assert check_request_availability(request, make_catalog(), back_to_back, NO_BUFFER).is_available


def test_three_member_package_with_one_short_member_reports_only_that_member() -> None:
    catalog = Catalog(
        (make_item("sound_speaker", 3), make_item("sound_mixer", 2), make_item("light_par", 4)),
        (
            ServicePackage(
                "pkg_full",
                "Full",
                (
                    PackageLine("sound_speaker", 2),
                    PackageLine("sound_mixer", 1),
                    PackageLine("light_par", 4),
                ),
            ),
        ),
    )
    bookings = (book(at(6, 20), at(7, 1), quantity=1, item_code="light_par"),)
    request = make_request(packages=(RequestedLine("pkg_full", 1),))
    report = check_request_availability(request, catalog, bookings, TWO_HOURS)
    assert not report.is_available
    assert [(a.item_code, a.is_available) for a in report.items] == [
        ("light_par", False),
        ("sound_mixer", True),
        ("sound_speaker", True),
    ]
    assert [(s.item_code, s.requested, s.remaining) for s in report.shortages] == [
        ("light_par", 4, 3)
    ]


# --- result validation ------------------------------------------------------------------------

GOOD = Availability("sound_speaker", requested=2, stock=3, remaining=1)

INVALID_AVAILABILITY: dict[str, Callable[[], Availability]] = {
    "bad-code": lambda: Availability("Bad Code", 1, 3, 1),
    "newline-code": lambda: Availability("abc\n", 1, 3, 1),
    "non-string-code": lambda: Availability(None, 1, 3, 1),  # type: ignore[arg-type]
    "zero-requested": lambda: Availability("sound_speaker", 0, 3, 1),
    "bool-requested": lambda: Availability("sound_speaker", True, 3, 1),
    "float-stock": lambda: Availability("sound_speaker", 1, 3.0, 1),  # type: ignore[arg-type]
    "negative-stock": lambda: Availability("sound_speaker", 1, -1, 0),
    "negative-remaining": lambda: Availability("sound_speaker", 1, 3, -1),
    "bool-remaining": lambda: Availability("sound_speaker", 1, 3, False),
    "remaining-above-stock": lambda: Availability("sound_speaker", 1, 3, 4),
}


@pytest.mark.parametrize("build", INVALID_AVAILABILITY.values(), ids=INVALID_AVAILABILITY.keys())
def test_inconsistent_availability_is_rejected(build: Callable[[], Availability]) -> None:
    with pytest.raises(InvalidAvailability):
        build()


OTHER = Availability("sound_mixer", requested=1, stock=2, remaining=2)

INVALID_REPORTS: dict[str, Callable[[], AvailabilityReport]] = {
    "empty": lambda: AvailabilityReport(()),
    "string": lambda: AvailabilityReport("abc"),  # type: ignore[arg-type]
    "bytes": lambda: AvailabilityReport(b"abc"),  # type: ignore[arg-type]
    "non-iterable": lambda: AvailabilityReport(5),  # type: ignore[arg-type]
    "wrong-element": lambda: AvailabilityReport((GOOD, "x")),  # type: ignore[arg-type]
    "duplicate-code": lambda: AvailabilityReport((GOOD, GOOD)),
    "unsorted": lambda: AvailabilityReport((GOOD, OTHER)),
}


@pytest.mark.parametrize("build", INVALID_REPORTS.values(), ids=INVALID_REPORTS.keys())
def test_inconsistent_report_is_rejected(build: Callable[[], AvailabilityReport]) -> None:
    with pytest.raises(InvalidAvailability):
        build()


def test_report_accepts_sorted_distinct_items_from_any_iterable() -> None:
    report = AvailabilityReport(iter((OTHER, GOOD)))
    assert report.items == (OTHER, GOOD)
    assert report.shortages == (GOOD,)
    assert hash(report) == hash(AvailabilityReport((OTHER, GOOD)))
