"""VectorSearch and HybridSearch over the fake embedder and the in-memory store."""

from collections.abc import Sequence

import pytest

from agent_fixtures import make_catalog
from eventssound.adapters.embeddings.fake import FakeEmbeddingProvider
from eventssound.adapters.search.hybrid import RRF_K, HybridSearch
from eventssound.adapters.search.keyword import KeywordSearch
from eventssound.adapters.search.vector import VectorSearch
from eventssound.application.embedding_index import refresh_embeddings
from eventssound.application.embeddings import EmbeddingResult
from eventssound.application.errors import RepositoryUnavailable
from eventssound.application.llm import LlmRateLimited, LlmUnavailable
from eventssound.application.search import EquipmentSearch, InvalidSearch
from eventssound.domain.catalog import Catalog, EquipmentCategory
from fakes import BrokenEmbeddingStore, InMemoryEmbeddingStore

CATALOG = make_catalog()
MODEL = "fake-embedding"
ALIASES = {"amplificacion": "parlante", "mezclar": "consola"}


def embedder() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider(dimensions=1024, model=MODEL, aliases=ALIASES)


def indexed_store() -> InMemoryEmbeddingStore:
    store = InMemoryEmbeddingStore()
    refresh_embeddings(CATALOG, embedder(), store, MODEL)
    return store


def vector_search(store: InMemoryEmbeddingStore | None = None, **kwargs: object) -> VectorSearch:
    return VectorSearch(embedder(), store or indexed_store(), CATALOG, MODEL, **kwargs)  # type: ignore[arg-type]


def codes(search: EquipmentSearch, query: str, category=None, limit: int = 5) -> list[str]:
    return [h.code for h in search.search([query], category, limit)[0].hits]


# --- VectorSearch ------------------------------------------------------------------------------


def test_it_satisfies_the_port() -> None:
    assert isinstance(vector_search(), EquipmentSearch)


def test_vector_search_finds_what_keywords_miss() -> None:
    keyword = KeywordSearch(CATALOG)

    assert "sound_speaker_15" not in codes(keyword, "amplificacion")
    assert "sound_speaker_15" in codes(vector_search(), "amplificacion")


def test_a_semantic_query_ranks_the_related_item_first() -> None:
    assert codes(vector_search(), "mezclar")[0] == "sound_mixer_16"


def test_hits_carry_similarity_and_no_keyword_score() -> None:
    (result,) = vector_search().search(["parlante"], None, 5)

    assert result.degraded is False
    assert [h.rank for h in result.hits] == list(range(1, len(result.hits) + 1))
    for hit in result.hits:
        assert 0 < hit.vector_similarity <= 1 and hit.keyword_score is None
    sims = [h.vector_similarity for h in result.hits]
    assert sims == sorted(sims, reverse=True)


def test_an_unrelated_query_returns_nothing_instead_of_nearest_neighbours() -> None:
    assert codes(vector_search(), "submarino nuclear atomico") == []


def test_the_minimum_similarity_is_configurable() -> None:
    assert codes(vector_search(min_similarity=0.99), "parlante potente grande") == []
    assert "sound_speaker_15" in codes(vector_search(min_similarity=0.05), "parlante")


@pytest.mark.parametrize("value", [-0.1, 1.1, True, "0.3", None])
def test_invalid_thresholds_are_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        vector_search(min_similarity=value)


def test_category_filter_applies_and_excludes_packages() -> None:
    result = codes(vector_search(min_similarity=0.0), "parlante", EquipmentCategory.SOUND, 10)

    assert result and all(c.startswith("sound_") for c in result)
    assert not any(c.startswith("pkg_") for c in result)


def test_the_limit_caps_the_hits() -> None:
    assert len(codes(vector_search(min_similarity=0.0), "parlante", limit=2)) == 2


def test_codes_that_left_the_catalog_are_dropped() -> None:
    store = indexed_store()
    smaller = Catalog(CATALOG.items[1:], ())  # drops sound_speaker_15 and every package

    found = codes(
        VectorSearch(embedder(), store, smaller, MODEL, min_similarity=0.0), "parlante", limit=10
    )

    assert "sound_speaker_15" not in found and not any(c.startswith("pkg_") for c in found)


def test_rows_of_another_model_are_never_returned() -> None:
    store = InMemoryEmbeddingStore()
    refresh_embeddings(CATALOG, embedder(), store, "other-model")

    assert codes(vector_search(store), "parlante") == []


def test_a_batch_uses_one_embedding_call() -> None:
    calls: list[int] = []

    class Spy:
        def embed(self, texts: Sequence[str], timeout_s: float = 10.0) -> EmbeddingResult:
            calls.append(len(texts))
            return embedder().embed(texts, timeout_s)

    search = VectorSearch(Spy(), indexed_store(), CATALOG, MODEL)
    results = search.search(["parlante", "luces", "humo"], None, 3)

    assert calls == [3] and len(results) == 3


@pytest.mark.parametrize("limit", [0, 11, True, None])
def test_invalid_arguments_are_rejected_before_any_call(limit: object) -> None:
    store = BrokenEmbeddingStore()

    with pytest.raises(InvalidSearch):
        VectorSearch(embedder(), store, CATALOG, MODEL).search(["luz"], None, limit)  # type: ignore[arg-type]


def test_provider_and_storage_failures_propagate_to_the_caller() -> None:
    class Down:
        def embed(self, texts: Sequence[str], timeout_s: float = 10.0) -> EmbeddingResult:
            raise LlmUnavailable()

    with pytest.raises(LlmUnavailable):
        VectorSearch(Down(), indexed_store(), CATALOG, MODEL).search(["luz"], None, 3)
    with pytest.raises(RepositoryUnavailable):
        VectorSearch(embedder(), BrokenEmbeddingStore(), CATALOG, MODEL).search(["luz"], None, 3)


# --- HybridSearch --------------------------------------------------------------------------------


def hybrid(vector: EquipmentSearch | None) -> HybridSearch:
    return HybridSearch(KeywordSearch(CATALOG), vector)


def test_without_a_vector_leg_it_is_the_keyword_search() -> None:
    keyword = KeywordSearch(CATALOG)

    assert hybrid(None).search(["parlante"], None, 5) == keyword.search(["parlante"], None, 5)


def test_fusion_brings_in_vector_only_hits() -> None:
    assert "sound_speaker_15" in codes(hybrid(vector_search()), "amplificacion")


def test_an_entry_found_by_both_legs_outranks_one_found_by_one() -> None:
    (result,) = hybrid(vector_search()).search(["microfono inalambrico"], None, 5)

    top = result.hits[0]
    assert top.code == "sound_wireless_mic"
    assert top.keyword_score is not None and top.vector_similarity is not None


def test_ranks_are_contiguous_and_the_limit_holds() -> None:
    (result,) = hybrid(vector_search(min_similarity=0.0)).search(["parlante luz"], None, 3)

    assert [h.rank for h in result.hits] == [1, 2, 3]


def test_the_fusion_score_is_reciprocal_rank_fusion() -> None:
    keyword, vector = KeywordSearch(CATALOG), vector_search(min_similarity=0.0)
    (k_res,) = keyword.search(["parlante"], None, 10)
    (v_res,) = vector.search(["parlante"], None, 10)
    expected: dict[str, float] = {}
    for result in (k_res, v_res):
        for hit in result.hits:
            expected[hit.code] = expected.get(hit.code, 0.0) + 1 / (RRF_K + hit.rank)

    (fused,) = hybrid(vector).search(["parlante"], None, 10)

    order = sorted(expected, key=lambda c: (-expected[c], c))
    assert [h.code for h in fused.hits] == order[: len(fused.hits)]
    assert RRF_K == 60


@pytest.mark.parametrize(
    "failure",
    [LlmUnavailable(), LlmRateLimited(retry_after_s=5)],
    ids=["unavailable", "rate-limited"],
)
def test_a_provider_failure_falls_back_to_keywords_with_the_same_shape(failure: Exception) -> None:
    class Down:
        def embed(self, texts: Sequence[str], timeout_s: float = 10.0) -> EmbeddingResult:
            raise failure

    search = hybrid(VectorSearch(Down(), indexed_store(), CATALOG, MODEL))

    (result,) = search.search(["luces"], None, 5)
    (plain,) = KeywordSearch(CATALOG).search(["luces"], None, 5)

    assert result.degraded is True
    assert result.hits == plain.hits


def test_a_storage_failure_falls_back_to_keywords() -> None:
    search = hybrid(VectorSearch(embedder(), BrokenEmbeddingStore(), CATALOG, MODEL))

    (result,) = search.search(["luces"], None, 5)

    assert result.degraded is True and result.hits


def test_invalid_arguments_are_not_swallowed_by_the_fallback() -> None:
    with pytest.raises(InvalidSearch):
        hybrid(vector_search()).search(["luz"], None, 0)


def test_unexpected_errors_are_not_swallowed_either() -> None:
    class Bug:
        def search(self, *args: object) -> None:
            raise KeyError("bug")

    with pytest.raises(KeyError):
        hybrid(Bug()).search(["luz"], None, 3)  # type: ignore[arg-type]


def test_a_batch_degrades_as_a_whole() -> None:
    search = hybrid(VectorSearch(embedder(), BrokenEmbeddingStore(), CATALOG, MODEL))

    results = search.search(["luces", "humo"], None, 3)

    assert [r.degraded for r in results] == [True, True]


def test_unrelated_queries_stay_empty_even_with_a_vector_leg() -> None:
    assert codes(hybrid(vector_search()), "submarino nuclear atomico") == []
