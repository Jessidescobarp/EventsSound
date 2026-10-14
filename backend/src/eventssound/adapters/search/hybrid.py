"""Hybrid search: keywords always, vectors when configured, fused with reciprocal rank fusion.

RRF needs no calibrated thresholds, which matters because cosine values depend on the model.
Any embedding-provider or storage failure degrades to the keyword result (`degraded=True`).
"""

from collections.abc import Sequence

from eventssound.adapters.search.keyword import KeywordSearch
from eventssound.adapters.search.validation import check_search_args
from eventssound.application.errors import RepositoryUnavailable
from eventssound.application.llm import LlmError
from eventssound.application.search import MAX_LIMIT, EquipmentSearch, SearchHit, SearchResult
from eventssound.domain.catalog import EquipmentCategory

RRF_K = 60


class HybridSearch:
    def __init__(self, keyword: KeywordSearch, vector: EquipmentSearch | None) -> None:
        self._keyword = keyword
        self._vector = vector

    def search(
        self, queries: Sequence[str], category: EquipmentCategory | None, limit: int
    ) -> tuple[SearchResult, ...]:
        check_search_args(queries, category, limit)  # invalid input is never a fallback case
        if self._vector is None:
            return self._keyword.search(queries, category, limit)
        # Each leg is read deep so a hit missing from one leg can still be fused in.
        keyword_results = self._keyword.search(queries, category, MAX_LIMIT)
        try:
            vector_results = self._vector.search(queries, category, MAX_LIMIT)
        except (LlmError, RepositoryUnavailable):
            return tuple(
                SearchResult(r.hits[:limit], degraded=True)
                for r in self._keyword.search(queries, category, limit)
            )
        return tuple(
            _fuse(k, v, limit) for k, v in zip(keyword_results, vector_results, strict=True)
        )


def _fuse(keyword: SearchResult, vector: SearchResult, limit: int) -> SearchResult:
    scores: dict[tuple[str, str], float] = {}
    parts: dict[tuple[str, str], dict[str, float | None]] = {}
    for hits, field in ((keyword.hits, "keyword_score"), (vector.hits, "vector_similarity")):
        for hit in hits:
            key = (hit.kind, hit.code)
            scores[key] = scores.get(key, 0.0) + 1 / (RRF_K + hit.rank)
            parts.setdefault(key, {})[field] = getattr(hit, field)
    # Equal fused scores: items before packages, then by code (same rule as keyword search).
    ordered = sorted(scores, key=lambda key: (-scores[key], key[0] != "item", key[1]))
    hits = tuple(
        SearchHit(
            kind,  # type: ignore[arg-type]
            code,
            rank,
            keyword_score=parts[(kind, code)].get("keyword_score"),
            vector_similarity=parts[(kind, code)].get("vector_similarity"),
        )
        for rank, (kind, code) in enumerate(ordered[:limit], start=1)
    )
    return SearchResult(hits, confident_code=_confident_code(keyword, vector, hits))


def _confident_code(
    keyword: SearchResult, vector: SearchResult, fused: tuple[SearchHit, ...]
) -> str | None:
    """The item both legs rank first, when keywords do not tie at the top and fusion agrees."""
    if not keyword.hits or not vector.hits or not fused:
        return None
    top = keyword.hits[0]
    if (top.kind, top.code) != (vector.hits[0].kind, vector.hits[0].code) or top.kind != "item":
        return None
    if len(keyword.hits) > 1 and keyword.hits[1].keyword_score == top.keyword_score:
        return None
    if (fused[0].kind, fused[0].code) != (top.kind, top.code):
        return None
    return top.code
