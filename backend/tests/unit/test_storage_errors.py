"""Classification of driver errors into generic, secret-free application errors."""

import pytest
from sqlalchemy.exc import DataError, IntegrityError, OperationalError, ProgrammingError

from eventssound.adapters.db.storage import storage_error
from eventssound.application.errors import (
    AuthenticationFailed,
    ConnectionFailed,
    RepositoryUnavailable,
    SchemaNotReady,
)

SECRET = "sentinel_pw@sentinel-host"


class DriverError(Exception):
    """Looks like a psycopg error: a message and an optional SQLSTATE."""

    def __init__(self, message: str, sqlstate: str | None = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


def wrapped(kind: type[Exception], message: str, sqlstate: str | None = None) -> Exception:
    return kind("SELECT 1", {}, DriverError(f"{message} {SECRET}", sqlstate))  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (wrapped(OperationalError, "connection refused"), ConnectionFailed),
        (wrapped(OperationalError, "timeout expired"), ConnectionFailed),
        (wrapped(OperationalError, "server closed the connection", "08006"), ConnectionFailed),
        (
            wrapped(OperationalError, "the database system is shutting down", "57P01"),
            ConnectionFailed,
        ),
        (wrapped(OperationalError, "too many connections", "53300"), ConnectionFailed),
        (
            wrapped(OperationalError, "FATAL: password authentication failed for user"),
            AuthenticationFailed,
        ),
        (wrapped(OperationalError, "FATAL: no pg_hba.conf entry for host"), AuthenticationFailed),
        (wrapped(OperationalError, "invalid password", "28P01"), AuthenticationFailed),
        (
            wrapped(ProgrammingError, 'relation "alembic_version" does not exist', "42P01"),
            SchemaNotReady,
        ),
        (wrapped(ProgrammingError, "column does not exist", "42703"), SchemaNotReady),
    ],
    ids=[
        "refused",
        "timeout",
        "08-class",
        "57P-class",
        "53-class",
        "auth-message",
        "pg-hba",
        "28-class",
        "undefined-table",
        "undefined-column",
    ],
)
def test_driver_errors_map_to_distinct_application_errors(
    error: Exception, expected: type[RepositoryUnavailable]
) -> None:
    result = storage_error(error)  # type: ignore[arg-type]

    assert type(result) is expected
    assert isinstance(result, RepositoryUnavailable)


@pytest.mark.parametrize(
    "error",
    [
        wrapped(ProgrammingError, "permission denied for table bookings", "42501"),
        wrapped(OperationalError, "could not obtain lock", "55P03"),
        wrapped(DataError, "value too large", "22001"),
        wrapped(IntegrityError, "duplicate key", "23505"),
    ],
    ids=["permission", "lock", "data", "integrity"],
)
def test_everything_else_is_a_plain_repository_unavailable(error: Exception) -> None:
    assert type(storage_error(error)) is RepositoryUnavailable  # type: ignore[arg-type]


def test_messages_are_fixed_and_carry_no_driver_text() -> None:
    errors = [
        wrapped(OperationalError, "connection refused"),
        wrapped(OperationalError, "FATAL: password authentication failed"),
        wrapped(ProgrammingError, "missing", "42P01"),
        wrapped(DataError, "bad", "22001"),
    ]

    for error in errors:
        message = str(storage_error(error))  # type: ignore[arg-type]
        assert message
        assert "sentinel" not in message
        assert "password" not in message
