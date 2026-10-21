from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from eventssound.domain.agent_config import AgentConfig, StoredAgentConfig
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


@runtime_checkable
class AgentConfigRepository(Protocol):
    def get_active(self) -> StoredAgentConfig | None:
        """The highest version, or None when nothing was saved yet.

        Raises RepositoryUnavailable on storage failure and InvalidStoredData when the stored
        values no longer parse. `load_active_config` then falls back to the environment defaults,
        NOT to the previous version.
        """
        ...

    def save(
        self, config: AgentConfig, *, base_version: int, user_id: UUID | None, note: str | None
    ) -> StoredAgentConfig:
        """Append a new version and one audit row in the same transaction.

        `base_version` is the version the caller read (0 when none existed). Raises
        VersionConflict when it is not the current maximum, InvalidAgentConfig when the config
        or the note is invalid (nothing is written) and RepositoryUnavailable on failure.
        """
        ...

    def history(self, limit: int) -> list[StoredAgentConfig]:
        """The newest `limit` versions, newest first; a row that no longer parses is skipped."""
        ...
