"""Login use case and the ports it needs (hasher, token issuer, user store)."""

from dataclasses import dataclass
from typing import Protocol

from eventssound.domain.user import Principal, Role, User


class InvalidCredentials(Exception):
    """Unknown email or wrong password. One error on purpose: no account enumeration."""


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    expires_in: int  # seconds
    role: Role


class PasswordHasher(Protocol):
    def verify(self, password_hash: str, password: str) -> bool: ...


class TokenIssuer(Protocol):
    def issue(self, user: User) -> IssuedToken: ...

    def verify(self, token: str) -> Principal | None:
        """The principal for a valid, unexpired token; None for anything else."""
        ...


class UserRepository(Protocol):
    def by_email(self, email: str) -> User | None: ...


def normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        hasher: PasswordHasher,
        tokens: TokenIssuer,
        *,
        dummy_hash: str,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._tokens = tokens
        self._dummy_hash = dummy_hash

    def login(self, email: str, password: str) -> IssuedToken:
        user = self._users.by_email(normalize_email(email))
        # An unknown email still pays one hash verification, so timing does not reveal it.
        stored = user.password_hash if user is not None else self._dummy_hash
        valid = self._hasher.verify(stored, password)
        if user is None or not valid:
            raise InvalidCredentials
        return self._tokens.issue(user)
