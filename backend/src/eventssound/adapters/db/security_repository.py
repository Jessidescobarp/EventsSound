"""Security events in Postgres behind the `SecurityLog` port."""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.application.errors import RepositoryUnavailable
from eventssound.application.quotes import Page
from eventssound.application.security import StoredEvent

from .models import SecurityEventModel as Event

RETENTION = timedelta(days=30)  # older rows are deleted on write (indexed on `at`)


class SqlAlchemySecurityLog:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def add(self, kind: str, client: str, at: datetime) -> None:
        try:
            with self._factory.begin() as session:
                session.execute(delete(Event).where(Event.at < at - RETENTION))
                session.add(Event(kind=kind, client=client, at=at))
        except SQLAlchemyError as error:
            raise RepositoryUnavailable from error

    def count_since(self, kind: str, client: str, since: datetime) -> int:
        query = select(func.count()).where(
            Event.kind == kind, Event.client == client, Event.at >= since
        )
        try:
            with self._factory() as session:
                return session.scalar(query) or 0
        except SQLAlchemyError as error:
            raise RepositoryUnavailable from error

    def page(self, limit: int, offset: int) -> Page[StoredEvent]:
        try:
            with self._factory() as session:
                total = session.scalar(select(func.count()).select_from(Event)) or 0
                rows = session.scalars(
                    select(Event)
                    .order_by(Event.at.desc(), Event.id.desc())
                    .limit(limit)
                    .offset(offset)
                ).all()
                items = tuple(StoredEvent(r.id, r.at, r.kind, r.client) for r in rows)
        except SQLAlchemyError as error:
            raise RepositoryUnavailable from error
        return Page(items, total, limit, offset)

    def summary(self, since: datetime) -> dict[str, int]:
        query = select(Event.kind, func.count()).where(Event.at >= since).group_by(Event.kind)
        try:
            with self._factory() as session:
                return {kind: n for kind, n in session.execute(query).all()}
        except SQLAlchemyError as error:
            raise RepositoryUnavailable from error
