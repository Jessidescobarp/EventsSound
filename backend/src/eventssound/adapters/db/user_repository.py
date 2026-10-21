"""Users read from Postgres behind the `UserRepository` port."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.application.errors import RepositoryUnavailable
from eventssound.domain.user import Role, User

from .models import UserModel


class SqlAlchemyUserRepository:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def by_email(self, email: str) -> User | None:
        try:
            with self._factory() as session:
                row = session.scalar(select(UserModel).where(UserModel.email == email))
        except SQLAlchemyError as error:
            raise RepositoryUnavailable from error
        if row is None:
            return None
        return User(str(row.id), row.email, Role(row.role), row.password_hash)

    def by_id(self, user_id: str) -> User | None:
        try:
            key = UUID(user_id)
        except ValueError:
            return None
        try:
            with self._factory() as session:
                row = session.get(UserModel, key)
        except SQLAlchemyError as error:
            raise RepositoryUnavailable from error
        if row is None:
            return None
        return User(str(row.id), row.email, Role(row.role), row.password_hash)
