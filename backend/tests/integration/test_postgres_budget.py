"""PostgresUsageBudget and migration 0004 against the throwaway database and fail-closed paths."""

import logging
import threading
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from conftest import SECRETS_IN_UNREACHABLE_URL
from eventssound.adapters.usage.memory import InMemoryUsageBudget
from eventssound.adapters.usage.postgres import PostgresUsageBudget, UsageStoreError
from eventssound.application.usage import Reservation
from eventssound.config import Settings
from eventssound.entrypoints.api.container import make_usage_budget

NOON = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
TODAY = NOON.date()


def budget(
    factory: sessionmaker[Session],
    now: datetime = NOON,
    token_cap: int = 1_000,
    cost_cap: int = 10_000,
) -> PostgresUsageBudget:
    return PostgresUsageBudget(
        factory, token_cap=token_cap, cost_cap_micro_usd=cost_cap, now=lambda: now
    )


def row(factory: sessionmaker[Session], day: date = TODAY) -> tuple[int, int] | None:
    with factory() as session:
        found = session.execute(
            text("SELECT tokens, cost_micro_usd FROM llm_usage_daily WHERE day = :d"), {"d": day}
        ).first()
    return None if found is None else (found[0], found[1])


@pytest.mark.parametrize(
    ("tokens", "cost", "error"),
    [
        (-1, 0, ValueError),
        (0, -1, ValueError),
        (2**53 + 1, 0, ValueError),
        (1.5, 0, TypeError),
        (True, 0, TypeError),
        ("1", 0, TypeError),
        (0, None, TypeError),
    ],
)
def test_invalid_amounts_are_rejected_before_any_database_call(
    unreachable_session_factory: sessionmaker[Session], tokens: object, cost: object, error: type
) -> None:
    b = budget(unreachable_session_factory)
    with pytest.raises(error):
        b.reserve(tokens, cost)  # type: ignore[arg-type]
    with pytest.raises(error):
        b.settle(Reservation(NOON.date(), 0, 0), tokens, cost)  # type: ignore[arg-type]


def test_an_oversized_reserve_is_denied_without_touching_the_database(
    unreachable_session_factory: sessionmaker[Session],
) -> None:
    assert budget(unreachable_session_factory).reserve(1_001, 0) is None
    assert budget(unreachable_session_factory).reserve(0, 10_001) is None


def test_reserve_fails_closed_and_logs_only_the_class_name(
    unreachable_session_factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG), pytest.raises(UsageStoreError) as raised:
        budget(unreachable_session_factory).reserve(10, 10)
    # Nothing from the driver error may stay attached to the exception.
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    shown = caplog.text + repr(raised.value)
    assert "OperationalError" in caplog.text
    assert not any(secret in shown for secret in SECRETS_IN_UNREACHABLE_URL)


def test_settle_never_raises_when_the_database_is_down(
    unreachable_session_factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        budget(unreachable_session_factory).settle(Reservation(NOON.date(), 10, 10), 5, 5)
    assert "OperationalError" in caplog.text
    assert not any(secret in caplog.text for secret in SECRETS_IN_UNREACHABLE_URL)


def test_a_statement_error_fails_closed(alembic_config: Config, database_url: str) -> None:
    # Empty schema (no llm_usage_daily): the statement itself fails, not the connection.
    engine = create_engine(database_url)
    try:
        with pytest.raises(UsageStoreError):
            budget(sessionmaker(bind=engine)).reserve(1, 1)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("reserves", "granted"),
    [
        ([(1_000, 0)], [True]),  # exactly the token cap
        ([(1_000, 0), (1, 0)], [True, False]),  # one over the token cap
        ([(0, 10_000), (0, 1)], [True, False]),  # cost cap, same boundary
        ([(0, 9_999), (0, 1), (0, 1)], [True, True, False]),  # cost cap, one below then exact
        ([(600, 0), (401, 0), (400, 0)], [True, False, True]),  # a denial consumes nothing
    ],
)
def test_reserve_enforces_both_caps_inclusively(
    session_factory: sessionmaker[Session], reserves: list[tuple[int, int]], granted: list[bool]
) -> None:
    b = budget(session_factory)
    assert [b.reserve(t, c) is not None for t, c in reserves] == granted


def test_settle_refunds_records_overrun_and_floors_at_zero(
    session_factory: sessionmaker[Session],
) -> None:
    b = budget(session_factory)
    first = b.reserve(800, 800)
    assert first is not None
    b.settle(first, 300, 100)  # refund the unused part
    assert row(session_factory) == (300, 100)
    second = b.reserve(100, 100)
    assert second is not None
    b.settle(second, 900, 900)  # overrun is recorded as it happened
    assert row(session_factory) == (1_200, 1_000)
    assert b.reserve(1, 0) is None  # and the next reserve sees it
    b.settle(Reservation(NOON.date(), 5_000, 5_000), 0, 0)  # stale reservation
    assert row(session_factory) == (0, 0)


def test_the_day_rolls_over_at_utc_midnight(session_factory: sessionmaker[Session]) -> None:
    last_second = datetime(2026, 10, 12, 23, 59, 59, tzinfo=UTC)
    midnight = last_second + timedelta(seconds=1)
    assert budget(session_factory, last_second, token_cap=10).reserve(10, 0) is not None
    assert budget(session_factory, last_second, token_cap=10).reserve(1, 0) is None
    fresh = budget(session_factory, midnight, token_cap=10).reserve(10, 0)
    assert fresh is not None
    assert fresh.day == date(2026, 10, 13)
    assert row(session_factory, date(2026, 10, 12)) == (10, 0)
    assert row(session_factory, date(2026, 10, 13)) == (10, 0)


def test_a_non_utc_clock_is_converted_to_the_utc_day(
    session_factory: sessionmaker[Session],
) -> None:
    bogota_evening = datetime(2026, 10, 12, 19, 0, tzinfo=timezone(timedelta(hours=-5)))
    granted = budget(session_factory, bogota_evening).reserve(1, 0)
    assert granted is not None
    assert granted.day == date(2026, 10, 13)


def test_concurrent_reserves_never_exceed_the_cap(session_factory: sessionmaker[Session]) -> None:
    b = budget(session_factory, token_cap=1_000, cost_cap=10**9)
    results: list[bool] = []
    barrier = threading.Barrier(30)

    def worker() -> None:
        barrier.wait()
        results.append(b.reserve(100, 1) is not None)

    threads = [threading.Thread(target=worker) for _ in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 10
    assert row(session_factory) == (1_000, 10)


def test_the_budget_survives_a_new_instance(session_factory: sessionmaker[Session]) -> None:
    assert budget(session_factory, token_cap=10).reserve(10, 0) is not None
    assert budget(session_factory, token_cap=10).reserve(1, 0) is None  # "restart"


# --- migration 0004 ---------------------------------------------------------------------------


@pytest.fixture
def engine(migrated_database: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database)
    yield engine
    engine.dispose()


def test_the_migration_round_trips_and_creates_an_empty_table(
    alembic_config: Config, database_url: str
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "0003")
    command.upgrade(alembic_config, "head")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert {c["name"] for c in inspector.get_columns("llm_usage_daily")} == {
            "day",
            "tokens",
            "cost_micro_usd",
            "updated_at",
        }
        assert inspector.get_pk_constraint("llm_usage_daily")["name"] == "pk_llm_usage_daily"
        checks = {c["name"] for c in inspector.get_check_constraints("llm_usage_daily")}
        assert checks == {
            "ck_llm_usage_daily_tokens_non_negative",
            "ck_llm_usage_daily_cost_non_negative",
        }
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM llm_usage_daily")).scalar() == 0
        command.downgrade(alembic_config, "0003")
        assert "llm_usage_daily" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


@pytest.mark.parametrize("column", ["tokens", "cost_micro_usd"])
def test_the_table_refuses_negative_counters(engine: Engine, column: str) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text(f"INSERT INTO llm_usage_daily (day, {column}) VALUES (now(), -1)"))


def test_settle_on_another_day_changes_only_the_reserved_day(
    session_factory: sessionmaker[Session],
) -> None:
    reservation = budget(session_factory).reserve(100, 100)
    assert reservation is not None
    next_day = NOON + timedelta(days=1)
    budget(session_factory, next_day).settle(reservation, 40, 40)
    assert row(session_factory) == (40, 40)
    assert row(session_factory, next_day.date()) is None


def test_settle_for_an_unknown_day_creates_no_row(session_factory: sessionmaker[Session]) -> None:
    budget(session_factory).settle(Reservation(date(2020, 1, 1), 5, 5), 9, 9)
    assert row(session_factory, date(2020, 1, 1)) is None


# --- bounded waits ----------------------------------------------------------------------------


@pytest.fixture
def locked_day(session_factory: sessionmaker[Session]) -> Iterator[Reservation]:
    """Today's row exists and another connection holds its row lock for the whole test."""
    reservation = budget(session_factory).reserve(10, 10)
    assert reservation is not None
    session = session_factory()
    session.execute(text("SELECT 1 FROM llm_usage_daily WHERE day = :d FOR UPDATE"), {"d": TODAY})
    try:
        yield reservation
    finally:
        session.rollback()
        session.close()


def fast_budget(factory: sessionmaker[Session]) -> PostgresUsageBudget:
    return PostgresUsageBudget(
        factory,
        token_cap=1_000,
        cost_cap_micro_usd=10_000,
        now=lambda: NOON,
        lock_timeout_ms=300,
    )


def test_reserve_times_out_on_a_held_lock_and_fails_closed(
    session_factory: sessionmaker[Session], locked_day: Reservation
) -> None:
    started = time.monotonic()
    with pytest.raises(UsageStoreError):
        fast_budget(session_factory).reserve(1, 1)
    assert time.monotonic() - started < 3


def test_settle_times_out_on_a_held_lock_without_raising(
    session_factory: sessionmaker[Session],
    locked_day: Reservation,
    caplog: pytest.LogCaptureFixture,
) -> None:
    started = time.monotonic()
    with caplog.at_level(logging.ERROR):
        fast_budget(session_factory).settle(locked_day, 0, 0)
    assert time.monotonic() - started < 3
    assert "usage settle failed" in caplog.text


# --- container choice -------------------------------------------------------------------------

OPENROUTER = {"llm_provider": "openrouter", "llm_model": "m", "openrouter_api_key": "k"}


@pytest.mark.parametrize("app_env", ["local", "Local", "production", "staging", "test"])
@pytest.mark.parametrize(
    ("provider", "expected"),
    [({}, InMemoryUsageBudget), (OPENROUTER, PostgresUsageBudget)],
    ids=["replay", "openrouter"],
)
def test_an_openrouter_chat_always_gets_the_persistent_budget(
    unreachable_session_factory: sessionmaker[Session],
    app_env: str,
    provider: dict[str, object],
    expected: type,
) -> None:
    values = {"DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1:1/x", "app_env": app_env}
    settings = Settings(_env_file=None, **(values | provider))  # type: ignore[arg-type]
    chosen = make_usage_budget(settings, unreachable_session_factory)
    assert type(chosen) is expected


def test_a_disabled_openrouter_chat_needs_no_persistent_budget(
    unreachable_session_factory: sessionmaker[Session],
) -> None:
    values = {"DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1:1/x", "chat_enabled": False}
    settings = Settings(_env_file=None, **(values | OPENROUTER))  # type: ignore[arg-type]
    assert type(make_usage_budget(settings, unreachable_session_factory)) is InMemoryUsageBudget


def test_a_live_cap_source_overrides_the_constructor_caps_per_reserve(
    session_factory: sessionmaker[Session],
) -> None:
    live = [(1_000, 10_000)]
    b = PostgresUsageBudget(
        session_factory,
        token_cap=1_000,
        cost_cap_micro_usd=10_000,
        now=lambda: NOON,
        caps=lambda: live[0],
    )
    assert b.reserve(600, 0) is not None
    live[0] = (700, 10_000)  # lowered: the atomic upsert WHERE uses the new cap
    assert b.reserve(101, 0) is None
    assert b.reserve(100, 0) is not None
    live[0] = (5_000, 10_000)  # raised above the constructor cap: the insert path honors it too
    assert b.reserve(2_000, 0) is not None
    assert row(session_factory) == (2_700, 0)


def test_lowering_a_cap_below_the_usage_refuses_new_reserves_and_keeps_the_row(
    session_factory: sessionmaker[Session],
) -> None:
    live = [(1_000, 10_000)]
    b = PostgresUsageBudget(
        session_factory,
        token_cap=1_000,
        cost_cap_micro_usd=10_000,
        now=lambda: NOON,
        caps=lambda: live[0],
    )
    assert b.reserve(800, 5_000) is not None
    live[0] = (500, 3_000)  # below today's usage on both counters
    assert b.reserve(1, 0) is None and b.reserve(0, 1) is None
    assert row(session_factory) == (800, 5_000)  # refusing changed nothing
