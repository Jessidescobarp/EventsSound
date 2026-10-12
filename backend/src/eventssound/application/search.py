"""Equipment search port: one batched call per chat turn, hits are catalog codes only."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from eventssound.domain.catalog import EquipmentCategory

MAX_QUERIES = 16
MAX_QUERY_CHARS = 200
MIN_LIMIT, MAX_LIMIT = 1, 10


class InvalidSearch(Exception):
    """The caller passed an invalid query, limit or category (not a storage failure)."""


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A catalog entry found for a query. `rank` is 1-based; names and prices stay in Catalog."""

    kind: Literal["item", "package"]
    code: str
    rank: int
    keyword_score: float | None = None
    vector_similarity: float | None = None


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Hits for one query. `degraded` means the vector leg failed and keywords answered."""

    hits: tuple[SearchHit, ...]
    degraded: bool = False


@runtime_checkable
class EquipmentSearch(Protocol):
    def search(
        self, queries: Sequence[str], category: EquipmentCategory | None, limit: int
    ) -> tuple[SearchResult, ...]:
        """One result per query, in order. Raises InvalidSearch for bad arguments.

        `limit` is 1..10, each query 1..200 characters after normalization, at most 16 queries.
        Hits reference only codes of the current catalog; nothing matching means no hits (the
        implementation never pads the result with nearest neighbours).
        """
        ...
