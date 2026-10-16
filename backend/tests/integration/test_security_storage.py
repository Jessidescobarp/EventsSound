"""Migration 0009 and the Postgres security log (needs DATABASE_URL_TEST)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.orm import sessionmaker

from eventssound.adapters.db.security_repository import SqlAlchemySecurityLog

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


@pytest.fixture
def engine(migrated_database: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database)
    yield engine
    engine.dispose()


def test_table_and_indexes_exist(engine: Engine) -> None:
    inspector = inspect(engine)

    assert {c["name"] for c in inspector.get_columns("security_events")} == {
        "id",
        "at",
        "kind",
        "client",
    }
    indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("security_events")}
    assert indexes["ix_security_events_kind_client_at"] == ["kind", "client", "at"]
    assert indexes["ix_security_events_at"] == ["at"]


def test_log_counts_pages_and_summarises(engine: Engine) -> None:
    log = SqlAlchemySecurityLog(sessionmaker(engine))
    old = NOW - timedelta(days=2)
    log.add("chat_refused", "aaaa", NOW)
    log.add("chat_refused", "aaaa", NOW - timedelta(minutes=11))
    log.add("chat_refused", "bbbb", NOW)
    log.add("login_failed", "aaaa", old)

    assert log.count_since("chat_refused", "aaaa", NOW - timedelta(minutes=10)) == 1
    assert log.count_since("chat_refused", "aaaa", NOW - timedelta(hours=1)) == 2
    assert log.summary(NOW - timedelta(days=1)) == {"chat_refused": 3}
    page = log.page(2, 0)
    assert page.total == 4 and len(page.items) == 2 and page.items[0].at == NOW
    assert log.page(2, 3).items[0].kind == "login_failed"
