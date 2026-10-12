"""Idempotent upsert of catalog definitions (and demo bookings) keyed by stable codes.

Rows are matched by `code` (items, packages) or `(booking_code, item_code)` (bookings): existing
rows are updated to the definition, missing ones are inserted, and nothing outside the definition
is ever deleted, except the stale lines of a seeded package so that editing a package converges.
The whole run is one transaction.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.domain.availability import Booking
from eventssound.domain.catalog import Catalog, EquipmentItem, ServicePackage
from eventssound.domain.errors import InvalidCatalog

from .models import BookingModel, EquipmentItemModel, PackageItemModel, ServicePackageModel
from .storage import storage_error


@dataclass(frozen=True, slots=True)
class SeedResult:
    """How many definitions were upserted (not how many rows changed)."""

    items: int
    packages: int
    bookings: int


def _collect[T](values: Iterable[T], kind: type[T], name: str) -> tuple[T, ...]:
    if isinstance(values, str | bytes):
        raise InvalidCatalog(f"{name} must be a collection of {kind.__name__}")
    try:
        collected = tuple(values)
    except TypeError:
        raise InvalidCatalog(f"{name} must be a collection of {kind.__name__}") from None
    if not all(isinstance(value, kind) for value in collected):
        raise InvalidCatalog(f"{name} must contain only {kind.__name__} values")
    return collected


def _ids(session: Session, model: type[EquipmentItemModel] | type[ServicePackageModel]):
    return {code: id_ for code, id_ in session.execute(select(model.code, model.id))}


def _upsert_items(session: Session, items: tuple[EquipmentItem, ...]) -> None:
    if not items:
        return
    statement = insert(EquipmentItemModel).values(
        [
            {
                "code": item.code,
                "name": item.name,
                "category": item.category.value,
                "stock_quantity": item.stock_quantity,
                "unit_price_cop": item.unit_price.amount,
            }
            for item in items
        ]
    )
    columns = ("name", "category", "stock_quantity", "unit_price_cop")
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["code"],
            set_={**{c: statement.excluded[c] for c in columns}, "updated_at": func.now()},
        )
    )


def _upsert_packages(session: Session, packages: tuple[ServicePackage, ...]) -> None:
    if not packages:
        return
    statement = insert(ServicePackageModel).values(
        [{"code": p.code, "name": p.name, "discount_bps": p.discount_bps} for p in packages]
    )
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["code"],
            set_={
                "name": statement.excluded.name,
                "discount_bps": statement.excluded.discount_bps,
                "updated_at": func.now(),
            },
        )
    )
    item_ids, package_ids = _ids(session, EquipmentItemModel), _ids(session, ServicePackageModel)
    lines = insert(PackageItemModel).values(
        [
            {
                "package_id": package_ids[package.code],
                "equipment_item_id": item_ids[line.item_code],
                "quantity": line.quantity,
            }
            for package in packages
            for line in package.lines
        ]
    )
    session.execute(
        lines.on_conflict_do_update(
            index_elements=["package_id", "equipment_item_id"],
            set_={"quantity": lines.excluded.quantity},
        )
    )
    for package in packages:
        wanted = [item_ids[line.item_code] for line in package.lines]
        session.execute(
            delete(PackageItemModel).where(
                PackageItemModel.package_id == package_ids[package.code],
                PackageItemModel.equipment_item_id.not_in(wanted),
            )
        )


def _upsert_bookings(session: Session, bookings: tuple[Booking, ...]) -> None:
    if not bookings:
        return
    statement = insert(BookingModel).values(
        [
            {
                "booking_code": b.code,
                "item_code": b.item_code,
                "quantity": b.quantity,
                "starts_at": b.start,
                "ends_at": b.end,
                "status": b.status.value,
            }
            for b in bookings
        ]
    )
    columns = ("quantity", "starts_at", "ends_at", "status")
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["booking_code", "item_code"],
            set_={**{c: statement.excluded[c] for c in columns}, "updated_at": func.now()},
        )
    )


def seed_catalog(
    session_factory: sessionmaker[Session],
    items: Iterable[EquipmentItem],
    packages: Iterable[ServicePackage],
    bookings: Iterable[Booking] = (),
) -> SeedResult:
    """Upsert the definitions in one transaction; invalid definitions write nothing."""
    item_values = _collect(items, EquipmentItem, "items")
    package_values = _collect(packages, ServicePackage, "packages")
    booking_values = _collect(bookings, Booking, "bookings")
    Catalog(item_values, package_values)  # duplicate codes and dangling references raise here
    seeded_codes = {item.code for item in item_values}
    if any(booking.item_code not in seeded_codes for booking in booking_values):
        raise InvalidCatalog("every seeded booking must reference a seeded item")
    if len({(b.code, b.item_code) for b in booking_values}) != len(booking_values):
        raise InvalidCatalog("seeded bookings must be unique per (code, item_code)")
    try:
        with session_factory.begin() as session:
            _upsert_items(session, item_values)
            _upsert_packages(session, package_values)
            _upsert_bookings(session, booking_values)
    except SQLAlchemyError as exc:
        raise storage_error(exc) from None
    return SeedResult(len(item_values), len(package_values), len(booking_values))
