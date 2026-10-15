"""Migration 0007 and the Postgres quote store / booking lister (needs DATABASE_URL_TEST)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from eventssound.adapters.db.quote_repository import SqlAlchemyBookingLister, SqlAlchemyQuoteStore
from eventssound.application.quotes import NewQuote

START = datetime(2026, 11, 14, 18, tzinfo=UTC)
USER_ID = "55555555-5555-4555-8555-555555555555"


@pytest.fixture
def engine(migrated_database: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database)
    yield engine
    engine.dispose()


def new_quote(user_id: str | None = None, total: int = 500_000, **over: object) -> NewQuote:
    values: dict[str, object] = {
        "user_id": user_id,
        "event_type": "wedding",
        "event_start": START,
        "event_end": START + timedelta(hours=5),
        "guest_count": 80,
        "total_cop": total,
        "available": True,
        "quote": {"total": total, "lines": []},
        "event_request": {"guest_count": 80},
    }
    values.update(over)
    return NewQuote(**values)  # type: ignore[arg-type]


def add_user(engine: Engine, user_id: str = USER_ID) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, email, role, password_hash) VALUES (:i, :e, 'client', 'h')"
            ),
            {"i": user_id, "e": f"{user_id[:4]}@example.com"},
        )


def test_add_then_page_returns_the_saved_fields(engine: Engine) -> None:
    store = SqlAlchemyQuoteStore(sessionmaker(engine))

    quote_id = store.add(new_quote(total=777_000))
    page = store.page(None, 20, 0)

    assert page.total == 1 and len(page.items) == 1
    saved = page.items[0]
    assert saved.id == quote_id and saved.total_cop == 777_000 and saved.registered is False
    assert saved.quote == {"total": 777_000, "lines": []} and saved.event_type == "wedding"


def test_pages_are_newest_first_with_a_stable_total_and_offset(engine: Engine) -> None:
    store = SqlAlchemyQuoteStore(sessionmaker(engine))
    ids = [store.add(new_quote(total=1000 * n)) for n in range(1, 6)]

    first = store.page(None, 2, 0)
    second = store.page(None, 2, 2)
    last = store.page(None, 2, 4)

    assert [q.id for q in first.items + second.items + last.items] == ids[::-1]
    assert (first.total, second.total, last.total) == (5, 5, 5)
    assert store.page(None, 2, 10).items == ()


def test_user_filter_returns_only_that_users_quotes(engine: Engine) -> None:
    add_user(engine)
    store = SqlAlchemyQuoteStore(sessionmaker(engine))
    store.add(new_quote())
    mine = store.add(new_quote(USER_ID, total=42_000))

    page = store.page(USER_ID, 20, 0)

    assert [q.id for q in page.items] == [mine] and page.total == 1 and page.items[0].registered


def test_deleting_the_user_keeps_the_quote_as_anonymous(engine: Engine) -> None:
    add_user(engine)
    store = SqlAlchemyQuoteStore(sessionmaker(engine))
    store.add(new_quote(USER_ID))

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM users"))

    assert store.page(None, 20, 0).items[0].registered is False


@pytest.mark.parametrize(
    "bad",
    [{"total_cop": -1}, {"guest_count": 0}, {"event_end": START}],
    ids=["negative-total", "no-guests", "ends-before-start"],
)
def test_check_constraints_reject_bad_rows(engine: Engine, bad: dict) -> None:
    from eventssound.application.errors import RepositoryUnavailable

    store = SqlAlchemyQuoteStore(sessionmaker(engine))

    with pytest.raises(RepositoryUnavailable):
        store.add(new_quote(**bad))


def test_booking_lister_pages_the_flat_bookings_table(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO equipment_items (code, name, category, stock_quantity, unit_price_cop)"
                " VALUES ('sound_x', 'Parlante', 'sound', 5, 1000)"
            )
        )
        for n in range(3):
            connection.execute(
                text(
                    "INSERT INTO bookings (booking_code, item_code, quantity, starts_at, ends_at)"
                    " VALUES (:c, 'sound_x', 1, :s, :e)"
                ),
                {"c": f"BK-{n}", "s": START, "e": START + timedelta(hours=2)},
            )

    page = SqlAlchemyBookingLister(sessionmaker(engine)).page(2, 0)

    assert page.total == 3 and len(page.items) == 2
    assert [b.booking_code for b in page.items] == ["BK-2", "BK-1"] and page.items[
        0
    ].status == "pending"


def test_downgrade_drops_the_table(alembic_config: Config, engine: Engine) -> None:
    command.downgrade(alembic_config, "0006")

    assert "quotes" not in inspect(engine).get_table_names()
