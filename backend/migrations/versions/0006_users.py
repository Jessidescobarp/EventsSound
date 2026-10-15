"""Users for login: email, role and an argon2id password hash. Schema only, no data.

Revision ID: 0006
Revises: 0005

A plain CREATE TABLE of a new empty table (no lock on existing data). `id` is a UUID so the
public id never exposes row counts. Names are literal so this revision stays frozen history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.CheckConstraint("role IN ('client', 'admin')", name=op.f("ck_users_role_valid")),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lower")),
    )


def downgrade() -> None:
    op.drop_table("users")
