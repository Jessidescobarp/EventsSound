"""Security events for runtime abuse detection.

Revision ID: 0009
Revises: 0008

One row per signal (refused chat message, rate limit hit, failed login, blocked request). It holds
a kind, a time and a hashed client key: no address, email, password or message text.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("client", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_events")),
    )
    op.create_index(
        "ix_security_events_kind_client_at", "security_events", ["kind", "client", "at"]
    )
    op.create_index("ix_security_events_at", "security_events", ["at"])


def downgrade() -> None:
    op.drop_table("security_events")
