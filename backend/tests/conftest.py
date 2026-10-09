"""Shared pytest fixtures."""

import os

import pytest
from sqlalchemy import create_engine, text


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL of a disposable Postgres for tests; skips cleanly when unavailable."""
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST is not set")
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("Postgres from DATABASE_URL_TEST is not reachable")
    finally:
        engine.dispose()
    return url
