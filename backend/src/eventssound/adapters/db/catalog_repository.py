"""Read-only SQLAlchemy implementation of the `CatalogRepository` port."""

from sqlalchemy import select
from sqlalchemy.exc import DataError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from eventssound.application.errors import InvalidStoredData, RepositoryUnavailable
from eventssound.domain.catalog import (
    Catalog,
    EquipmentCategory,
    EquipmentItem,
    PackageLine,
    ServicePackage,
)
from eventssound.domain.errors import DomainError
from eventssound.domain.money import Money

from .models import EquipmentItemModel, ServicePackageModel


def _item_from_model(model: EquipmentItemModel) -> EquipmentItem:
    return EquipmentItem(
        code=model.code,
        name=model.name,
        category=EquipmentCategory(model.category),
        stock_quantity=model.stock_quantity,
        unit_price=Money(model.unit_price_cop),
    )


def _package_from_model(model: ServicePackageModel, codes: dict[int, str]) -> ServicePackage:
    lines = sorted(
        (PackageLine(codes[line.equipment_item_id], line.quantity) for line in model.lines),
        key=lambda line: line.item_code,
    )
    return ServicePackage(
        code=model.code, name=model.name, lines=tuple(lines), discount_bps=model.discount_bps
    )


class SqlAlchemyCatalogRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_catalog(self) -> Catalog:
        try:
            with self._session_factory() as session:
                # One snapshot for both selects, so a concurrent seed cannot split them.
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                items = session.scalars(
                    select(EquipmentItemModel).order_by(EquipmentItemModel.code)
                ).all()
                packages = session.scalars(
                    select(ServicePackageModel)
                    .options(selectinload(ServicePackageModel.lines))
                    .order_by(ServicePackageModel.code)
                ).all()
                # Mapping stays inside the session: it reads the loaded relationships.
                return self._to_domain(items, packages)
        except DataError:
            raise InvalidStoredData("stored catalog row cannot be read") from None
        except SQLAlchemyError:
            raise RepositoryUnavailable("catalog storage unavailable") from None

    @staticmethod
    def _to_domain(items: list[EquipmentItemModel], packages: list[ServicePackageModel]) -> Catalog:
        codes = {item.id: item.code for item in items}
        try:
            return Catalog(
                items=tuple(_item_from_model(item) for item in items),
                packages=tuple(_package_from_model(package, codes) for package in packages),
            )
        except DomainError as exc:
            raise InvalidStoredData(f"stored catalog is invalid: {exc}") from None
        except (ValueError, KeyError):
            raise InvalidStoredData("stored catalog row is invalid") from None
