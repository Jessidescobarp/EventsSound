"""pgvector-backed EmbeddingStore. Driver errors become generic application errors."""

from collections.abc import Collection, Sequence

from sqlalchemy import delete, func, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DataError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.db.models import EMBEDDING_DIMENSIONS, CatalogEmbeddingModel
from eventssound.adapters.db.storage import storage_error
from eventssound.adapters.db.vector import format_vector
from eventssound.application.embedding_index import StoredEmbedding, VectorMatch
from eventssound.application.embeddings import EmbeddingDimensionMismatch

_NEAREST = text(
    "SELECT kind, code, 1 - (embedding <=> CAST(:query AS vector)) AS similarity"
    " FROM catalog_embeddings WHERE model = :model"
    " ORDER BY embedding <=> CAST(:query AS vector), kind, code LIMIT :limit"
)


class SqlAlchemyEmbeddingStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def existing_hashes(self, model: str) -> dict[tuple[str, str], str]:
        statement = select(
            CatalogEmbeddingModel.kind,
            CatalogEmbeddingModel.code,
            CatalogEmbeddingModel.content_hash,
        ).where(CatalogEmbeddingModel.model == model)
        try:
            with self._session_factory() as session:
                return {(kind, code): digest for kind, code, digest in session.execute(statement)}
        except SQLAlchemyError as exc:
            raise storage_error(exc) from None

    def upsert(self, model: str, rows: Sequence[StoredEmbedding]) -> None:
        if not rows:
            return
        values = [self._values(model, row) for row in rows]  # validates every row before writing
        statement = insert(CatalogEmbeddingModel).values(values)
        statement = statement.on_conflict_do_update(
            constraint="uq_catalog_embeddings_kind_code_model",
            set_={
                "content_hash": statement.excluded.content_hash,
                "embedding": statement.excluded.embedding,
                "updated_at": func.now(),
            },
        )
        try:
            with self._session_factory.begin() as session:
                session.execute(statement)
        except DataError:
            raise EmbeddingDimensionMismatch() from None
        except SQLAlchemyError as exc:
            raise storage_error(exc) from None

    def prune(self, model: str, keep: Collection[tuple[str, str]]) -> int:
        stale = CatalogEmbeddingModel.model != model
        if keep:
            key = tuple_(CatalogEmbeddingModel.kind, CatalogEmbeddingModel.code)
            stale = stale | key.not_in(list(keep))
        else:
            stale = stale | (CatalogEmbeddingModel.model == model)
        try:
            with self._session_factory.begin() as session:
                return session.execute(delete(CatalogEmbeddingModel).where(stale)).rowcount
        except SQLAlchemyError as exc:
            raise storage_error(exc) from None

    def nearest(self, model: str, vector: Sequence[float], limit: int) -> tuple[VectorMatch, ...]:
        try:
            literal = format_vector(vector, EMBEDDING_DIMENSIONS)
        except ValueError:
            raise EmbeddingDimensionMismatch() from None
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    _NEAREST, {"query": literal, "model": model, "limit": limit}
                ).all()
        except DataError:
            raise EmbeddingDimensionMismatch() from None
        except SQLAlchemyError as exc:
            raise storage_error(exc) from None
        return tuple(
            VectorMatch(kind, code, min(1.0, max(0.0, float(similarity))))
            for kind, code, similarity in rows
        )

    @staticmethod
    def _values(model: str, row: StoredEmbedding) -> dict[str, object]:
        try:
            format_vector(row.vector, EMBEDDING_DIMENSIONS)
        except ValueError:
            raise EmbeddingDimensionMismatch() from None
        return {
            "kind": row.kind,
            "code": row.code,
            "model": model,
            "content_hash": row.content_hash,
            "embedding": row.vector,
        }
