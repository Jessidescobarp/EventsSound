"""Catalog and bookings schema: tables, constraints, naming, reversibility and model drift."""

import ast
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from eventssound.adapters.db.session import Base

BACKEND_DIR = Path(__file__).resolve().parents[2]
TABLES = {"equipment_items", "service_packages", "package_items", "bookings"}
ALL_TABLES = TABLES | {"catalog_embeddings", "llm_usage_daily", "users"}  # 0003, 0004, 0006

ITEM: dict[str, Any] = {
    "code": "sound_speaker",
    "name": "Parlante",
    "category": "sound",
    "stock": 5,
    "price": 50000,
}
BOOKING: dict[str, Any] = {
    "booking": "BK-1",
    "item": "sound_speaker",
    "quantity": 2,
    "starts": datetime(2026, 11, 1, 10, tzinfo=UTC),
    "ends": datetime(2026, 11, 1, 18, tzinfo=UTC),
    "status": "pending",
}


@pytest.fixture
def engine(migrated_database: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database)
    yield engine
    engine.dispose()


def insert_item(connection: Connection, **overrides: Any) -> int:
    row = connection.execute(
        text(
            "INSERT INTO equipment_items (code, name, category, stock_quantity, unit_price_cop)"
            " VALUES (:code, :name, :category, :stock, :price) RETURNING id"
        ),
        {**ITEM, **overrides},
    )
    return row.scalar_one()


def insert_package(connection: Connection, code: str = "pkg_party", discount: int = 0) -> int:
    row = connection.execute(
        text(
            "INSERT INTO service_packages (code, name, discount_bps)"
            " VALUES (:code, 'Fiesta', :discount) RETURNING id"
        ),
        {"code": code, "discount": discount},
    )
    return row.scalar_one()


def insert_booking(connection: Connection, **overrides: Any) -> None:
    connection.execute(
        text(
            "INSERT INTO bookings (booking_code, item_code, quantity, starts_at, ends_at, status)"
            " VALUES (:booking, :item, :quantity, :starts, :ends, :status)"
        ),
        {**BOOKING, **overrides},
    )


def count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_upgrade_creates_exactly_the_catalog_tables_and_they_are_empty(engine: Engine) -> None:
    assert table_names(engine) == ALL_TABLES
    assert [count(engine, table) for table in sorted(ALL_TABLES)] == [0] * len(ALL_TABLES)


def test_downgrade_to_the_baseline_and_to_base_removes_every_table(
    alembic_config: Config, migrated_database: str, engine: Engine
) -> None:
    command.downgrade(alembic_config, "0001")
    assert table_names(engine) == set()

    command.downgrade(alembic_config, "base")
    assert table_names(engine) == set()


def test_upgrade_downgrade_upgrade_round_trip_restores_the_schema(
    alembic_config: Config, engine: Engine
) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    assert table_names(engine) == ALL_TABLES


def test_repeat_upgrade_is_a_no_op(alembic_config: Config, engine: Engine) -> None:
    command.upgrade(alembic_config, "head")

    assert table_names(engine) == ALL_TABLES


def constraint_and_index_names(engine: Engine) -> set[str]:
    inspector = inspect(engine)
    names: set[str] = set()
    for table in TABLES:
        names.add(inspector.get_pk_constraint(table)["name"])
        names.update(c["name"] for c in inspector.get_unique_constraints(table))
        names.update(c["name"] for c in inspector.get_check_constraints(table))
        names.update(c["name"] for c in inspector.get_foreign_keys(table))
        names.update(i["name"] for i in inspector.get_indexes(table))
    return names


EXPECTED_NAMES = {
    "pk_equipment_items",
    "uq_equipment_items_code",
    "ck_equipment_items_category_valid",
    "ck_equipment_items_stock_nonnegative",
    "ck_equipment_items_unit_price_nonnegative",
    "pk_service_packages",
    "uq_service_packages_code",
    "ck_service_packages_discount_range",
    "pk_package_items",
    "uq_package_items_package_id_equipment_item_id",
    "fk_package_items_package_id_service_packages",
    "fk_package_items_equipment_item_id_equipment_items",
    "ck_package_items_quantity_positive",
    "ix_package_items_equipment_item_id",
    "pk_bookings",
    "uq_bookings_booking_code_item_code",
    "fk_bookings_item_code_equipment_items",
    "ck_bookings_quantity_positive",
    "ck_bookings_ends_after_starts",
    "ck_bookings_status_valid",
    "ix_bookings_item_code",
}


def test_constraints_and_indexes_have_the_conventional_names(engine: Engine) -> None:
    names = constraint_and_index_names(engine)

    assert names >= EXPECTED_NAMES
    assert all(name.split("_")[0] in {"pk", "fk", "uq", "ck", "ix"} for name in names)


def test_bookings_index_serves_the_availability_query(engine: Engine) -> None:
    indexes = {i["name"]: i["column_names"] for i in inspect(engine).get_indexes("bookings")}

    assert indexes["ix_bookings_item_code"] == ["item_code", "starts_at", "ends_at"]


@pytest.mark.parametrize(
    ("table_overrides", "violated"),
    [
        ({"stock": -1}, "ck_equipment_items_stock_nonnegative"),
        ({"price": -1}, "ck_equipment_items_unit_price_nonnegative"),
        ({"category": "pyrotechnics"}, "ck_equipment_items_category_valid"),
        ({"category": ""}, "ck_equipment_items_category_valid"),
    ],
    ids=["negative-stock", "negative-price", "unknown-category", "empty-category"],
)
def test_equipment_item_constraints_reject_invalid_rows(
    engine: Engine, table_overrides: dict[str, Any], violated: str
) -> None:
    with pytest.raises(IntegrityError, match=violated), engine.begin() as connection:
        insert_item(connection, **table_overrides)

    assert count(engine, "equipment_items") == 0


def test_equipment_item_accepts_zero_stock_and_zero_price(engine: Engine) -> None:
    with engine.begin() as connection:
        insert_item(connection, stock=0, price=0)

    assert count(engine, "equipment_items") == 1


def test_duplicate_item_code_is_rejected(engine: Engine) -> None:
    with engine.begin() as connection:
        insert_item(connection)

    with pytest.raises(IntegrityError, match="uq_equipment_items_code"), engine.begin() as c:
        insert_item(c)


@pytest.mark.parametrize("discount", [-1, 10_001], ids=["below", "above"])
def test_package_discount_must_be_within_basis_points(engine: Engine, discount: int) -> None:
    with (
        pytest.raises(IntegrityError, match="ck_service_packages_discount_range"),
        engine.begin() as connection,
    ):
        insert_package(connection, discount=discount)


def test_duplicate_package_code_is_rejected(engine: Engine) -> None:
    with engine.begin() as connection:
        insert_package(connection)

    with pytest.raises(IntegrityError, match="uq_service_packages_code"), engine.begin() as c:
        insert_package(c)


def insert_package_item(connection: Connection, package: int, item: int, quantity: int) -> None:
    connection.execute(
        text(
            "INSERT INTO package_items (package_id, equipment_item_id, quantity)"
            " VALUES (:package, :item, :quantity)"
        ),
        {"package": package, "item": item, "quantity": quantity},
    )


@pytest.mark.parametrize("quantity", [0, -3], ids=["zero", "negative"])
def test_package_item_quantity_must_be_positive(engine: Engine, quantity: int) -> None:
    with engine.begin() as connection:
        item, package = insert_item(connection), insert_package(connection)

    with (
        pytest.raises(IntegrityError, match="ck_package_items_quantity_positive"),
        engine.begin() as connection,
    ):
        insert_package_item(connection, package, item, quantity)


def test_package_cannot_list_the_same_item_twice(engine: Engine) -> None:
    with engine.begin() as connection:
        item, package = insert_item(connection), insert_package(connection)
        insert_package_item(connection, package, item, 1)

    with (
        pytest.raises(IntegrityError, match="uq_package_items_package_id_equipment_item_id"),
        engine.begin() as connection,
    ):
        insert_package_item(connection, package, item, 2)


def test_package_item_must_reference_existing_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        item = insert_item(connection)

    with (
        pytest.raises(IntegrityError, match="fk_package_items_package_id_service_packages"),
        engine.begin() as connection,
    ):
        insert_package_item(connection, 999_999, item, 1)


def test_deleting_a_package_cascades_to_its_lines(engine: Engine) -> None:
    with engine.begin() as connection:
        item, package = insert_item(connection), insert_package(connection)
        insert_package_item(connection, package, item, 1)

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM service_packages"))

    assert count(engine, "package_items") == 0
    assert count(engine, "equipment_items") == 1


def test_deleting_an_item_used_by_a_package_is_restricted(engine: Engine) -> None:
    with engine.begin() as connection:
        item, package = insert_item(connection), insert_package(connection)
        insert_package_item(connection, package, item, 1)

    with (
        pytest.raises(IntegrityError, match="fk_package_items_equipment_item_id"),
        engine.begin() as connection,
    ):
        connection.execute(text("DELETE FROM equipment_items"))


@pytest.mark.parametrize(
    ("overrides", "violated"),
    [
        ({"quantity": 0}, "ck_bookings_quantity_positive"),
        ({"quantity": -1}, "ck_bookings_quantity_positive"),
        ({"ends": BOOKING["starts"]}, "ck_bookings_ends_after_starts"),
        ({"ends": BOOKING["starts"] - timedelta(hours=1)}, "ck_bookings_ends_after_starts"),
        ({"status": "archived"}, "ck_bookings_status_valid"),
        ({"item": "missing_item"}, "fk_bookings_item_code_equipment_items"),
    ],
    ids=[
        "quantity-zero",
        "quantity-negative",
        "ends-equal-starts",
        "ends-before-starts",
        "unknown-status",
        "unknown-item",
    ],
)
def test_booking_constraints_reject_invalid_rows(
    engine: Engine, overrides: dict[str, Any], violated: str
) -> None:
    with engine.begin() as connection:
        insert_item(connection)

    with pytest.raises(IntegrityError, match=violated), engine.begin() as connection:
        insert_booking(connection, **overrides)

    assert count(engine, "bookings") == 0


@pytest.mark.parametrize("status", ["pending", "confirmed", "cancelled"])
def test_booking_accepts_every_known_status(engine: Engine, status: str) -> None:
    with engine.begin() as connection:
        insert_item(connection)
        insert_booking(connection, status=status)

    assert count(engine, "bookings") == 1


def test_booking_item_pair_is_unique(engine: Engine) -> None:
    with engine.begin() as connection:
        insert_item(connection)
        insert_booking(connection)

    with (
        pytest.raises(IntegrityError, match="uq_bookings_booking_code_item_code"),
        engine.begin() as connection,
    ):
        insert_booking(connection)


def test_one_booking_can_reserve_several_items(engine: Engine) -> None:
    with engine.begin() as connection:
        insert_item(connection)
        insert_item(connection, code="light_par")
        insert_booking(connection)
        insert_booking(connection, item="light_par")

    assert count(engine, "bookings") == 2


def test_deleting_a_booked_item_is_restricted(engine: Engine) -> None:
    with engine.begin() as connection:
        insert_item(connection)
        insert_booking(connection)

    with (
        pytest.raises(IntegrityError, match="fk_bookings_item_code_equipment_items"),
        engine.begin() as connection,
    ):
        connection.execute(text("DELETE FROM equipment_items"))


def test_booking_timestamps_keep_their_timezone_and_instant(engine: Engine) -> None:
    utc_minus_5 = timezone(timedelta(hours=-5))
    starts = datetime(2026, 11, 1, 20, 0, tzinfo=utc_minus_5)
    ends = datetime(2026, 11, 2, 2, 0, tzinfo=utc_minus_5)
    with engine.begin() as connection:
        insert_item(connection)
        insert_booking(connection, starts=starts, ends=ends)

    with engine.connect() as connection:
        row = connection.execute(text("SELECT starts_at, ends_at FROM bookings")).one()

    assert row.starts_at.tzinfo is not None
    assert row.starts_at == starts
    assert row.ends_at == ends
    assert row.starts_at.astimezone(UTC) == datetime(2026, 11, 2, 1, 0, tzinfo=UTC)


def test_models_match_the_migrated_schema(engine: Engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_migration_env_imports_the_models_module() -> None:
    tree = ast.parse((BACKEND_DIR / "migrations" / "env.py").read_text(encoding="utf-8"))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "eventssound.adapters.db.models" in imported
