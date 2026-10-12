from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from eventssound.domain.availability import Booking
from eventssound.domain.catalog import Catalog


class DatabaseHealthPort(Protocol):
    def ping(self) -> None:
        """Return normally when the database answers; raise otherwise."""
        ...


@runtime_checkable
class CatalogRepository(Protocol):
    def get_catalog(self) -> Catalog:
        """Return the whole catalog as one consistent snapshot.

        Raises RepositoryUnavailable on storage failure and InvalidStoredData when a stored row
        violates the domain contract.
        """
        ...


@runtime_checkable
class BookingRepository(Protocol):
    def find_reservations(
        self, item_codes: Collection[str], window_start: datetime, window_end: datetime
    ) -> Sequence[Booking]:
        """Item-level bookings of `item_codes` whose [start, end) intersects the window.

        Blocking ones (pending, confirmed) at least; the domain ignores cancelled ones itself.
        Unknown codes yield nothing. Raises InvalidAvailability for a malformed query,
        RepositoryUnavailable on storage failure and InvalidStoredData for a bad stored row.
        """
        ...
