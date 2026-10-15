"""Saved quotes and the admin booking list, read from Postgres behind the application ports."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.application.errors import RepositoryUnavailable
from eventssound.application.quotes import BookingRow, NewQuote, Page, StoredQuote

from .models import BookingModel, QuoteModel


class SqlAlchemyQuoteStore:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def add(self, quote: NewQuote) -> str:
        row = QuoteModel(
            user_id=uuid.UUID(quote.user_id) if quote.user_id else None,
            event_type=quote.event_type,
            event_start=quote.event_start,
            event_end=quote.event_end,
            guest_count=quote.guest_count,
            total_cop=quote.total_cop,
            available=quote.available,
            quote=quote.quote,
            event_request=quote.event_request,
        )
        try:
            with self._factory.begin() as session:
                session.add(row)
                session.flush()
                return str(row.id)
        except SQLAlchemyError as error:
            raise RepositoryUnavailable from error

    def page(self, user_id: str | None, limit: int, offset: int) -> Page[StoredQuote]:
        base = select(QuoteModel)
        count = select(func.count()).select_from(QuoteModel)
        if user_id is not None:
            owner = QuoteModel.user_id == uuid.UUID(user_id)
            base, count = base.where(owner), count.where(owner)
        try:
            with self._factory() as session:
                total = session.scalar(count) or 0
                rows = session.scalars(
                    base.order_by(QuoteModel.created_at.desc(), QuoteModel.id.desc())
                    .limit(limit)
                    .offset(offset)
                ).all()
                items = tuple(
                    StoredQuote(
                        id=str(r.id),
                        created_at=r.created_at,
                        registered=r.user_id is not None,
                        event_type=r.event_type,
                        event_start=r.event_start,
                        event_end=r.event_end,
                        guest_count=r.guest_count,
                        total_cop=r.total_cop,
                        available=r.available,
                        quote=r.quote,
                        event_request=r.event_request,
                    )
                    for r in rows
                )
        except SQLAlchemyError as error:
            raise RepositoryUnavailable from error
        return Page(items, total, limit, offset)


class SqlAlchemyBookingLister:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def page(self, limit: int, offset: int) -> Page[BookingRow]:
        try:
            with self._factory() as session:
                total = session.scalar(select(func.count()).select_from(BookingModel)) or 0
                rows = session.scalars(
                    select(BookingModel)
                    .order_by(BookingModel.created_at.desc(), BookingModel.id.desc())
                    .limit(limit)
                    .offset(offset)
                ).all()
                items = tuple(
                    BookingRow(
                        r.booking_code,
                        r.item_code,
                        r.quantity,
                        r.starts_at,
                        r.ends_at,
                        r.status,
                        r.created_at,
                    )
                    for r in rows
                )
        except SQLAlchemyError as error:
            raise RepositoryUnavailable from error
        return Page(items, total, limit, offset)
