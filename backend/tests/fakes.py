"""In-memory fakes of the application ports, for use-case tests without a database."""

import math
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime

from eventssound.application.booking_query import ReservationQuery
from eventssound.application.embedding_index import StoredEmbedding, VectorMatch
from eventssound.application.errors import RepositoryUnavailable
from eventssound.application.quotes import Page
from eventssound.application.security import StoredEvent
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


class InMemoryEmbeddingStore:
    """Mirrors the SQL adapter: per-model rows, cosine similarity, ties by (kind, code)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], tuple[str, tuple[float, ...]]] = {}
        self.nearest_calls = 0

    def existing_hashes(self, model: str) -> dict[tuple[str, str], str]:
        return {(k, c): h for (k, c, m), (h, _) in self.rows.items() if m == model}

    def upsert(self, model: str, rows: Sequence["StoredEmbedding"]) -> None:
        for row in rows:
            self.rows[(row.kind, row.code, model)] = (row.content_hash, row.vector)

    def prune(self, model: str, keep: Collection[tuple[str, str]]) -> int:
        doomed = [key for key in self.rows if key[2] != model or (key[0], key[1]) not in keep]
        for key in doomed:
            del self.rows[key]
        return len(doomed)

    def nearest(self, model: str, vector: Sequence[float], limit: int) -> tuple["VectorMatch", ...]:
        self.nearest_calls += 1
        scored = []
        for (kind, code, row_model), (_, stored) in self.rows.items():
            if row_model != model:
                continue
            dot = sum(a * b for a, b in zip(vector, stored, strict=True))
            norm = math.sqrt(sum(a * a for a in vector)) * math.sqrt(sum(b * b for b in stored))
            scored.append(VectorMatch(kind, code, dot / norm))  # type: ignore[arg-type]
        scored.sort(key=lambda m: (-m.similarity, m.kind, m.code))
        return tuple(scored[:limit])


class BrokenEmbeddingStore:
    def existing_hashes(self, model: str) -> dict[tuple[str, str], str]:
        raise RepositoryUnavailable("embedding storage unavailable")

    def upsert(self, model: str, rows: Sequence["StoredEmbedding"]) -> None:
        raise RepositoryUnavailable("embedding storage unavailable")

    def prune(self, model: str, keep: Collection[tuple[str, str]]) -> int:
        raise RepositoryUnavailable("embedding storage unavailable")

    def nearest(self, model: str, vector: Sequence[float], limit: int) -> tuple["VectorMatch", ...]:
        raise RepositoryUnavailable("embedding storage unavailable")


class InMemorySecurityLog:
    def __init__(self, broken: bool = False) -> None:
        self.rows: list[tuple[str, str, datetime]] = []
        self.broken = broken

    def add(self, kind: str, client: str, at: datetime) -> None:
        if self.broken:
            raise RepositoryUnavailable
        self.rows.append((kind, client, at))

    def count_since(self, kind: str, client: str, since: datetime) -> int:
        if self.broken:
            raise RepositoryUnavailable
        return sum(1 for k, c, at in self.rows if (k, c) == (kind, client) and at >= since)

    def page(self, limit: int, offset: int) -> Page[StoredEvent]:
        newest = sorted(self.rows, key=lambda r: r[2], reverse=True)
        items = tuple(StoredEvent(i, at, k, c) for i, (k, c, at) in enumerate(newest, 1))
        return Page(items[offset : offset + limit], len(items), limit, offset)

    def summary(self, since: datetime) -> dict[str, int]:
        counts: dict[str, int] = {}
        for kind, _, at in self.rows:
            if at >= since:
                counts[kind] = counts.get(kind, 0) + 1
        return counts


class InMemoryAgentConfigRepository:
    """`put` stores the next version (1, 2, ...); reads follow the port (newest first)."""

    def __init__(self, broken: bool = False) -> None:
        self.versions: list = []
        self.audit_rows: list = []
        self.saves: list = []
        self.broken = broken
        self.reads = 0

    @property
    def active(self):
        return self.versions[-1] if self.versions else None

    def put(self, config, user_id=None) -> None:
        from datetime import UTC

        from eventssound.domain.agent_config import StoredAgentConfig

        stored = StoredAgentConfig(
            config, len(self.versions) + 1, datetime(2026, 10, 20, tzinfo=UTC), user_id
        )
        self.versions.append(stored)

    def get_active(self):
        self.reads += 1
        if self.broken:
            raise RepositoryUnavailable
        return self.active

    def history(self, limit: int):
        if self.broken:
            raise RepositoryUnavailable
        return list(reversed(self.versions))[:limit]

    def save(self, config, *, base_version, user_id, note, action="save"):
        """Like the adapter: the next version, or VersionConflict when the base is not current."""
        from eventssound.application.errors import VersionConflict
        from eventssound.domain.agent_config import AuditEntry, validate_note

        if self.broken:
            raise RepositoryUnavailable
        note = validate_note(note)  # like the adapter, before writing
        if base_version != len(self.versions):
            raise VersionConflict
        old = self.active.config.to_dict() if self.active else {}
        self.put(config, user_id)
        stored = self.versions[-1]
        diff = {k: [old.get(k), v] for k, v in config.to_dict().items() if old.get(k) != v}
        self.audit_rows.append(
            AuditEntry(stored.version, stored.created_at, user_id, action, diff, note)
        )
        self.saves.append((config, base_version, user_id, note, action))
        return stored

    def audit(self, limit: int):
        if self.broken:
            raise RepositoryUnavailable
        return list(reversed(self.audit_rows))[:limit]
