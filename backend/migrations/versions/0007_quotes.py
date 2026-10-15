"""Saved quotes: the validated quote and event fields, optionally tied to a user.

Revision ID: 0007
Revises: 0006

A plain CREATE TABLE of a new empty table (no lock on existing data). No message text, reply,
address, name or email is stored. Names are literal so this revision stays frozen history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quotes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("event_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("guest_count", sa.Integer(), nullable=False),
        sa.Column("total_cop", sa.BigInteger(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=True),
        sa.Column("quote", postgresql.JSONB(), nullable=False),
        sa.Column("event_request", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quotes")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_quotes_user_id_users"), ondelete="SET NULL"
        ),
        sa.CheckConstraint("total_cop >= 0", name=op.f("ck_quotes_total_non_negative")),
        sa.CheckConstraint("guest_count > 0", name=op.f("ck_quotes_guests_positive")),
        sa.CheckConstraint("event_end > event_start", name=op.f("ck_quotes_ends_after_starts")),
    )
    op.create_index("ix_quotes_created_at_id", "quotes", ["created_at", "id"])
    op.create_index("ix_quotes_user_id", "quotes", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_quotes_user_id", table_name="quotes")
    op.drop_index("ix_quotes_created_at_id", table_name="quotes")
    op.drop_table("quotes")
