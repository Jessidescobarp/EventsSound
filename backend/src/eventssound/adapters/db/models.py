"""SQLAlchemy models for the catalog and bookings.

Money is stored as whole pesos in `*_cop` BIGINT columns (ADR 12); `*_bps` columns are basis
points. `category` and `status` are VARCHAR + CHECK rather than native ENUM types, so changing the
allowed values is a normal migration. The CHECK value lists are literal on purpose: a migration is
frozen history and must not follow later changes to the domain enums by accident.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base
from .vector import VectorType

CATEGORIES = "('sound', 'lighting', 'dj', 'stage', 'effects', 'video', 'staff')"
BOOKING_STATUSES = "('pending', 'confirmed', 'cancelled')"
EMBEDDING_KINDS = "('item', 'package')"
# Frozen in migration 0003: a different size is a new revision plus a full refresh.
EMBEDDING_DIMENSIONS = 1024


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EquipmentItemModel(TimestampMixin, Base):
    __tablename__ = "equipment_items"
    __table_args__ = (
        CheckConstraint(f"category IN {CATEGORIES}", name="category_valid"),
        CheckConstraint("stock_quantity >= 0", name="stock_nonnegative"),
        CheckConstraint("unit_price_cop >= 0", name="unit_price_nonnegative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(16))
    stock_quantity: Mapped[int] = mapped_column(Integer)
    unit_price_cop: Mapped[int] = mapped_column(BigInteger)


class ServicePackageModel(TimestampMixin, Base):
    __tablename__ = "service_packages"
    __table_args__ = (CheckConstraint("discount_bps BETWEEN 0 AND 10000", name="discount_range"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    discount_bps: Mapped[int] = mapped_column(Integer, server_default="0")

    lines: Mapped[list["PackageItemModel"]] = relationship(
        back_populates="package", cascade="all, delete-orphan", passive_deletes=True
    )


class PackageItemModel(Base):
    __tablename__ = "package_items"
    __table_args__ = (
        UniqueConstraint(
            "package_id",
            "equipment_item_id",
            name="uq_package_items_package_id_equipment_item_id",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    package_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_packages.id", ondelete="CASCADE")
    )
    equipment_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("equipment_items.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer)

    package: Mapped[ServicePackageModel] = relationship(back_populates="lines")
    item: Mapped[EquipmentItemModel] = relationship()


class BookingModel(TimestampMixin, Base):
    """One row per equipment item per booking (flat table, no header)."""

    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("booking_code", "item_code", name="uq_bookings_booking_code_item_code"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("ends_at > starts_at", name="ends_after_starts"),
        CheckConstraint(f"status IN {BOOKING_STATUSES}", name="status_valid"),
        Index("ix_bookings_item_code", "item_code", "starts_at", "ends_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    booking_code: Mapped[str] = mapped_column(String(64))
    item_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("equipment_items.code", ondelete="RESTRICT")
    )
    quantity: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")


class CatalogEmbeddingModel(TimestampMixin, Base):
    """One embedding per catalog entry and model. `code` is polymorphic (item or package), so
    there is no foreign key; readers drop codes that left the catalog and refresh deletes them."""

    __tablename__ = "catalog_embeddings"
    __table_args__ = (
        UniqueConstraint("kind", "code", "model", name="uq_catalog_embeddings_kind_code_model"),
        CheckConstraint(f"kind IN {EMBEDDING_KINDS}", name="kind_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(120))
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[tuple[float, ...]] = mapped_column(VectorType(EMBEDDING_DIMENSIONS))


class LlmUsageDailyModel(Base):
    """Reserved plus settled LLM usage per UTC day (the persistent daily money cap).

    Caps are not stored: they come from Settings, so changing a cap needs no migration.
    """

    __tablename__ = "llm_usage_daily"
    __table_args__ = (
        CheckConstraint("tokens >= 0", name="tokens_non_negative"),
        CheckConstraint("cost_micro_usd >= 0", name="cost_non_negative"),
    )

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
