"""Turn driver errors into generic application errors, and check the migrated schema.

Nothing derived from the driver message (host, user, database, SQL) leaves this module: the
message is only inspected, and the returned errors carry fixed text.
"""

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.application.errors import (
    AuthenticationFailed,
    ConnectionFailed,
    RepositoryUnavailable,
    SchemaNotReady,
)

_UNDEFINED = {"42P01", "42703"}  # undefined_table, undefined_column
_CONNECTION_CLASSES = ("08", "53", "57P")  # connection exception, resources, operator intervention
_AUTH_HINTS = ("authentication failed", "pg_hba.conf")


def storage_error(exc: SQLAlchemyError) -> RepositoryUnavailable:
    """The application error for a driver failure; connection, credentials and schema differ."""
    original = getattr(exc, "orig", None)
    sqlstate = getattr(original, "sqlstate", None)
    message = str(original).lower()
    if isinstance(sqlstate, str) and sqlstate in _UNDEFINED:
        return SchemaNotReady("database schema is missing or out of date")
    if (isinstance(sqlstate, str) and sqlstate.startswith("28")) or any(
        hint in message for hint in _AUTH_HINTS
    ):
        return AuthenticationFailed("the database rejected the credentials")
    if isinstance(exc, OperationalError) and (
        sqlstate is None or (isinstance(sqlstate, str) and sqlstate.startswith(_CONNECTION_CLASSES))
    ):
        return ConnectionFailed("cannot connect to the database")
    return RepositoryUnavailable("storage unavailable")


def check_schema(session_factory: sessionmaker[Session], expected_revision: str) -> None:
    """Raise SchemaNotReady unless `alembic_version` holds exactly `expected_revision`."""
    try:
        with session_factory() as session:
            revisions = session.execute(text("SELECT version_num FROM alembic_version")).scalars()
            current = list(revisions)
    except SQLAlchemyError as exc:
        raise storage_error(exc) from None
    if current != [expected_revision]:
        raise SchemaNotReady("database schema is missing or out of date")
