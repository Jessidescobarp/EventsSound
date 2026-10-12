"""The database schema agrees with the domain: value lists, bounds, column types and defaults."""

import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, inspect, text

from eventssound.domain.availability import Booking, BookingStatus
from eventssound.domain.catalog import (
    EquipmentCategory,
    EquipmentItem,
    PackageLine,
    ServicePackage,
)
from eventssound.domain.errors import DomainError
from eventssound.domain.money import Money

NOW = datetime(2026, 11, 1, 10, tzinfo=UTC)


@pytest.fixture
def engine(migrated_database: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database)
    yield engine
    engine.dispose()


def definition(engine: Engine, name: str) -> str:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
            {"name": name},
        ).scalar_one()


@pytest.mark.parametrize(
    ("constraint", "domain_values"),
    [
        ("ck_equipment_items_category_valid", {c.value for c in EquipmentCategory}),
        ("ck_bookings_status_valid", {s.value for s in BookingStatus}),
    ],
    ids=["category", "status"],
)
def test_check_value_lists_equal_the_domain_enums(
    engine: Engine, constraint: str, domain_values: set[str]
) -> None:
    listed = set(re.findall(r"'([^']+)'", definition(engine, constraint)))

    assert listed
    assert listed == domain_values


def accepts(build: Callable[[int], object], value: int) -> bool:
    try:
        build(value)
    except DomainError:
        return False
    return True


def item(stock: int = 1, price: int = 0) -> EquipmentItem:
    return EquipmentItem("abc", "Equipo", EquipmentCategory.SOUND, stock, Money(price))


def booking(quantity: int) -> Booking:
    return Booking("B-1", "abc", quantity, NOW, NOW + timedelta(hours=1), BookingStatus.PENDING)


BOUNDED = [
    ("ck_equipment_items_stock_nonnegative", lambda v: item(stock=v)),
    ("ck_equipment_items_unit_price_nonnegative", lambda v: item(price=v)),
    (
        "ck_service_packages_discount_range",
        lambda v: ServicePackage("abc", "Paquete", (PackageLine("def", 1),), v),
    ),
    ("ck_package_items_quantity_positive", lambda v: PackageLine("abc", v)),
    ("ck_bookings_quantity_positive", lambda v: booking(v)),
]


@pytest.mark.parametrize(("constraint", "build"), BOUNDED, ids=[name for name, _ in BOUNDED])
def test_numeric_bounds_match_the_domain_boundaries(
    engine: Engine, constraint: str, build: Callable[[int], object]
) -> None:
    text_definition = definition(engine, constraint)
    lower = re.search(r"(>=|>) (-?\d+)", text_definition) or re.search(
        r"BETWEEN (-?\d+) AND", text_definition
    )
    assert lower, text_definition
    first_allowed = int(lower.groups()[-1]) + (1 if lower.group(1) == ">" else 0)
    upper = re.search(r"<= (\d+)", text_definition) or re.search(r"AND (\d+)\)", text_definition)

    assert accepts(build, first_allowed)
    assert not accepts(build, first_allowed - 1)
    if upper:
        last_allowed = int(upper.group(1))
        assert accepts(build, last_allowed)
        assert not accepts(build, last_allowed + 1)


def column_types(engine: Engine) -> dict[tuple[str, str], str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT table_name, column_name, data_type FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
            )
        )
        return {(row[0], row[1]): row[2] for row in rows}


def test_money_ids_and_instants_have_the_wide_types(engine: Engine) -> None:
    types = column_types(engine)

    assert types[("equipment_items", "unit_price_cop")] == "bigint"
    for table in ("equipment_items", "service_packages", "package_items", "bookings"):
        assert types[(table, "id")] == "bigint"
    for column in ("starts_at", "ends_at", "created_at", "updated_at"):
        assert types[("bookings", column)] == "timestamp with time zone"
    assert types[("equipment_items", "stock_quantity")] == "integer"


def test_a_price_above_32_bits_round_trips(engine: Engine) -> None:
    price = 2**31 + 5_000_000_000
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO equipment_items (code, name, category, stock_quantity, unit_price_cop)"
                " VALUES ('abc', 'Equipo', 'sound', 1, :price)"
            ),
            {"price": price},
        )

    with engine.connect() as connection:
        stored = connection.execute(text("SELECT unit_price_cop FROM equipment_items")).scalar_one()

    assert stored == price


def test_defaults_fill_status_discount_and_audit_columns(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO equipment_items (code, name, category, stock_quantity, unit_price_cop)"
                " VALUES ('abc', 'Equipo', 'sound', 1, 1000)"
            )
        )
        connection.execute(text("INSERT INTO service_packages (code, name) VALUES ('pkg', 'P')"))
        connection.execute(
            text(
                "INSERT INTO bookings (booking_code, item_code, quantity, starts_at, ends_at)"
                " VALUES ('BK-1', 'abc', 1, now(), now() + interval '1 hour')"
            )
        )

    with engine.connect() as connection:
        package = connection.execute(
            text("SELECT discount_bps, created_at, updated_at FROM service_packages")
        ).one()
        stored = connection.execute(
            text("SELECT status, created_at, updated_at FROM bookings")
        ).one()
        item_row = connection.execute(
            text("SELECT created_at, updated_at FROM equipment_items")
        ).one()

    assert package.discount_bps == 0
    assert stored.status == "pending"
    now = datetime.now(UTC)
    for stamp in (package.created_at, package.updated_at, stored.created_at, *item_row):
        assert stamp.tzinfo is not None
        assert abs(now - stamp) < timedelta(minutes=5)


EXPECTED_UNIQUE: dict[str, dict[str, list[str]]] = {
    "equipment_items": {"uq_equipment_items_code": ["code"]},
    "service_packages": {"uq_service_packages_code": ["code"]},
    "package_items": {
        "uq_package_items_package_id_equipment_item_id": ["package_id", "equipment_item_id"]
    },
    "bookings": {"uq_bookings_booking_code_item_code": ["booking_code", "item_code"]},
}


@pytest.mark.parametrize("table", sorted(EXPECTED_UNIQUE))
def test_unique_constraints_keep_their_column_order(engine: Engine, table: str) -> None:
    found: Any = {
        constraint["name"]: constraint["column_names"]
        for constraint in inspect(engine).get_unique_constraints(table)
    }

    assert found == EXPECTED_UNIQUE[table]
