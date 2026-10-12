"""Catalog embeddings for vector retrieval (pgvector). Schema only, no data.

Revision ID: 0003
Revises: 0002

Names, the kind list and the vector size are literal so this revision stays frozen history. The
extension is created with IF NOT EXISTS and is deliberately NOT dropped on downgrade: other
objects may use it, and managed hosts restrict who may create it. Embeddings are produced
manually by the embed_catalog CLI, never by this migration. No index: the table holds a few dozen
rows, where a sequential scan beats HNSW; add one in a later revision if the catalog grows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.types import UserDefinedType

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class _Vector1024(UserDefinedType):
    """The column type, spelled out here so the revision never imports application code."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "vector(1024)"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "catalog_embeddings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", _Vector1024(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_embeddings")),
        sa.UniqueConstraint(
            "kind", "code", "model", name=op.f("uq_catalog_embeddings_kind_code_model")
        ),
        sa.CheckConstraint(
            "kind IN ('item', 'package')", name=op.f("ck_catalog_embeddings_kind_valid")
        ),
    )


def downgrade() -> None:
    op.drop_table("catalog_embeddings")
