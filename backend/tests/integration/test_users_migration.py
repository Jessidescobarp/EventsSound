"""Migration 0006: the users table, its constraints and reversibility."""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from eventssound.adapters.db.user_repository import SqlAlchemyUserRepository
from eventssound.domain.user import Role

INSERT = "INSERT INTO users (email, role, password_hash) VALUES (:email, :role, 'h')"


@pytest.fixture
def engine(migrated_database: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database)
    yield engine
    engine.dispose()


def add(engine: Engine, email: str = "ana@example.com", role: str = "client") -> None:
    with engine.begin() as connection:
        connection.execute(text(INSERT), {"email": email, "role": role})


@pytest.mark.parametrize(
    ("email", "role"),
    [("ana@example.com", "owner"), ("Ana@Example.com", "client")],
    ids=["unknown-role", "upper-case-email"],
)
def test_constraints_reject_bad_rows(engine: Engine, email: str, role: str) -> None:
    with pytest.raises(IntegrityError):
        add(engine, email, role)


def test_email_is_unique_and_the_id_is_generated(engine: Engine) -> None:
    add(engine)

    with pytest.raises(IntegrityError):
        add(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM users")).scalar_one() is not None
    assert [c["name"] for c in inspect(engine).get_columns("users")][:3] == ["id", "email", "role"]


def test_repository_finds_a_user_by_email_and_none_otherwise(engine: Engine) -> None:
    add(engine, "root@example.com", "admin")

    repository = SqlAlchemyUserRepository(sessionmaker(engine))
    found = repository.by_email("root@example.com")
    assert found is not None and found.role is Role.ADMIN and found.password_hash == "h"
    assert repository.by_email("nobody@example.com") is None


def test_downgrade_drops_the_table(alembic_config: Config, engine: Engine) -> None:
    command.downgrade(alembic_config, "0005")

    assert "users" not in inspect(engine).get_table_names()
