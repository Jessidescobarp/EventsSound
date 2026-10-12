"""Vector search: embed the queries in one batch, rank by cosine similarity in the store.

Provider and storage failures propagate (`LlmError`, `RepositoryUnavailable`); the composite
`HybridSearch` turns them into a keyword fallback. The category filter runs here, in Python,
against the Catalog: with a few dozen rows a pushdown buys nothing.
"""

from collections.abc import Sequence

from eventssound.adapters.search.validation import check_search_args
from eventssound.application.embedding_index import EmbeddingStore
from eventssound.application.embeddings import EmbeddingProvider
from eventssound.application.search import SearchHit, SearchResult
from eventssound.domain.catalog import Catalog, EquipmentCategory

# Cosine values are model specific; this floor only removes noise. UNVERIFIED for real models:
# the retrieval eval tunes it.
DEFAULT_MIN_SIMILARITY = 0.25
_FETCH_CAP = 100


class VectorSearch:
    def __init__(
        self,
        embedder: EmbeddingProvider,
        store: EmbeddingStore,
        catalog: Catalog,
        model: str,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
    ) -> None:
        if type(min_similarity) not in (int, float) or not 0 <= min_similarity <= 1:
            raise ValueError("min_similarity must be a number within 0..1")
        self._embedder = embedder
        self._store = store
        self._catalog = catalog
        self._model = model
        self._min = float(min_similarity)
        self._entries = {("item", i.code): i.category for i in catalog.items} | {
            ("package", p.code): None for p in catalog.packages
        }
        self._fetch = min(max(len(self._entries), 1), _FETCH_CAP)

    def search(
        self, queries: Sequence[str], category: EquipmentCategory | None, limit: int
    ) -> tuple[SearchResult, ...]:
        normalized = check_search_args(queries, category, limit)
        vectors = self._embedder.embed(list(normalized)).vectors
        return tuple(self._one(vector, category, limit) for vector in vectors)

    def _one(
        self, vector: Sequence[float], category: EquipmentCategory | None, limit: int
    ) -> SearchResult:
        hits: list[SearchHit] = []
        for match in self._store.nearest(self._model, vector, self._fetch):
            key = (match.kind, match.code)
            if key not in self._entries or match.similarity < self._min:
                continue  # stale row (left the catalog) or too far away
            if category is not None and self._entries[key] is not category:
                continue  # also excludes packages, which have no category
            hits.append(
                SearchHit(match.kind, match.code, len(hits) + 1, vector_similarity=match.similarity)
            )
            if len(hits) == limit:
                break
        return SearchResult(tuple(hits))
