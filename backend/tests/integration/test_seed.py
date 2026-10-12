"""seed_catalog against a real Postgres: idempotent, convergent and non-destructive."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.db.catalog_repository import SqlAlchemyCatalogRepository
from eventssound.adapters.db.seed import SeedResult, seed_catalog
from eventssound.adapters.db.seed_data import SEED_BOOKINGS, SEED_ITEMS, SEED_PACKAGES
from eventssound.application.errors import RepositoryUnavailable
from eventssound.domain.availability import Booking, BookingStatus
from eventssound.domain.catalog import EquipmentCategory, EquipmentItem
from eventssound.domain.errors import DomainError, InvalidCatalog, UnknownCatalogEntry
from eventssound.domain.money import Money

LINES = sum(len(package.lines) for package in SEED_PACKAGES)

SNAPSHOT_QUERIES = {
    "items": "SELECT code, name, category, stock_quantity, unit_price_cop"
    " FROM equipment_items ORDER BY code",
    "packages": "SELECT code, name, discount_bps FROM service_packages ORDER BY code",
    "lines": "SELECT p.code, i.code, l.quantity FROM package_items l"
    " JOIN service_packages p ON p.id = l.package_id"
    " JOIN equipment_items i ON i.id = l.equipment_item_id ORDER BY 1, 2",
    "bookings": "SELECT booking_code, item_code, quantity, starts_at, ends_at, status"
    " FROM bookings ORDER BY 1, 2",
}


def run(factory: sessionmaker[Session], sql: str, **params: object) -> list[tuple]:
    with factory.begin() as session:
        result = session.execute(text(sql), params)
        return [tuple(row) for row in result] if result.returns_rows else []


def snapshot(factory: sessionmaker[Session]) -> dict[str, list[tuple]]:
    return {name: run(factory, sql) for name, sql in SNAPSHOT_QUERIES.items()}


def seed(factory: sessionmaker[Session]) -> SeedResult:
    return seed_catalog(factory, SEED_ITEMS, SEED_PACKAGES, SEED_BOOKINGS)


def test_first_run_loads_everything_and_reports_counts(
    session_factory: sessionmaker[Session],
) -> None:
    result = seed(session_factory)

    assert result == SeedResult(items=20, packages=4, bookings=len(SEED_BOOKINGS))
    data = snapshot(session_factory)
    assert len(data["items"]) == 20
    assert len(data["packages"]) == 4
    assert len(data["lines"]) == LINES
    assert len(data["bookings"]) == len(SEED_BOOKINGS)


def test_the_seeded_database_loads_back_as_the_seed_catalog(
    session_factory: sessionmaker[Session],
) -> None:
    seed(session_factory)

    catalog = SqlAlchemyCatalogRepository(session_factory).get_catalog()

    assert {item.code: item for item in catalog.items} == {i.code: i for i in SEED_ITEMS}
    assert len(catalog.packages) == len(SEED_PACKAGES)
    for expected in SEED_PACKAGES:
        stored = catalog.package(expected.code)
        assert (stored.name, stored.discount_bps) == (expected.name, expected.discount_bps)
        assert set(stored.lines) == set(expected.lines)


def test_running_twice_creates_no_duplicates_and_changes_nothing(
    session_factory: sessionmaker[Session],
) -> None:
    seed(session_factory)
    first = snapshot(session_factory)
    created = run(session_factory, "SELECT code, created_at FROM equipment_items ORDER BY code")

    second_result = seed(session_factory)

    assert second_result == SeedResult(items=20, packages=4, bookings=len(SEED_BOOKINGS))
    assert snapshot(session_factory) == first
    assert run(session_factory, "SELECT code, created_at FROM equipment_items ORDER BY code") == (
        created
    )


def test_drifted_values_are_restored(session_factory: sessionmaker[Session]) -> None:
    seed(session_factory)
    expected = snapshot(session_factory)
    run(session_factory, "UPDATE equipment_items SET unit_price_cop = 1, stock_quantity = 99")
    run(session_factory, "UPDATE service_packages SET discount_bps = 0, name = 'x'")
    run(session_factory, "UPDATE package_items SET quantity = 77")
    run(session_factory, "UPDATE bookings SET status = 'cancelled', quantity = 50")

    seed(session_factory)

    assert snapshot(session_factory) == expected


def test_a_package_line_removed_from_the_definition_is_deleted(
    session_factory: sessionmaker[Session],
) -> None:
    seed(session_factory)
    package = SEED_PACKAGES[0]
    stray = next(i.code for i in SEED_ITEMS if i.code not in {ln.item_code for ln in package.lines})
    run(
        session_factory,
        "INSERT INTO package_items (package_id, equipment_item_id, quantity)"
        " SELECT p.id, i.id, 3 FROM service_packages p, equipment_items i"
        " WHERE p.code = :package AND i.code = :item",
        package=package.code,
        item=stray,
    )
    assert len(snapshot(session_factory)["lines"]) == LINES + 1

    seed(session_factory)

    assert len(snapshot(session_factory)["lines"]) == LINES


def test_rows_outside_the_seed_survive_and_foreign_bookings_are_untouched(
    session_factory: sessionmaker[Session],
) -> None:
    seed(session_factory)
    run(
        session_factory,
        "INSERT INTO equipment_items (code, name, category, stock_quantity, unit_price_cop)"
        " VALUES ('custom_item', 'Hecho a mano', 'sound', 1, 5000)",
    )
    run(
        session_factory,
        "INSERT INTO service_packages (code, name, discount_bps) VALUES ('pkg_custom', 'Mio', 0)",
    )
    run(
        session_factory,
        "INSERT INTO bookings (booking_code, item_code, quantity, starts_at, ends_at, status)"
        " VALUES ('REAL-1', 'sound_mixer_16ch', 1, now(), now() + interval '1 hour', 'confirmed')",
    )
    before = run(session_factory, "SELECT * FROM bookings WHERE booking_code = 'REAL-1'")

    seed(session_factory)

    codes = [row[0] for row in run(session_factory, "SELECT code FROM equipment_items")]
    assert "custom_item" in codes
    assert [r[0] for r in run(session_factory, "SELECT code FROM service_packages")].count(
        "pkg_custom"
    ) == 1
    assert run(session_factory, "SELECT * FROM bookings WHERE booking_code = 'REAL-1'") == before


def test_a_failure_part_way_rolls_everything_back(session_factory: sessionmaker[Session]) -> None:
    run(session_factory, "ALTER TABLE bookings RENAME TO bookings_moved")
    try:
        with pytest.raises(RepositoryUnavailable):
            seed(session_factory)
    finally:
        run(session_factory, "ALTER TABLE bookings_moved RENAME TO bookings")

    assert run(session_factory, "SELECT count(*) FROM equipment_items") == [(0,)]
    assert run(session_factory, "SELECT count(*) FROM service_packages") == [(0,)]


def booking(item: str = "sound_mixer_16ch", code: str = "DEMO-9") -> Booking:
    start = datetime(2026, 12, 1, 10, tzinfo=UTC)
    return Booking(
        code, item, 1, start, datetime(2026, 12, 1, 12, tzinfo=UTC), BookingStatus.PENDING
    )


def custom_item(code: str = "custom_mixer") -> EquipmentItem:
    return EquipmentItem(code, "Mezclador", EquipmentCategory.SOUND, 2, Money(10_000))


@pytest.mark.parametrize(
    ("items", "packages", "bookings", "error"),
    [
        ([custom_item(), custom_item()], [], [], InvalidCatalog),
        ([custom_item()], list(SEED_PACKAGES), [], UnknownCatalogEntry),
        ([custom_item()], [], [booking("not_seeded")], InvalidCatalog),
        ([custom_item()], [], [booking("custom_mixer"), booking("custom_mixer")], InvalidCatalog),
        ([custom_item()], [], ["DEMO-1"], InvalidCatalog),
        ("custom_mixer", [], [], InvalidCatalog),
        ([object()], [], [], InvalidCatalog),
    ],
    ids=[
        "duplicate-items",
        "package-with-unknown-item",
        "booking-of-unseeded-item",
        "duplicate-booking-pair",
        "booking-is-a-string",
        "items-is-a-string",
        "item-is-an-object",
    ],
)
def test_invalid_definitions_raise_a_domain_error_and_write_nothing(
    session_factory: sessionmaker[Session], items, packages, bookings, error
) -> None:
    with pytest.raises(error) as caught:
        seed_catalog(session_factory, items, packages, bookings)

    assert isinstance(caught.value, DomainError)
    assert run(session_factory, "SELECT count(*) FROM equipment_items") == [(0,)]


def test_a_custom_definition_can_be_seeded_without_bookings(
    session_factory: sessionmaker[Session],
) -> None:
    result = seed_catalog(session_factory, [custom_item()], [])

    assert result == SeedResult(items=1, packages=0, bookings=0)
    assert run(session_factory, "SELECT code FROM equipment_items") == [("custom_mixer",)]
