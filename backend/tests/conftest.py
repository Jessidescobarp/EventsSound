"""Shared pytest fixtures."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]

from network_guard import install


@pytest.fixture(autouse=True)
def _network_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that connects to or resolves a non-loopback host (see network_guard)."""
    install(monkeypatch)


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL of a disposable Postgres for tests.

    Skips only when DATABASE_URL_TEST is unset (database tests are opt-in locally).
    When it is set, an unreachable database is a failure, never a silent skip, so a
    broken CI service cannot make the database tests vanish.
    """
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST is not set")
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.fail(
            f"DATABASE_URL_TEST is set but the database is unreachable: {type(exc).__name__}"
        )
    finally:
        engine.dispose()
    return url


def reset_schema(url: str) -> None:
    """Drop every application table and the Alembic bookkeeping table.

    Table names come from the models metadata, so a new model is cleaned up without edits here.
    This is deliberately not `DROP SCHEMA public CASCADE`: it never touches extensions.
    """
    import eventssound.adapters.db.models  # noqa: F401  (registers the tables on Base.metadata)
    from eventssound.adapters.db.session import Base

    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            Base.metadata.drop_all(connection)
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        engine.dispose()


@pytest.fixture
def alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Alembic config bound to the test database, starting from an empty schema."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    reset_schema(database_url)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


@pytest.fixture
def migrated_database(alembic_config: Config, database_url: str) -> Iterator[str]:
    """A test database upgraded to head (empty tables); the schema is dropped afterwards."""
    command.upgrade(alembic_config, "head")
    yield database_url
    reset_schema(database_url)


@pytest.fixture
def session_factory(migrated_database: str) -> Iterator[sessionmaker[Session]]:
    from eventssound.adapters.db.session import build_engine, build_session_factory

    engine = build_engine(migrated_database)
    try:
        yield build_session_factory(engine)
    finally:
        engine.dispose()
