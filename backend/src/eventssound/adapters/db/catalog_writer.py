"""Catalog writes in Postgres behind the `CatalogWriter` port. One transaction per call."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from eventssound.application.errors import CodeTaken, NotFound
from eventssound.domain.catalog import EquipmentItem, ServicePackage
from eventssound.domain.errors import UnknownCatalogEntry

from .models import EquipmentItemModel, PackageItemModel, ServicePackageModel
from .storage import storage_error


class SqlAlchemyCatalogWriter:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def create_item(self, item: EquipmentItem) -> None:
        with self._write() as session:
            session.add(
                EquipmentItemModel(
                    code=item.code,
                    name=item.name,
                    category=item.category.value,
                    stock_quantity=item.stock_quantity,
                    unit_price_cop=item.unit_price.amount,
                )
            )

    def update_item(self, item: EquipmentItem) -> None:
        with self._write() as session:
            row = session.scalar(
                select(EquipmentItemModel).where(EquipmentItemModel.code == item.code)
            )
            if row is None:
                raise NotFound
            row.name = item.name
            row.category = item.category.value
            row.stock_quantity = item.stock_quantity
            row.unit_price_cop = item.unit_price.amount

    def create_package(self, package: ServicePackage) -> None:
        with self._write() as session:
            row = ServicePackageModel(
                code=package.code, name=package.name, discount_bps=package.discount_bps
            )
            row.lines = self._lines(session, package)
            session.add(row)

    def update_package(self, package: ServicePackage) -> None:
        with self._write() as session:
            row = session.scalar(
                select(ServicePackageModel)
                .options(selectinload(ServicePackageModel.lines))
                .where(ServicePackageModel.code == package.code)
            )
            if row is None:
                raise NotFound
            lines = self._lines(session, package)
            row.name = package.name
            row.discount_bps = package.discount_bps
            # Delete the old lines first: the unique (package, item) pair would clash otherwise.
            row.lines.clear()
            session.flush()
            row.lines = lines

    @staticmethod
    def _lines(session: Session, package: ServicePackage) -> list[PackageItemModel]:
        codes = [line.item_code for line in package.lines]
        ids = dict(
            session.execute(
                select(EquipmentItemModel.code, EquipmentItemModel.id).where(
                    EquipmentItemModel.code.in_(codes)
                )
            ).all()
        )
        for code in codes:
            if code not in ids:
                raise UnknownCatalogEntry(code)
        return [
            PackageItemModel(equipment_item_id=ids[line.item_code], quantity=line.quantity)
            for line in package.lines
        ]

    @contextmanager
    def _write(self) -> Iterator[Session]:
        """One session that commits on success and maps driver errors to application errors."""
        session = self._factory()
        try:
            yield session
            session.commit()
        except IntegrityError:
            session.rollback()
            raise CodeTaken from None  # the unique code is the only constraint it can hit
        except SQLAlchemyError as error:
            session.rollback()
            raise storage_error(error) from None
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()
