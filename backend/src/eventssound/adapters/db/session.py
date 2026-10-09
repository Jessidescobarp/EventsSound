from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def build_engine(database_url: str) -> Engine:
    """Create the engine lazily (no connection is opened here).

    pool_pre_ping and pool_recycle absorb Neon dropping idle connections.
    """
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=3,
        max_overflow=2,
        connect_args={"connect_timeout": 10},
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
