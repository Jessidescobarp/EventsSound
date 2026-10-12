"""SqlAlchemyBookingRepository and the row mapping (the DB tests need DATABASE_URL_TEST)."""

import traceback
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session, sessionmaker

from conftest import SECRETS_IN_UNREACHABLE_URL
from eventssound.adapters.db.booking_repository import (
    SqlAlchemyBookingRepository,
    booking_from_row,
)
from eventssound.adapters.db.models import BookingModel, EquipmentItemModel
from eventssound.application.errors import InvalidStoredData, RepositoryUnavailable
from eventssound.application.ports import BookingRepository
from eventssound.domain.availability import Booking, BookingStatus
from eventssound.domain.errors import InvalidAvailability

START = datetime(2026, 11, 1, 10, tzinfo=UTC)
END = datetime(2026, 11, 1, 18, tzinfo=UTC)
HOUR = timedelta(hours=1)
CODES = {"sound_speaker"}


def put(
    factory: sessionmaker[Session], bookings: list[dict], items=("sound_speaker", "light_par")
) -> None:
    with factory.begin() as session:
        session.add_all(
            EquipmentItemModel(
                code=code, name="Equipo", category="sound", stock_quantity=5, unit_price_cop=1000
            )
            for code in items
        )
        session.flush()
        session.add_all(BookingModel(**row) for row in bookings)


def row(code: str, start=START, end=END, status="confirmed", item="sound_speaker", quantity=1):
    return {
        "booking_code": code,
        "item_code": item,
        "quantity": quantity,
        "starts_at": start,
        "ends_at": end,
        "status": status,
    }


def codes_found(factory: sessionmaker[Session], window=(START, END), codes=CODES) -> list[str]:
    return [b.code for b in SqlAlchemyBookingRepository(factory).find_reservations(codes, *window)]


def test_repository_satisfies_the_port(session_factory: sessionmaker[Session]) -> None:
    assert isinstance(SqlAlchemyBookingRepository(session_factory), BookingRepository)


def test_one_row_becomes_one_validated_booking(session_factory: sessionmaker[Session]) -> None:
    put(session_factory, [row("BK-7", quantity=3, status="pending")])

    found = SqlAlchemyBookingRepository(session_factory).find_reservations(CODES, START, END)

    assert list(found) == [Booking("BK-7", "sound_speaker", 3, START, END, BookingStatus.PENDING)]
    assert found[0].start.tzinfo is not None


def test_pending_and_confirmed_block_but_cancelled_does_not(
    session_factory: sessionmaker[Session],
) -> None:
    put(
        session_factory,
        [
            row("BK-1", status="pending"),
            row("BK-2", status="confirmed"),
            row("BK-3", status="cancelled"),
        ],
    )

    assert sorted(codes_found(session_factory)) == ["BK-1", "BK-2"]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (START + HOUR, END - HOUR, True),
        (START - HOUR, START + HOUR, True),
        (END - HOUR, END + HOUR, True),
        (START - HOUR, END + HOUR, True),
        (START - 2 * HOUR, START, False),
        (END, END + 2 * HOUR, False),
        (START - 9 * HOUR, START - 8 * HOUR, False),
        (END + 8 * HOUR, END + 9 * HOUR, False),
    ],
    ids=[
        "inside",
        "overlaps-start",
        "overlaps-end",
        "contains-window",
        "ends-at-window-start",
        "starts-at-window-end",
        "far-before",
        "far-after",
    ],
)
def test_window_intersection_is_half_open(
    session_factory: sessionmaker[Session], start: datetime, end: datetime, expected: bool
) -> None:
    put(session_factory, [row("BK-1", start=start, end=end)])

    assert (codes_found(session_factory) == ["BK-1"]) is expected


def test_only_the_requested_item_codes_are_returned(session_factory: sessionmaker[Session]) -> None:
    put(
        session_factory, [row("BK-1"), row("BK-1", item="light_par"), row("BK-2", item="light_par")]
    )

    assert codes_found(session_factory, codes={"light_par"}) == ["BK-1", "BK-2"]
    assert codes_found(session_factory, codes=["sound_speaker", "light_par"]) == [
        "BK-1",
        "BK-1",
        "BK-2",
    ]


def test_unknown_codes_and_empty_collections_yield_nothing(
    session_factory: sessionmaker[Session],
) -> None:
    put(session_factory, [row("BK-1")])

    assert codes_found(session_factory, codes={"no_such_item"}) == []
    assert codes_found(session_factory, codes=[]) == []


def test_window_offsets_are_compared_as_instants(session_factory: sessionmaker[Session]) -> None:
    plus_two = timezone(timedelta(hours=2))
    put(session_factory, [row("BK-1")])

    inside = (datetime(2026, 11, 1, 18, tzinfo=plus_two), END + HOUR)
    touching = (datetime(2026, 11, 1, 20, tzinfo=plus_two), END + 2 * HOUR)

    assert codes_found(session_factory, window=inside) == ["BK-1"]
    assert codes_found(session_factory, window=touching) == []


def test_results_are_ordered_deterministically(session_factory: sessionmaker[Session]) -> None:
    put(
        session_factory,
        [row("BK-B", start=START + HOUR), row("BK-C", start=START), row("BK-A", start=START)],
    )

    assert codes_found(session_factory) == ["BK-A", "BK-C", "BK-B"]


def test_a_stored_row_with_a_bad_booking_code_is_rejected(
    session_factory: sessionmaker[Session],
) -> None:
    put(session_factory, [row("bad code!")])

    with pytest.raises(InvalidStoredData):
        codes_found(session_factory)


@pytest.mark.parametrize(
    ("codes", "start", "end"),
    [
        ("sound_speaker", START, END),
        (CODES, START.replace(tzinfo=None), END),
        (CODES, END, START),
    ],
    ids=["string-codes", "naive-start", "inverted-window"],
)
def test_malformed_queries_raise_before_touching_the_database(
    unreachable_session_factory: sessionmaker[Session], codes, start, end
) -> None:
    repository = SqlAlchemyBookingRepository(unreachable_session_factory)

    with pytest.raises(InvalidAvailability):
        repository.find_reservations(codes, start, end)


def test_storage_failure_is_reported_without_connection_details(
    unreachable_session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyBookingRepository(unreachable_session_factory)

    with pytest.raises(RepositoryUnavailable) as caught:
        repository.find_reservations(CODES, START, END)

    rendered = str(caught.value) + "".join(traceback.format_exception(caught.value))
    for secret in SECRETS_IN_UNREACHABLE_URL:
        assert secret not in rendered


def stored(**overrides) -> SimpleNamespace:
    fields = {
        "booking_code": "BK-1",
        "item_code": "sound_speaker",
        "quantity": 2,
        "starts_at": START,
        "ends_at": END,
        "status": "confirmed",
    }
    return SimpleNamespace(**{**fields, **overrides})


def test_row_mapping_builds_the_domain_booking() -> None:
    assert booking_from_row(stored()) == Booking(
        "BK-1", "sound_speaker", 2, START, END, BookingStatus.CONFIRMED
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"booking_code": ""},
        {"booking_code": "x" * 65},
        {"booking_code": "has space"},
        {"booking_code": None},
        {"item_code": "UPPER"},
        {"item_code": None},
        {"quantity": 0},
        {"quantity": True},
        {"quantity": 1.0},
        {"quantity": None},
        {"starts_at": START.replace(tzinfo=None)},
        {"starts_at": "2026-11-01"},
        {"ends_at": START},
        {"status": "archived"},
        {"status": None},
    ],
    ids=[
        "empty-code",
        "long-code",
        "space-code",
        "none-code",
        "uppercase-item",
        "none-item",
        "zero-quantity",
        "bool-quantity",
        "float-quantity",
        "none-quantity",
        "naive-start",
        "string-start",
        "empty-interval",
        "unknown-status",
        "none-status",
    ],
)
def test_row_mapping_rejects_untrusted_values_with_a_typed_error(overrides: dict) -> None:
    with pytest.raises(InvalidStoredData):
        booking_from_row(stored(**overrides))
