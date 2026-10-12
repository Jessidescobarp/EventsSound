"""The synthetic seed definitions are plain data validated without a database."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from eventssound.adapters.db.seed_data import SEED_BOOKINGS, SEED_ITEMS, SEED_PACKAGES
from eventssound.domain.availability import (
    BookingStatus,
    check_availability,
    default_availability_rules,
)
from eventssound.domain.catalog import Catalog, EquipmentCategory
from eventssound.domain.event_request import EventRequest, EventType, RequestedLine, VenueType
from eventssound.domain.pricing import calculate_price
from eventssound.domain.pricing_rules import default_pricing_rules

SLUG = re.compile(r"[a-z][a-z0-9_]*")
BOGOTA = ZoneInfo("America/Bogota")


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog(SEED_ITEMS, SEED_PACKAGES)


def test_counts_and_unique_codes(catalog: Catalog) -> None:
    assert len(SEED_ITEMS) == 20
    assert len(SEED_PACKAGES) == 4
    assert len({item.code for item in SEED_ITEMS}) == 20
    assert len({package.code for package in SEED_PACKAGES}) == 4


def test_codes_are_english_slugs() -> None:
    codes = [item.code for item in SEED_ITEMS] + [package.code for package in SEED_PACKAGES]

    assert all(SLUG.fullmatch(code) for code in codes)


def test_every_category_is_covered() -> None:
    assert {item.category for item in SEED_ITEMS} == set(EquipmentCategory)


def test_prices_and_stock_follow_the_seed_rules() -> None:
    assert all(item.unit_price.amount > 0 for item in SEED_ITEMS)
    assert all(item.unit_price.amount % 1000 == 0 for item in SEED_ITEMS)
    assert all(1 <= item.stock_quantity <= 24 for item in SEED_ITEMS)
    assert any(item.stock_quantity > 1 for item in SEED_ITEMS)


def test_packages_have_four_to_six_lines_and_a_modest_discount() -> None:
    assert all(4 <= len(package.lines) <= 6 for package in SEED_PACKAGES)
    assert all(500 <= package.discount_bps <= 1500 for package in SEED_PACKAGES)


def test_names_are_present_and_unique() -> None:
    names = [item.name for item in SEED_ITEMS] + [package.name for package in SEED_PACKAGES]

    assert all(name.strip() for name in names)
    assert len(set(names)) == len(names)


@pytest.mark.parametrize("package", SEED_PACKAGES, ids=lambda package: package.code)
def test_every_package_can_be_priced_with_the_default_rules(
    catalog: Catalog, package: object
) -> None:
    request = EventRequest(
        event_type=EventType.WEDDING,
        start=datetime(2026, 11, 14, 18, tzinfo=BOGOTA),
        end=datetime(2026, 11, 15, 1, tzinfo=BOGOTA),
        guest_count=80,
        distance_km=10,
        venue=VenueType.INDOOR,
        packages=(RequestedLine(package.code, 1),),
    )

    quote = calculate_price(request, catalog, default_pricing_rules())

    assert quote.total.amount > 0
    assert quote.total.amount % 1000 == 0


def test_sample_bookings_reference_seed_items_and_mix_statuses() -> None:
    item_codes = {item.code for item in SEED_ITEMS}

    assert len(SEED_BOOKINGS) >= 4
    assert all(booking.item_code in item_codes for booking in SEED_BOOKINGS)
    assert len({(b.code, b.item_code) for b in SEED_BOOKINGS}) == len(SEED_BOOKINGS)
    assert {BookingStatus.CONFIRMED, BookingStatus.PENDING, BookingStatus.CANCELLED} <= {
        booking.status for booking in SEED_BOOKINGS
    }


def test_sample_bookings_reduce_availability_except_cancelled_ones(catalog: Catalog) -> None:
    blocking = [b for b in SEED_BOOKINGS if b.status in BookingStatus.blocking()]
    cancelled = [b for b in SEED_BOOKINGS if b.status is BookingStatus.CANCELLED]
    sample = cancelled[0]
    held = sum(b.quantity for b in blocking if b.item_code == sample.item_code)
    assert held > 0, "the cancelled booking's item must also have a blocking booking"

    availability = check_availability(
        catalog.item(sample.item_code),
        sample.start,
        sample.end,
        SEED_BOOKINGS,
        default_availability_rules(),
    )

    assert availability.remaining == availability.stock - held
    assert 0 < availability.remaining < availability.stock
