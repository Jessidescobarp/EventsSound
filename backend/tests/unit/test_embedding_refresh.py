"""refresh_embeddings: idempotent, batched, deletes orphans, one active model."""

import hashlib
import math
from collections.abc import Sequence

import pytest

from agent_fixtures import make_catalog
from eventssound.adapters.embeddings.fake import FakeEmbeddingProvider
from eventssound.application.embedding_index import (
    EmbeddingStore,
    RefreshResult,
    StoredEmbedding,
    VectorMatch,
    content_hash,
    embedding_text,
    refresh_embeddings,
)
from eventssound.application.embeddings import EmbeddingResult
from eventssound.application.errors import RepositoryUnavailable
from eventssound.application.llm import LlmBadResponse, LlmUnavailable
from eventssound.domain.catalog import Catalog, EquipmentCategory, EquipmentItem
from eventssound.domain.money import Money
from fakes import BrokenEmbeddingStore, InMemoryEmbeddingStore

CATALOG = make_catalog()
ENTRIES = len(CATALOG.items) + len(CATALOG.packages)
MODEL = "fake-embedding"


class CountingEmbedder:
    def __init__(self, inner: FakeEmbeddingProvider | None = None) -> None:
        self.inner = inner or FakeEmbeddingProvider(dimensions=32, model=MODEL)
        self.batches: list[int] = []

    def embed(self, texts: Sequence[str], timeout_s: float = 10.0) -> EmbeddingResult:
        self.batches.append(len(texts))
        return self.inner.embed(texts, timeout_s)


def test_the_fakes_satisfy_the_port() -> None:
    assert isinstance(InMemoryEmbeddingStore(), EmbeddingStore)
    assert isinstance(BrokenEmbeddingStore(), EmbeddingStore)


def test_texts_are_spanish_and_deterministic() -> None:
    speaker = CATALOG.item("sound_speaker_15")
    package = CATALOG.package("pkg_dj")

    assert embedding_text(speaker, CATALOG) == "Parlante activo de 15 pulgadas. Categoria: sonido."
    assert embedding_text(package, CATALOG) == (
        "Paquete DJ. Incluye: Controlador DJ de 4 canales, Parlante activo de 15 pulgadas."
    )


def test_the_hash_depends_on_the_model_and_the_text() -> None:
    expected = hashlib.sha256(b"m1\nhola").hexdigest()

    assert content_hash("m1", "hola") == expected
    assert content_hash("m2", "hola") != expected
    assert content_hash("m1", "hola!") != expected
    assert len(expected) == 64


def test_the_first_run_embeds_everything_in_batches() -> None:
    embedder, store = CountingEmbedder(), InMemoryEmbeddingStore()

    result = refresh_embeddings(CATALOG, embedder, store, MODEL, batch_size=3)

    assert result == RefreshResult(embedded=ENTRIES, skipped=0, deleted=0)
    assert embedder.batches == [3, 3, 2]
    assert len(store.rows) == ENTRIES
    assert {(k, c) for (k, c, _m) in store.rows} == {
        *(("item", i.code) for i in CATALOG.items),
        *(("package", p.code) for p in CATALOG.packages),
    }


def test_a_second_run_on_unchanged_data_embeds_nothing() -> None:
    store = InMemoryEmbeddingStore()
    refresh_embeddings(CATALOG, CountingEmbedder(), store, MODEL)
    embedder = CountingEmbedder()

    result = refresh_embeddings(CATALOG, embedder, store, MODEL)

    assert result == RefreshResult(embedded=0, skipped=ENTRIES, deleted=0)
    assert embedder.batches == []


def test_only_changed_entries_are_re_embedded() -> None:
    store = InMemoryEmbeddingStore()
    refresh_embeddings(CATALOG, CountingEmbedder(), store, MODEL)
    renamed = EquipmentItem(
        "light_led_par", "Luz LED PAR de 18 watts", EquipmentCategory.LIGHTING, 24, Money(25_000)
    )
    items = tuple(renamed if i.code == renamed.code else i for i in CATALOG.items)
    # package pkg_party includes the renamed item, so its text changes too
    changed = Catalog(items, CATALOG.packages)
    embedder = CountingEmbedder()

    result = refresh_embeddings(changed, embedder, store, MODEL)

    assert result == RefreshResult(embedded=2, skipped=ENTRIES - 2, deleted=0)
    assert embedder.batches == [2]


def test_a_price_or_stock_change_does_not_re_embed() -> None:
    store = InMemoryEmbeddingStore()
    refresh_embeddings(CATALOG, CountingEmbedder(), store, MODEL)
    cheaper = EquipmentItem(
        "light_led_par", "Luz LED PAR RGB", EquipmentCategory.LIGHTING, 99, Money(1)
    )
    items = tuple(cheaper if i.code == cheaper.code else i for i in CATALOG.items)

    result = refresh_embeddings(Catalog(items, CATALOG.packages), CountingEmbedder(), store, MODEL)

    assert result.embedded == 0


def test_entries_that_left_the_catalog_are_deleted() -> None:
    store = InMemoryEmbeddingStore()
    refresh_embeddings(CATALOG, CountingEmbedder(), store, MODEL)
    smaller = Catalog(CATALOG.items, CATALOG.packages[:1])

    result = refresh_embeddings(smaller, CountingEmbedder(), store, MODEL)

    assert result == RefreshResult(embedded=0, skipped=ENTRIES - 1, deleted=1)
    assert ("package", "pkg_dj", MODEL) not in store.rows


def test_rows_of_another_model_are_deleted_so_only_one_model_is_active() -> None:
    store = InMemoryEmbeddingStore()
    refresh_embeddings(CATALOG, CountingEmbedder(), store, "old-model")

    result = refresh_embeddings(CATALOG, CountingEmbedder(), store, MODEL)

    assert result.deleted == ENTRIES and result.embedded == ENTRIES
    assert {m for (_k, _c, m) in store.rows} == {MODEL}


def test_an_empty_catalog_clears_the_store_without_calling_the_provider() -> None:
    store = InMemoryEmbeddingStore()
    refresh_embeddings(CATALOG, CountingEmbedder(), store, MODEL)
    embedder = CountingEmbedder()

    result = refresh_embeddings(Catalog((), ()), embedder, store, MODEL)

    assert result == RefreshResult(embedded=0, skipped=0, deleted=ENTRIES)
    assert embedder.batches == [] and store.rows == {}


def test_a_provider_failure_writes_nothing_and_propagates() -> None:
    class Failing:
        def embed(self, texts: Sequence[str], timeout_s: float = 10.0) -> EmbeddingResult:
            raise LlmUnavailable()

    store = InMemoryEmbeddingStore()

    with pytest.raises(LlmUnavailable):
        refresh_embeddings(CATALOG, Failing(), store, MODEL)

    assert store.rows == {}


def test_a_partial_failure_keeps_the_batches_already_stored_and_a_rerun_finishes() -> None:
    class FailsSecondBatch(CountingEmbedder):
        def embed(self, texts: Sequence[str], timeout_s: float = 10.0) -> EmbeddingResult:
            if len(self.batches) == 1:
                raise LlmUnavailable()
            return super().embed(texts, timeout_s)

    store = InMemoryEmbeddingStore()
    with pytest.raises(LlmUnavailable):
        refresh_embeddings(CATALOG, FailsSecondBatch(), store, MODEL, batch_size=3)
    assert len(store.rows) == 3

    result = refresh_embeddings(CATALOG, CountingEmbedder(), store, MODEL, batch_size=3)

    assert result == RefreshResult(embedded=ENTRIES - 3, skipped=3, deleted=0)


def test_a_provider_returning_the_wrong_number_of_vectors_is_rejected() -> None:
    class Short:
        def embed(self, texts: Sequence[str], timeout_s: float = 10.0) -> EmbeddingResult:
            return FakeEmbeddingProvider(dimensions=32).embed(list(texts)[:-1] or ["x"])

    store = InMemoryEmbeddingStore()

    with pytest.raises(LlmBadResponse):
        refresh_embeddings(CATALOG, Short(), store, MODEL)

    assert store.rows == {}


def test_a_broken_store_propagates_repository_unavailable() -> None:
    with pytest.raises(RepositoryUnavailable):
        refresh_embeddings(CATALOG, CountingEmbedder(), BrokenEmbeddingStore(), MODEL)


@pytest.mark.parametrize("batch_size", [0, -1, 65, True, 1.5, None])
def test_invalid_batch_sizes_are_rejected(batch_size: object) -> None:
    with pytest.raises(ValueError):
        refresh_embeddings(CATALOG, CountingEmbedder(), InMemoryEmbeddingStore(), MODEL, batch_size)  # type: ignore[arg-type]


@pytest.mark.parametrize("model", ["", "  ", "x" * 121, None, 5])
def test_invalid_model_names_are_rejected(model: object) -> None:
    with pytest.raises(ValueError):
        refresh_embeddings(CATALOG, CountingEmbedder(), InMemoryEmbeddingStore(), model)  # type: ignore[arg-type]


def test_stored_values_are_validated() -> None:
    vector = (1.0, 0.0)
    assert StoredEmbedding("item", "abc", "a" * 64, vector).vector == vector
    for kwargs in (
        {"kind": "bundle"},
        {"code": "UPPER"},
        {"content_hash": "short"},
        {"vector": ()},
        {"vector": (math.nan,)},
    ):
        values = {"kind": "item", "code": "abc", "content_hash": "a" * 64, "vector": vector}
        with pytest.raises(ValueError):
            StoredEmbedding(**(values | kwargs))  # type: ignore[arg-type]
    assert VectorMatch("item", "abc", 0.5).similarity == 0.5
