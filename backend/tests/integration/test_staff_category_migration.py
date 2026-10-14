"""Migration 0005: the `staff` equipment category in the category CHECK constraint."""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

INSERT = (
    "INSERT INTO equipment_items (code, name, category, stock_quantity, unit_price_cop)"
    " VALUES (:code, 'Servicio', :category, 1, 1000)"
)


@pytest.fixture
def engine(migrated_database: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database)
    yield engine
    engine.dispose()


def insert(engine: Engine, category: str, code: str = "abc") -> None:
    with engine.begin() as connection:
        connection.execute(text(INSERT), {"code": code, "category": category})


def test_head_accepts_staff_and_still_rejects_unknown_categories(engine: Engine) -> None:
    insert(engine, "staff")

    with pytest.raises(IntegrityError):
        insert(engine, "catering", "other")


def test_upgrade_from_0004_keeps_existing_rows(alembic_config: Config, engine: Engine) -> None:
    command.downgrade(alembic_config, "0004")
    insert(engine, "sound")

    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT category FROM equipment_items")).scalar_one() == "sound"
        )
    insert(engine, "staff", "abd")


def test_downgrade_restores_the_old_check_when_no_staff_rows_exist(
    alembic_config: Config, engine: Engine
) -> None:
    command.downgrade(alembic_config, "0004")

    with pytest.raises(IntegrityError):
        insert(engine, "staff")
    insert(engine, "sound")


def test_downgrade_refuses_to_run_while_staff_rows_exist_and_changes_nothing(
    alembic_config: Config, engine: Engine
) -> None:
    insert(engine, "staff")

    with pytest.raises(RuntimeError, match="staff"):
        command.downgrade(alembic_config, "0004")

    insert(engine, "staff", "abd")  # the schema is still at head
