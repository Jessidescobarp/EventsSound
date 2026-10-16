"""Portfolio events: the store port. Hiding an event replaces deleting it."""

from dataclasses import dataclass
from typing import Protocol

from eventssound.domain.portfolio import PortfolioEvent


@dataclass(frozen=True, slots=True)
class StoredPortfolioEvent:
    id: int
    event: PortfolioEvent


class PortfolioStore(Protocol):
    """Storage errors raise RepositoryUnavailable; updating a missing id raises NotFound."""

    def list_events(self, visible_only: bool) -> tuple[StoredPortfolioEvent, ...]:
        """Oldest first (`id`); `visible_only` hides the events an admin switched off."""
        ...

    def add(self, event: PortfolioEvent) -> int: ...

    def update(self, event_id: int, event: PortfolioEvent) -> None: ...
