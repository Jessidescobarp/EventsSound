"""Composition root: the only place where concrete adapters are bound to ports.

Extension point: later phases register the ``LlmProvider`` port here (choosing an
adapter from settings, or a replay provider in tests). No LLM code exists yet.
"""

from collections.abc import Callable, Iterator

from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.db.health import SqlAlchemyDatabaseHealth
from eventssound.adapters.db.session import build_engine, build_session_factory
from eventssound.application.ports import DatabaseHealthPort
from eventssound.config import Settings

SessionProvider = Callable[[], Iterator[Session]]


def build_session_factory_from(settings: Settings) -> sessionmaker[Session]:
    return build_session_factory(build_engine(settings.database_url.get_secret_value()))


def make_session_provider(factory: sessionmaker[Session]) -> SessionProvider:
    def provide() -> Iterator[Session]:
        with factory() as session:
            yield session

    return provide


def make_database_health(factory: sessionmaker[Session]) -> DatabaseHealthPort:
    return SqlAlchemyDatabaseHealth(factory)
