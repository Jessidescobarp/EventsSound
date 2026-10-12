"""Catalog tables and the flat bookings table. Schema only, no data.

Revision ID: 0002
Revises: 0001

Names are literal (`op.f`) so this revision stays frozen history even if the naming convention or
the models change later. The category and status value lists are literal for the same reason.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "equipment_items",
        _id(),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("stock_quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_cop", sa.BigInteger(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equipment_items")),
        sa.UniqueConstraint("code", name=op.f("uq_equipment_items_code")),
        sa.CheckConstraint(
            "category IN ('sound', 'lighting', 'dj', 'stage', 'effects', 'video')",
            name=op.f("ck_equipment_items_category_valid"),
        ),
        sa.CheckConstraint(
            "stock_quantity >= 0", name=op.f("ck_equipment_items_stock_nonnegative")
        ),
        sa.CheckConstraint(
            "unit_price_cop >= 0", name=op.f("ck_equipment_items_unit_price_nonnegative")
        ),
    )
    op.create_table(
        "service_packages",
        _id(),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("discount_bps", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_packages")),
        sa.UniqueConstraint("code", name=op.f("uq_service_packages_code")),
        sa.CheckConstraint(
            "discount_bps BETWEEN 0 AND 10000", name=op.f("ck_service_packages_discount_range")
        ),
    )
    op.create_table(
        "package_items",
        _id(),
        sa.Column("package_id", sa.BigInteger(), nullable=False),
        sa.Column("equipment_item_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_package_items")),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["service_packages.id"],
            name=op.f("fk_package_items_package_id_service_packages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["equipment_item_id"],
            ["equipment_items.id"],
            name=op.f("fk_package_items_equipment_item_id_equipment_items"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "package_id",
            "equipment_item_id",
            name=op.f("uq_package_items_package_id_equipment_item_id"),
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_package_items_quantity_positive")),
    )
    op.create_index(
        op.f("ix_package_items_equipment_item_id"), "package_items", ["equipment_item_id"]
    )
    op.create_table(
        "bookings",
        _id(),
        sa.Column("booking_code", sa.String(64), nullable=False),
        sa.Column("item_code", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bookings")),
        sa.ForeignKeyConstraint(
            ["item_code"],
            ["equipment_items.code"],
            name=op.f("fk_bookings_item_code_equipment_items"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "booking_code", "item_code", name=op.f("uq_bookings_booking_code_item_code")
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_bookings_quantity_positive")),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_bookings_ends_after_starts")),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled')", name=op.f("ck_bookings_status_valid")
        ),
    )
    op.create_index(
        op.f("ix_bookings_item_code"), "bookings", ["item_code", "starts_at", "ends_at"]
    )


def downgrade() -> None:
    # Reverse dependency order: bookings and package_items reference equipment_items.
    op.drop_index(op.f("ix_bookings_item_code"), table_name="bookings")
    op.drop_table("bookings")
    op.drop_index(op.f("ix_package_items_equipment_item_id"), table_name="package_items")
    op.drop_table("package_items")
    op.drop_table("service_packages")
    op.drop_table("equipment_items")
