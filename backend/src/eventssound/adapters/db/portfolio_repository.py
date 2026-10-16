"""Portfolio events in Postgres behind the `PortfolioStore` port."""

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.application.errors import InvalidStoredData, NotFound
from eventssound.application.portfolio import StoredPortfolioEvent
from eventssound.domain.errors import DomainError
from eventssound.domain.portfolio import PortfolioEvent

from .models import PortfolioEventModel
from .storage import storage_error


def _event(row: PortfolioEventModel) -> PortfolioEvent:
    try:
        return PortfolioEvent(
            row.title, row.kind, row.description, tuple(row.equipment), row.visible
        )
    except DomainError:
        raise InvalidStoredData("stored portfolio event is invalid") from None


def _fill(row: PortfolioEventModel, event: PortfolioEvent) -> None:
    row.title = event.title
    row.kind = event.kind
    row.description = event.description
    row.equipment = list(event.equipment)
    row.visible = event.visible


class SqlAlchemyPortfolioStore:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def list_events(self, visible_only: bool) -> tuple[StoredPortfolioEvent, ...]:
        query = select(PortfolioEventModel).order_by(PortfolioEventModel.id)
        if visible_only:
            query = query.where(PortfolioEventModel.visible.is_(True))
        try:
            with self._factory() as session:
                return tuple(StoredPortfolioEvent(r.id, _event(r)) for r in session.scalars(query))
        except SQLAlchemyError as error:
            raise storage_error(error) from None

    def add(self, event: PortfolioEvent) -> int:
        row = PortfolioEventModel()
        _fill(row, event)
        try:
            with self._factory() as session:
                session.add(row)
                session.commit()
                return row.id
        except SQLAlchemyError as error:
            raise storage_error(error) from None

    def update(self, event_id: int, event: PortfolioEvent) -> None:
        try:
            with self._factory() as session:
                row = session.get(PortfolioEventModel, event_id)
                if row is None:
                    raise NotFound
                _fill(row, event)
                session.commit()
        except SQLAlchemyError as error:
            raise storage_error(error) from None
