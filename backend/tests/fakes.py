"""In-memory fakes of the application ports, for use-case tests without a database."""

import math
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime

from eventssound.application.booking_query import ReservationQuery
from eventssound.application.embedding_index import StoredEmbedding, VectorMatch
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
