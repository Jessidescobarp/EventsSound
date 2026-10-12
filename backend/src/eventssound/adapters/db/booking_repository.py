"""Read-only SQLAlchemy implementation of the `BookingRepository` port."""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import DataError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.application.booking_query import ReservationQuery
from eventssound.application.errors import InvalidStoredData, RepositoryUnavailable
from eventssound.domain.availability import Booking, BookingStatus
from eventssound.domain.errors import DomainError

from .models import BookingModel


def booking_from_row(row: Any) -> Booking:
    """Map one stored row to a domain `Booking`; database values are never trusted."""
    try:
        return Booking(
            code=row.booking_code,
            item_code=row.item_code,
            quantity=row.quantity,
            start=row.starts_at,
            end=row.ends_at,
            status=BookingStatus(row.status),
        )
    except DomainError as exc:
        raise InvalidStoredData(f"stored booking row is invalid: {exc}") from None
    except ValueError:
        raise InvalidStoredData("stored booking row has an unknown status") from None


class SqlAlchemyBookingRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def find_reservations(
        self, item_codes: Collection[str], window_start: datetime, window_end: datetime
    ) -> Sequence[Booking]:
        query = ReservationQuery(item_codes, window_start, window_end)
        if not query.item_codes:
            return ()
        # The domain ignores cancelled bookings itself; filtering here as well is defence in depth.
        blocking = sorted(status.value for status in BookingStatus.blocking())
        statement = (
            select(
                BookingModel.booking_code,
                BookingModel.item_code,
                BookingModel.quantity,
                BookingModel.starts_at,
                BookingModel.ends_at,
                BookingModel.status,
            )
            .where(
                BookingModel.item_code.in_(sorted(query.item_codes)),
                BookingModel.status.in_(blocking),
                BookingModel.starts_at < query.window_end,
                BookingModel.ends_at > query.window_start,
            )
            .order_by(BookingModel.starts_at, BookingModel.booking_code, BookingModel.item_code)
        )
        try:
            with self._session_factory() as session:
                rows = session.execute(statement).all()
        except DataError:
            raise InvalidStoredData("stored booking row cannot be read") from None
        except SQLAlchemyError:
            raise RepositoryUnavailable("booking storage unavailable") from None
        return tuple(booking_from_row(row) for row in rows)
