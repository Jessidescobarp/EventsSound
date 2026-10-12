"""Ports, the reservation query value and the in-memory fakes."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from eventssound.application.booking_query import ReservationQuery
from eventssound.application.errors import InvalidStoredData, RepositoryUnavailable
from eventssound.application.ports import BookingRepository, CatalogRepository
from eventssound.domain.availability import Booking, BookingStatus
from eventssound.domain.catalog import Catalog
from eventssound.domain.errors import DomainError, InvalidAvailability
from fakes import (
    BrokenBookingRepository,
    BrokenCatalogRepository,
    InMemoryBookingRepository,
    InMemoryCatalogRepository,
)

START = datetime(2026, 11, 1, 10, tzinfo=UTC)
END = datetime(2026, 11, 1, 18, tzinfo=UTC)


def booking(code: str = "BK-1", item: str = "sound_speaker", **overrides) -> Booking:
    fields = {
        "code": code,
        "item_code": item,
        "quantity": 1,
        "start": START,
        "end": END,
        "status": BookingStatus.CONFIRMED,
    }
    return Booking(**{**fields, **overrides})


def test_fakes_satisfy_the_ports() -> None:
    assert isinstance(InMemoryCatalogRepository(Catalog((), ())), CatalogRepository)
    assert isinstance(BrokenCatalogRepository(), CatalogRepository)
    assert isinstance(InMemoryBookingRepository(), BookingRepository)
    assert isinstance(BrokenBookingRepository(), BookingRepository)


def test_catalog_fake_returns_its_catalog() -> None:
    catalog = Catalog((), ())

    assert InMemoryCatalogRepository(catalog).get_catalog() is catalog


@pytest.mark.parametrize(
    "repository", [BrokenCatalogRepository(), BrokenBookingRepository()], ids=["catalog", "booking"]
)
def test_broken_fakes_raise_repository_unavailable(repository) -> None:
    with pytest.raises(RepositoryUnavailable):
        if isinstance(repository, BrokenCatalogRepository):
            repository.get_catalog()
        else:
            repository.find_reservations({"sound_speaker"}, START, END)


def test_repository_errors_are_not_domain_errors() -> None:
    assert not issubclass(RepositoryUnavailable, DomainError)
    assert not issubclass(InvalidStoredData, DomainError)


@pytest.mark.parametrize(
    ("window", "expected"),
    [
        ((START, END), True),
        ((START - timedelta(hours=1), START + timedelta(minutes=1)), True),
        ((END - timedelta(minutes=1), END + timedelta(hours=1)), True),
        ((START - timedelta(hours=3), END + timedelta(hours=3)), True),
        ((START - timedelta(hours=2), START), False),
        ((END, END + timedelta(hours=2)), False),
    ],
    ids=["same", "overlap-start", "overlap-end", "containing", "touches-start", "touches-end"],
)
def test_booking_fake_filters_by_half_open_window(
    window: tuple[datetime, datetime], expected: bool
) -> None:
    found = InMemoryBookingRepository([booking()]).find_reservations({"sound_speaker"}, *window)

    assert bool(found) is expected


def test_booking_fake_filters_by_item_code_and_keeps_every_status() -> None:
    cancelled = booking("BK-2", status=BookingStatus.CANCELLED)
    other = booking("BK-3", item="light_par")
    repository = InMemoryBookingRepository([booking(), cancelled, other])

    found = repository.find_reservations(["sound_speaker"], START, END)

    assert [b.code for b in found] == ["BK-1", "BK-2"]


def test_booking_fake_compares_instants_across_offsets() -> None:
    plus_two = timezone(timedelta(hours=2))
    repository = InMemoryBookingRepository([booking()])

    # 18:00+02:00 is 16:00 UTC, inside the booking; 20:00+02:00 is exactly the booking end.
    inside = repository.find_reservations(
        {"sound_speaker"}, datetime(2026, 11, 1, 18, tzinfo=plus_two), END + timedelta(hours=1)
    )
    touching = repository.find_reservations(
        {"sound_speaker"}, datetime(2026, 11, 1, 20, tzinfo=plus_two), END + timedelta(hours=1)
    )

    assert len(inside) == 1
    assert touching == ()


def test_query_normalizes_codes_and_instants() -> None:
    plus_two = timezone(timedelta(hours=2))

    query = ReservationQuery(
        ["b_item", "a_item", "a_item"], datetime(2026, 11, 1, 12, tzinfo=plus_two), END
    )

    assert query.item_codes == frozenset({"a_item", "b_item"})
    assert query.window_start == START
    assert query.window_start.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("codes", "start", "end"),
    [
        ("sound_speaker", START, END),
        (b"sound_speaker", START, END),
        (None, START, END),
        (["sound_speaker", 7], START, END),
        ([["sound_speaker"]], START, END),
        (["sound_speaker"], START.replace(tzinfo=None), END),
        (["sound_speaker"], START, END.replace(tzinfo=None)),
        (["sound_speaker"], "2026-11-01", END),
        (["sound_speaker"], START, START),
        (["sound_speaker"], END, START),
        (["sound_speaker"], datetime.max.replace(tzinfo=timezone(timedelta(hours=-5))), END),
    ],
    ids=[
        "string-codes",
        "bytes-codes",
        "none-codes",
        "non-string-element",
        "nested-element",
        "naive-start",
        "naive-end",
        "string-start",
        "empty-window",
        "inverted-window",
        "out-of-range-instant",
    ],
)
def test_invalid_queries_raise_a_typed_error(codes, start, end) -> None:
    with pytest.raises(InvalidAvailability):
        ReservationQuery(codes, start, end)


def test_empty_code_collection_is_a_valid_query() -> None:
    assert ReservationQuery([], START, END).item_codes == frozenset()
