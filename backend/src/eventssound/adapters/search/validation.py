"""Argument validation of the EquipmentSearch port, shared by every search adapter."""

from collections.abc import Sequence

from eventssound.adapters.search.text import normalize
from eventssound.application.search import (
    MAX_LIMIT,
    MAX_QUERIES,
    MAX_QUERY_CHARS,
    MIN_LIMIT,
    InvalidSearch,
)
from eventssound.domain.catalog import EquipmentCategory

_RAW_QUERY_CAP = 1_000  # bounds the work done before normalization


def check_search_args(queries: object, category: object, limit: object) -> tuple[str, ...]:
    """Validate the port arguments; returns the normalized queries."""
    if isinstance(queries, str | bytes) or not isinstance(queries, Sequence):
        raise InvalidSearch("queries must be a sequence of strings")
    if not 1 <= len(queries) <= MAX_QUERIES:
        raise InvalidSearch(f"queries must hold 1..{MAX_QUERIES} entries")
    if type(limit) is not int or not MIN_LIMIT <= limit <= MAX_LIMIT:
        raise InvalidSearch(f"limit must be an int within {MIN_LIMIT}..{MAX_LIMIT}")
    if category is not None and not isinstance(category, EquipmentCategory):
        raise InvalidSearch("category must be an EquipmentCategory or None")
    normalized = []
    for query in queries:
        if not isinstance(query, str) or len(query) > _RAW_QUERY_CAP:
            raise InvalidSearch("each query must be a short string")
        folded = normalize(query)
        if not 1 <= len(folded) <= MAX_QUERY_CHARS:
            raise InvalidSearch(f"each query must have 1..{MAX_QUERY_CHARS} characters")
        normalized.append(folded)
    return tuple(normalized)
