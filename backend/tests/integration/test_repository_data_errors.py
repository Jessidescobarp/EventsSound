"""Values the driver cannot decode are bad stored data, not an outage."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.db.booking_repository import SqlAlchemyBookingRepository
from eventssound.adapters.db.catalog_repository import SqlAlchemyCatalogRepository
from eventssound.application.errors import InvalidStoredData


@pytest.mark.parametrize("column", ["ends_at", "starts_at"])
def test_an_infinite_timestamp_in_a_booking_is_invalid_stored_data(
    session_factory: sessionmaker[Session], column: str
) -> None:
    infinity = "'infinity'" if column == "ends_at" else "'-infinity'"
    with session_factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO equipment_items (code, name, category, stock_quantity, unit_price_cop)"
                " VALUES ('abc', 'Equipo', 'sound', 1, 1000)"
            )
        )
        starts, ends = ("now()", infinity) if column == "ends_at" else (infinity, "now()")
        session.execute(
            text(
                "INSERT INTO bookings (booking_code, item_code, quantity, starts_at, ends_at)"
                f" VALUES ('BK-1', 'abc', 1, {starts}, {ends})"
            )
        )

    with pytest.raises(InvalidStoredData):
        SqlAlchemyBookingRepository(session_factory).find_reservations(
            {"abc"}, datetime(2000, 1, 1, tzinfo=UTC), datetime(9000, 1, 1, tzinfo=UTC)
        )


class DataErrorSession:
    """A session whose reads fail the way an undecodable value does."""

    def __enter__(self) -> "DataErrorSession":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def connection(self, **kwargs: object) -> None:
        return None

    def scalars(self, *args: object) -> None:
        raise DataError("SELECT 1", {}, Exception("value out of range sentinel_pw"))


def test_a_data_error_while_reading_the_catalog_is_invalid_stored_data() -> None:
    repository = SqlAlchemyCatalogRepository(lambda: DataErrorSession())  # type: ignore[arg-type]

    with pytest.raises(InvalidStoredData) as caught:
        repository.get_catalog()

    assert "sentinel" not in str(caught.value)
