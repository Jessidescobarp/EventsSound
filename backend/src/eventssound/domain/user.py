"""Users and roles. Pure values: no hashing, tokens or storage here."""

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    CLIENT = "client"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class User:
    id: str  # public UUID text; the database id never leaves the adapter
    email: str  # already normalised (stripped, lower case)
    role: Role
    password_hash: str = ""

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, role={self.role.value!r})"  # never prints email or hash


@dataclass(frozen=True, slots=True)
class Principal:
    """Who a verified token says is calling."""

    user_id: str
    role: Role
