"""Versioned agent configuration and its audit trail.

Revision ID: 0010
Revises: 0009

`agent_settings` is append-only: one row per saved version, the highest version is the active one.
`config` holds behavior and limits only (never a provider or a key). `agent_settings_audit` keeps
who changed what: a diff of old and new values, no secrets.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_settings",
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("version", name=op.f("pk_agent_settings")),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_agent_settings_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_agent_settings_version_positive")),
        sa.CheckConstraint("char_length(note) <= 200", name=op.f("ck_agent_settings_note_length")),
    )
    op.create_table(
        "agent_settings_audit",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("diff", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_settings_audit")),
        sa.ForeignKeyConstraint(
            ["version"],
            ["agent_settings.version"],
            name=op.f("fk_agent_settings_audit_version_agent_settings"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_agent_settings_audit_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "action IN ('save', 'rollback')", name=op.f("ck_agent_settings_audit_action_valid")
        ),
    )
    op.create_index("ix_agent_settings_audit_version", "agent_settings_audit", ["version"])


def downgrade() -> None:
    op.drop_table("agent_settings_audit")
    op.drop_table("agent_settings")
