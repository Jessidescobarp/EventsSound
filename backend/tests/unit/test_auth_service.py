"""Login use case with in-memory fakes: no hashing library, no database."""

import pytest

from eventssound.application.auth import (
    AuthService,
    InvalidCredentials,
    IssuedToken,
)
from eventssound.domain.user import Role, User

USER = User("11111111-1111-4111-8111-111111111111", "ana@example.com", Role.CLIENT, "hash:secret")


class FakeHasher:
    def __init__(self) -> None:
        self.verified: list[str] = []

    def verify(self, password_hash: str, password: str) -> bool:
        self.verified.append(password_hash)
        return password_hash == f"hash:{password}"


class FakeTokens:
    def issue(self, user: User) -> IssuedToken:
        return IssuedToken(f"token-for-{user.email}", 3600, user.role)


class FakeUsers:
    def by_email(self, email: str) -> User | None:
        return USER if email == USER.email else None

    def by_id(self, user_id: str) -> User | None:
        return USER if user_id == USER.id else None


def service(hasher: FakeHasher | None = None) -> tuple[AuthService, FakeHasher]:
    hasher = hasher or FakeHasher()
    return AuthService(FakeUsers(), hasher, FakeTokens(), dummy_hash="hash:dummy"), hasher


def test_valid_credentials_issue_a_token_and_normalise_the_email() -> None:
    auth, _ = service()

    assert auth.login("  Ana@Example.com ", "secret") == IssuedToken(
        "token-for-ana@example.com", 3600, Role.CLIENT
    )


@pytest.mark.parametrize(
    ("email", "password", "verified"),
    [
        ("ana@example.com", "wrong", ["hash:secret"]),
        ("nobody@example.com", "secret", ["hash:dummy"]),  # unknown email still pays one verify
    ],
    ids=["wrong-password", "unknown-email"],
)
def test_bad_credentials_are_one_indistinguishable_error(email, password, verified) -> None:
    auth, hasher = service()

    with pytest.raises(InvalidCredentials):
        auth.login(email, password)

    assert hasher.verified == verified


@pytest.mark.parametrize(
    ("user_id", "password", "ok", "verified"),
    [
        (USER.id, "secret", True, ["hash:secret"]),
        (USER.id, "wrong", False, ["hash:secret"]),
        ("22222222-2222-4222-8222-222222222222", "secret", False, ["hash:dummy"]),  # no such user
    ],
    ids=["valid", "wrong-password", "unknown-user"],
)
def test_verify_password_rechecks_a_signed_in_user_without_revealing_existence(
    user_id, password, ok, verified
) -> None:
    auth, hasher = service()

    assert auth.verify_password(user_id, password) is ok
    assert hasher.verified == verified
