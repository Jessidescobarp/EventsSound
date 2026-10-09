from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", database_url)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def current_versions(database_url: str) -> list[str]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return [
                row[0]
                for row in connection.execute(text("SELECT version_num FROM alembic_version"))
            ]
    finally:
        engine.dispose()


def application_tables(database_url: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_there_is_exactly_one_head(alembic_config: Config) -> None:
    assert len(ScriptDirectory.from_config(alembic_config).get_heads()) == 1


def test_upgrade_to_head_records_baseline(alembic_config: Config, database_url: str) -> None:
    command.upgrade(alembic_config, "head")

    head = ScriptDirectory.from_config(alembic_config).get_current_head()
    assert current_versions(database_url) == [head]


def test_second_upgrade_is_a_no_op(alembic_config: Config, database_url: str) -> None:
    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")

    assert len(current_versions(database_url)) == 1


def test_downgrade_to_base_leaves_no_application_tables(
    alembic_config: Config, database_url: str
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    assert current_versions(database_url) == []
    assert application_tables(database_url) == set()
