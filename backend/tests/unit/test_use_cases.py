"""Catalog, pricing and availability use cases over in-memory fakes."""

from datetime import UTC, datetime, timedelta

import pytest

from eventssound.application.availability import check_event_availability
from eventssound.application.catalog import list_catalog
from eventssound.application.errors import RepositoryUnavailable
from eventssound.application.pricing import price_quote
from eventssound.domain.availability import (
    AvailabilityRules,
    Booking,
    BookingStatus,
    check_request_availability,
    default_availability_rules,
)
from eventssound.domain.catalog import (
    Catalog,
    EquipmentCategory,
    EquipmentItem,
    PackageLine,
    ServicePackage,
)
from eventssound.domain.event_request import EventRequest, EventType, RequestedLine, VenueType
from eventssound.domain.money import Money
from eventssound.domain.pricing import calculate_price
from eventssound.domain.pricing_rules import default_pricing_rules
from fakes import (
    BrokenBookingRepository,
    BrokenCatalogRepository,
    InMemoryBookingRepository,
    InMemoryCatalogRepository,
)

START = datetime(2026, 11, 6, 14, tzinfo=UTC)
END = datetime(2026, 11, 6, 18, tzinfo=UTC)
CATALOG = Catalog(
    items=(
        EquipmentItem("speaker", "Speaker", EquipmentCategory.SOUND, 1, Money(100_000)),
        EquipmentItem("mixer", "Mixer", EquipmentCategory.SOUND, 2, Money(50_000)),
    ),
    packages=(ServicePackage("pkg_basic", "Basic", (PackageLine("speaker", 1),), 0),),
)


def request(**overrides: object) -> EventRequest:
    values: dict[str, object] = {
        "event_type": EventType.CORPORATE,
        "start": START,
        "end": END,
        "guest_count": 50,
        "distance_km": 0,
        "venue": VenueType.INDOOR,
        "items": (RequestedLine("speaker", 1),),
    }
    values.update(overrides)
    return EventRequest(**values)  # type: ignore[arg-type]


def booking(item: str, start: datetime, end: datetime, **overrides: object) -> Booking:
    fields: dict[str, object] = {
        "code": "bk_1",
        "item_code": item,
        "quantity": 1,
        "start": start,
        "end": end,
        "status": BookingStatus.CONFIRMED,
    }
    fields.update(overrides)
    return Booking(**fields)  # type: ignore[arg-type]


def test_list_catalog_returns_the_repository_catalog() -> None:
    assert list_catalog(InMemoryCatalogRepository(CATALOG)) is CATALOG


def test_price_quote_equals_the_pure_oracle() -> None:
    rules = default_pricing_rules()

    quote = price_quote(request(), InMemoryCatalogRepository(CATALOG), rules)

    assert quote == calculate_price(request(), CATALOG, rules)


def test_price_quote_prices_package_members() -> None:
    quote = price_quote(
        request(items=(), packages=(RequestedLine("pkg_basic", 1),)),
        InMemoryCatalogRepository(CATALOG),
        default_pricing_rules(),
    )

    assert quote.total.amount > 0


def test_availability_equals_the_pure_function_over_the_fake_bookings() -> None:
    held = (booking("speaker", START - timedelta(days=1), START - timedelta(hours=20)),)
    rules = default_availability_rules()

    report = check_event_availability(
        request(), InMemoryCatalogRepository(CATALOG), InMemoryBookingRepository(held), rules
    )

    assert report == check_request_availability(request(), CATALOG, held, rules)


def test_booking_inside_the_buffer_before_the_event_blocks_the_item() -> None:
    # Ends one hour before the event starts: outside [start, end) but inside the 2h buffer.
    held = (booking("speaker", START - timedelta(hours=5), START - timedelta(hours=1)),)

    report = check_event_availability(
        request(),
        InMemoryCatalogRepository(CATALOG),
        InMemoryBookingRepository(held),
        AvailabilityRules(buffer=timedelta(hours=2)),
    )

    assert not report.items[0].is_available


def test_booking_inside_the_buffer_after_the_event_blocks_the_item() -> None:
    held = (booking("speaker", END + timedelta(hours=1), END + timedelta(hours=5)),)

    report = check_event_availability(
        request(),
        InMemoryCatalogRepository(CATALOG),
        InMemoryBookingRepository(held),
        AvailabilityRules(buffer=timedelta(hours=2)),
    )

    assert not report.items[0].is_available


def test_booking_beyond_the_buffer_does_not_block() -> None:
    held = (booking("speaker", START - timedelta(hours=9), START - timedelta(hours=3)),)

    report = check_event_availability(
        request(),
        InMemoryCatalogRepository(CATALOG),
        InMemoryBookingRepository(held),
        AvailabilityRules(buffer=timedelta(hours=2)),
    )

    assert report.items[0].is_available


def test_package_members_are_checked() -> None:
    held = (booking("speaker", START, END),)

    report = check_event_availability(
        request(items=(), packages=(RequestedLine("pkg_basic", 1),)),
        InMemoryCatalogRepository(CATALOG),
        InMemoryBookingRepository(held),
        default_availability_rules(),
    )

    assert [(a.item_code, a.is_available) for a in report.items] == [("speaker", False)]


def test_broken_catalog_propagates_repository_unavailable() -> None:
    with pytest.raises(RepositoryUnavailable):
        list_catalog(BrokenCatalogRepository())
    with pytest.raises(RepositoryUnavailable):
        price_quote(request(), BrokenCatalogRepository(), default_pricing_rules())
    with pytest.raises(RepositoryUnavailable):
        check_event_availability(
            request(),
            BrokenCatalogRepository(),
            InMemoryBookingRepository(),
            default_availability_rules(),
        )


def test_broken_bookings_propagate_repository_unavailable() -> None:
    with pytest.raises(RepositoryUnavailable):
        check_event_availability(
            request(),
            InMemoryCatalogRepository(CATALOG),
            BrokenBookingRepository(),
            default_availability_rules(),
        )
