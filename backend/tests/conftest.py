"""Shared pytest fixtures."""

import os

import pytest
from sqlalchemy import create_engine, text


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
