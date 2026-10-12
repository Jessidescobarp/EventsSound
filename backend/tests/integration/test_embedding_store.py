"""SqlAlchemyEmbeddingStore against a real pgvector Postgres."""

import math
import traceback

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from agent_fixtures import make_catalog
from conftest import SECRETS_IN_UNREACHABLE_URL
from eventssound.adapters.db.embedding_store import SqlAlchemyEmbeddingStore
from eventssound.adapters.db.models import EMBEDDING_DIMENSIONS
from eventssound.adapters.embeddings.fake import FakeEmbeddingProvider
from eventssound.adapters.search.vector import VectorSearch
from eventssound.application.embedding_index import (
    EmbeddingStore,
    StoredEmbedding,
    refresh_embeddings,
)
from eventssound.application.embeddings import EmbeddingDimensionMismatch
from eventssound.application.errors import ConnectionFailed, SchemaNotReady

HASH = "b" * 64
D = EMBEDDING_DIMENSIONS


def vec(*head: float) -> tuple[float, ...]:
    return (*head, *([0.0] * (D - len(head))))


def row(code: str, *head: float, kind: str = "item") -> StoredEmbedding:
    return StoredEmbedding(kind, code, HASH, vec(*head))  # type: ignore[arg-type]


@pytest.fixture
def store(session_factory: sessionmaker[Session]) -> SqlAlchemyEmbeddingStore:
    return SqlAlchemyEmbeddingStore(session_factory)


def count(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return session.execute(text("SELECT count(*) FROM catalog_embeddings")).scalar_one()


def test_it_satisfies_the_port(store: SqlAlchemyEmbeddingStore) -> None:
    assert isinstance(store, EmbeddingStore)


def test_upsert_inserts_then_updates_in_place(
    store: SqlAlchemyEmbeddingStore, session_factory: sessionmaker[Session]
) -> None:
    store.upsert("m", [row("abc", 1.0)])
    store.upsert("m", [StoredEmbedding("item", "abc", "c" * 64, vec(0.0, 1.0))])

    assert count(session_factory) == 1
    assert store.existing_hashes("m") == {("item", "abc"): "c" * 64}
    assert store.nearest("m", vec(0.0, 1.0), 5)[0].similarity == pytest.approx(1.0)


def test_updated_at_moves_on_update(
    store: SqlAlchemyEmbeddingStore, session_factory: sessionmaker[Session]
) -> None:
    store.upsert("m", [row("abc", 1.0)])
    with session_factory.begin() as session:
        session.execute(text("UPDATE catalog_embeddings SET updated_at = '2000-01-01'"))

    store.upsert("m", [row("abc", 1.0)])

    with session_factory() as session:
        year = session.execute(
            text("SELECT extract(year FROM updated_at) FROM catalog_embeddings")
        ).scalar_one()
    assert year > 2000


def test_the_same_code_can_exist_for_two_models_and_two_kinds(
    store: SqlAlchemyEmbeddingStore,
) -> None:
    store.upsert("m1", [row("abc", 1.0), row("abc", 1.0, kind="package")])
    store.upsert("m2", [row("abc", 1.0)])

    assert set(store.existing_hashes("m1")) == {("item", "abc"), ("package", "abc")}
    assert set(store.existing_hashes("m2")) == {("item", "abc")}
    assert store.existing_hashes("nope") == {}


def test_nearest_orders_by_cosine_similarity_and_ignores_magnitude(
    store: SqlAlchemyEmbeddingStore,
) -> None:
    store.upsert("m", [row("near", 1.0, 0.1), row("far", 0.0, 1.0), row("same", 5.0)])

    matches = store.nearest("m", vec(1.0), 10)

    assert [m.code for m in matches] == ["same", "near", "far"]
    assert matches[0].similarity == pytest.approx(1.0)
    assert matches[1].similarity == pytest.approx(1 / math.sqrt(1.01), rel=1e-5)
    assert matches[2].similarity == pytest.approx(0.0, abs=1e-6)


def test_similarity_is_clamped_to_zero_for_opposite_vectors(
    store: SqlAlchemyEmbeddingStore,
) -> None:
    store.upsert("m", [row("opposite", -1.0)])

    assert store.nearest("m", vec(1.0), 5)[0].similarity == 0.0


def test_ties_are_broken_by_kind_then_code(store: SqlAlchemyEmbeddingStore) -> None:
    store.upsert("m", [row("zzz", 1.0), row("aaa", 1.0), row("mmm", 1.0, kind="package")])

    matches = store.nearest("m", vec(1.0), 10)

    assert [(m.kind, m.code) for m in matches] == [
        ("item", "aaa"),
        ("item", "zzz"),
        ("package", "mmm"),
    ]


def test_nearest_respects_the_limit_and_the_model(store: SqlAlchemyEmbeddingStore) -> None:
    store.upsert("m", [row("aaa1", 1.0), row("aaa2", 1.0), row("aaa3", 1.0)])
    store.upsert("other", [row("bbb1", 1.0)])

    assert len(store.nearest("m", vec(1.0), 2)) == 2
    assert {m.code for m in store.nearest("m", vec(1.0), 10)} == {"aaa1", "aaa2", "aaa3"}


def test_nearest_on_an_empty_table_is_empty(store: SqlAlchemyEmbeddingStore) -> None:
    assert store.nearest("m", vec(1.0), 5) == ()


def test_prune_keeps_only_the_listed_rows_of_the_active_model(
    store: SqlAlchemyEmbeddingStore, session_factory: sessionmaker[Session]
) -> None:
    store.upsert("m", [row("keep", 1.0), row("drop", 1.0), row("pkg1", 1.0, kind="package")])
    store.upsert("old", [row("keep", 1.0)])

    deleted = store.prune("m", {("item", "keep"), ("package", "pkg1")})

    assert deleted == 2  # "drop" of m and "keep" of old
    assert set(store.existing_hashes("m")) == {("item", "keep"), ("package", "pkg1")}
    assert store.existing_hashes("old") == {}
    assert count(session_factory) == 2


def test_prune_with_an_empty_keep_set_clears_everything(
    store: SqlAlchemyEmbeddingStore, session_factory: sessionmaker[Session]
) -> None:
    store.upsert("m", [row("aaa1", 1.0), row("aaa2", 1.0)])

    assert store.prune("m", set()) == 2
    assert count(session_factory) == 0


def test_a_wrong_sized_query_vector_is_a_dimension_mismatch(
    store: SqlAlchemyEmbeddingStore,
) -> None:
    with pytest.raises(EmbeddingDimensionMismatch):
        store.nearest("m", (1.0, 0.0, 0.0), 5)


def test_a_wrong_sized_stored_vector_is_a_dimension_mismatch(
    store: SqlAlchemyEmbeddingStore,
) -> None:
    with pytest.raises(EmbeddingDimensionMismatch):
        store.upsert("m", [StoredEmbedding("item", "abc", HASH, (1.0, 0.0))])


def test_a_zero_query_vector_is_refused_before_reaching_the_database(
    store: SqlAlchemyEmbeddingStore,
) -> None:
    with pytest.raises(EmbeddingDimensionMismatch):
        store.nearest("m", vec(), 5)


def test_a_failed_upsert_batch_writes_nothing(
    store: SqlAlchemyEmbeddingStore, session_factory: sessionmaker[Session]
) -> None:
    with pytest.raises(EmbeddingDimensionMismatch):
        store.upsert("m", [row("good", 1.0), StoredEmbedding("item", "bad", HASH, (1.0,))])

    assert count(session_factory) == 0


def test_a_missing_table_is_schema_not_ready(database_url: str) -> None:
    from conftest import reset_schema
    from eventssound.adapters.db.session import build_engine, build_session_factory

    reset_schema(database_url)
    engine = build_engine(database_url)
    try:
        with pytest.raises(SchemaNotReady):
            SqlAlchemyEmbeddingStore(build_session_factory(engine)).existing_hashes("m")
    finally:
        engine.dispose()


def test_an_unreachable_database_leaks_nothing(unreachable_session_factory: sessionmaker) -> None:
    store = SqlAlchemyEmbeddingStore(unreachable_session_factory)

    with pytest.raises(ConnectionFailed) as caught:
        store.nearest("m", vec(1.0), 5)

    rendered = str(caught.value) + "".join(traceback.format_exception(caught.value))
    assert not any(secret in rendered for secret in SECRETS_IN_UNREACHABLE_URL)


def test_end_to_end_refresh_and_vector_search_on_postgres(
    store: SqlAlchemyEmbeddingStore,
) -> None:
    catalog = make_catalog()
    embedder = FakeEmbeddingProvider(
        dimensions=D, model="fake", aliases={"amplificacion": "parlante"}
    )

    first = refresh_embeddings(catalog, embedder, store, "fake")
    second = refresh_embeddings(catalog, embedder, store, "fake")
    found = VectorSearch(embedder, store, catalog, "fake").search(["amplificacion"], None, 3)[0]

    assert first.embedded == 8 and second.embedded == 0 and second.skipped == 8
    assert "sound_speaker_15" in [h.code for h in found.hits]
