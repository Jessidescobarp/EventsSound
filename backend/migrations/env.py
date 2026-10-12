"""Alembic environment: URL from Settings, metadata from the registered models.

Concurrency note: no advisory lock is taken around the upgrade (deliberately, see the
quote-domain-core design). If two instances start at once on an empty database, the loser can fail
on `CREATE TABLE` ("already exists"); `start.sh` retries `alembic upgrade head` a bounded number of
times, and the retry then finds the new revision in `alembic_version` and succeeds as a no-op.
"""

from alembic import context
from sqlalchemy import create_engine, pool

import eventssound.adapters.db.models  # noqa: F401  (registers the models on Base.metadata)
from eventssound.adapters.db.session import Base
from eventssound.config import Settings

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=Settings().database_url.get_secret_value(),  # type: ignore[call-arg]
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        Settings().database_url.get_secret_value(),  # type: ignore[call-arg]
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 10},
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
