"""In-memory fakes of the application ports, for use-case tests without a database."""

from collections.abc import Collection, Iterable, Sequence
from datetime import datetime

from eventssound.application.booking_query import ReservationQuery
from eventssound.application.errors import RepositoryUnavailable
from eventssound.domain.availability import Booking
from eventssound.domain.catalog import Catalog


class InMemoryCatalogRepository:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    def get_catalog(self) -> Catalog:
        return self._catalog


class InMemoryBookingRepository:
    """Returns bookings of the requested items intersecting the half-open window, any status.

    Like the real adapter it validates the query; unlike it, it does not pre-filter by status, so
    use-case tests exercise the domain's own handling of cancelled bookings.
    """

    def __init__(self, bookings: Iterable[Booking] = ()) -> None:
        self._bookings = tuple(bookings)

    def find_reservations(
        self, item_codes: Collection[str], window_start: datetime, window_end: datetime
    ) -> Sequence[Booking]:
        query = ReservationQuery(item_codes, window_start, window_end)
        return tuple(
            booking
            for booking in self._bookings
            if booking.item_code in query.item_codes
            and booking.start < query.window_end
            and booking.end > query.window_start
        )


class BrokenCatalogRepository:
    def get_catalog(self) -> Catalog:
        raise RepositoryUnavailable("catalog storage unavailable")


class BrokenBookingRepository:
    def find_reservations(
        self, item_codes: Collection[str], window_start: datetime, window_end: datetime
    ) -> Sequence[Booking]:
        raise RepositoryUnavailable("booking storage unavailable")
