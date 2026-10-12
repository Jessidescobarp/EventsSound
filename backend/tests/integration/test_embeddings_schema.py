"""Migration 0003: the catalog_embeddings table, the vector extension and the model drift."""

from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import DataError, IntegrityError

from eventssound.adapters.db.models import EMBEDDING_DIMENSIONS, CatalogEmbeddingModel
from eventssound.adapters.db.vector import format_vector
from eventssound.config import Settings

HASH = "a" * 64


def unit_vector(position: int = 0, dimensions: int = EMBEDDING_DIMENSIONS) -> str:
    values = [0.0] * dimensions
    values[position] = 1.0
    return format_vector(values, dimensions)


@pytest.fixture
def engine(migrated_database: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database)
    yield engine
    engine.dispose()


def insert(engine: Engine, **overrides: Any) -> None:
    values = {
        "kind": "item",
        "code": "sound_speaker",
        "model": "m1",
        "hash": HASH,
        "vec": unit_vector(),
    } | overrides
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO catalog_embeddings (kind, code, model, content_hash, embedding)"
                " VALUES (:kind, :code, :model, :hash, CAST(:vec AS vector))"
            ),
            values,
        )


def test_the_extension_and_the_table_exist_after_upgrade(engine: Engine) -> None:
    with engine.connect() as connection:
        extension = connection.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
        column = connection.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute"
                " WHERE attrelid = 'catalog_embeddings'::regclass AND attname = 'embedding'"
            )
        ).scalar_one()

    assert extension == "vector"
    assert column == f"vector({EMBEDDING_DIMENSIONS})"


def test_the_migration_does_not_insert_any_row(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM catalog_embeddings")).scalar() == 0


def test_the_model_dimension_equals_the_migration_literal() -> None:
    from pathlib import Path

    migration = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    source = next(migration.glob("0003_*.py")).read_text(encoding="utf-8")

    assert f"vector({EMBEDDING_DIMENSIONS})" in source


def test_the_settings_default_dimension_equals_the_column(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMBEDDING_DIMENSIONS", raising=False)
    settings = Settings(_env_file=None, DATABASE_URL="postgresql://u:p@127.0.0.1:1/x")  # type: ignore[call-arg]

    assert settings.embedding_dimensions == EMBEDDING_DIMENSIONS


def test_downgrade_drops_the_table_and_keeps_the_extension(
    alembic_config: Config, engine: Engine
) -> None:
    command.downgrade(alembic_config, "0002")

    assert "catalog_embeddings" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        extension = connection.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
    assert extension == "vector"


def test_upgrade_is_repeatable_when_the_extension_already_exists(
    alembic_config: Config, engine: Engine
) -> None:
    command.downgrade(alembic_config, "0002")
    command.upgrade(alembic_config, "head")

    assert "catalog_embeddings" in inspect(engine).get_table_names()


def test_the_vector_column_round_trips_through_the_orm_type(engine: Engine) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        session.add(
            CatalogEmbeddingModel(
                kind="item",
                code="abc",
                model="m",
                content_hash=HASH,
                embedding=tuple([0.5] + [0.0] * (EMBEDDING_DIMENSIONS - 1)),
            )  # fmt: skip
        )
        session.commit()
        stored = session.scalars(select(CatalogEmbeddingModel)).one()

    assert stored.embedding[0] == 0.5 and len(stored.embedding) == EMBEDDING_DIMENSIONS


def test_kind_code_model_is_unique_but_another_model_may_repeat_the_code(engine: Engine) -> None:
    insert(engine)
    insert(engine, model="m2")

    with pytest.raises(IntegrityError):
        insert(engine)


@pytest.mark.parametrize("kind", ["bundle", "", "ITEM"])
def test_kind_is_restricted(engine: Engine, kind: str) -> None:
    with pytest.raises(IntegrityError):
        insert(engine, kind=kind)


def test_a_vector_of_another_size_is_rejected_by_postgres(engine: Engine) -> None:
    with pytest.raises(DataError):
        insert(engine, vec=unit_vector(0, 3))


def test_an_embedding_is_required(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO catalog_embeddings (kind, code, model, content_hash)"
                " VALUES ('item', 'x', 'm', :h)"
            ),
            {"h": HASH},
        )


def test_audit_columns_default_to_now(engine: Engine) -> None:
    insert(engine)

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT created_at, updated_at FROM catalog_embeddings")
        ).one()

    assert row.created_at is not None and row.updated_at is not None
