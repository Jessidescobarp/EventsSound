"""Persistent daily LLM usage (the money cap survives restarts). Schema only, no data.

Revision ID: 0004
Revises: 0003

A plain CREATE TABLE of a new empty table: it takes no lock on existing data, so it is safe to
run on every deploy. Names are literal so this revision stays frozen history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_daily",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("cost_micro_usd", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("day", name=op.f("pk_llm_usage_daily")),
        sa.CheckConstraint("tokens >= 0", name=op.f("ck_llm_usage_daily_tokens_non_negative")),
        sa.CheckConstraint(
            "cost_micro_usd >= 0", name=op.f("ck_llm_usage_daily_cost_non_negative")
        ),
    )


def downgrade() -> None:
    op.drop_table("llm_usage_daily")
