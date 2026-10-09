from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker


class SqlAlchemyDatabaseHealth:
    """Driven adapter implementing DatabaseHealthPort with ``SELECT 1``."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ping(self) -> None:
        with self._session_factory() as session:
            session.execute(text("SELECT 1"))
