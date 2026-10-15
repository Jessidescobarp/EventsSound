"""Upsert of the demo users. Receives password hashes only; plain passwords never get here."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.application.errors import RepositoryUnavailable
from eventssound.domain.user import Role

from .models import UserModel


@dataclass(frozen=True, slots=True)
class SeedUser:
    email: str
    role: Role
    password_hash: str


def seed_users(factory: sessionmaker[Session], users: Sequence[SeedUser]) -> int:
    """Insert or update each user by email in one transaction; returns how many were written."""
    try:
        with factory.begin() as session:
            for user in users:
                statement = insert(UserModel).values(
                    email=user.email, role=user.role.value, password_hash=user.password_hash
                )
                session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[UserModel.email],
                        set_={
                            "role": statement.excluded.role,
                            "password_hash": statement.excluded.password_hash,
                        },
                    )
                )
    except SQLAlchemyError as error:
        raise RepositoryUnavailable from error
    return len(users)
