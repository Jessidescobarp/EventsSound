"""POST /auth/login and `require_role`: contracted errors, rate limits, no leaks."""

import logging
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr

from eventssound.adapters.auth.tokens import JwtTokenIssuer
from eventssound.adapters.usage.rate_limit import InMemoryRateLimiter
from eventssound.application.auth import AuthService
from eventssound.application.errors import RepositoryUnavailable
from eventssound.config import Settings
from eventssound.domain.user import Principal, Role, User
from eventssound.entrypoints.api.app import create_app
from eventssound.entrypoints.api.auth_kit import AuthKit, require_role

PASSWORD = "correct-horse-battery"
ADMIN = User(
    "33333333-3333-4333-8333-333333333333", "root@example.com", Role.ADMIN, f"h:{PASSWORD}"
)
CLIENT = User(
    "44444444-4444-4444-8444-444444444444", "ana@example.com", Role.CLIENT, f"h:{PASSWORD}"
)
SECRET = SecretStr("k" * 40)


class FakeHasher:
    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"h:{password}"


class FakeUsers:
    def __init__(self, broken: bool = False) -> None:
        self.broken = broken

    def by_email(self, email: str) -> User | None:
        if self.broken:
            raise RepositoryUnavailable
        return {u.email: u for u in (ADMIN, CLIENT)}.get(email)


def kit(users: FakeUsers | None = None, per_minute: int = 50) -> AuthKit:
    tokens = JwtTokenIssuer(SECRET, 60)
    service = AuthService(users or FakeUsers(), FakeHasher(), tokens, dummy_hash="h:dummy")
    return AuthKit(
        service, tokens, InMemoryRateLimiter(per_minute), InMemoryRateLimiter(per_minute)
    )


def make_client(auth: AuthKit | None, **settings: object) -> TestClient:
    values: dict[str, object] = {"DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1:1/x"}
    values.update(settings)
    app = create_app(Settings(_env_file=None, **values), auth_kit=auth)  # type: ignore[arg-type]
    router = APIRouter()

    @router.get("/_admin")
    def admin_only(who: Annotated[Principal, Depends(require_role(Role.ADMIN))]) -> dict:
        return {"role": who.role.value}

    @router.get("/_any")
    def any_user(who: Annotated[Principal, Depends(require_role(Role.CLIENT, Role.ADMIN))]) -> dict:
        return {"sub": who.user_id}

    app.include_router(router)
    return TestClient(app)


def login(client: TestClient, email: str = ADMIN.email, password: str = PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def bearer(client: TestClient, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {login(client, email).json()['access_token']}"}


def test_login_returns_a_bearer_token_with_the_role_and_is_not_cacheable() -> None:
    response = login(make_client(kit()), "  ROOT@example.com ")

    assert response.status_code == 200
    body = response.json()
    assert (body["token_type"], body["expires_in"], body["role"]) == ("bearer", 3600, "admin")
    assert body["access_token"].count(".") == 2
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("email", "password"),
    [(ADMIN.email, "wrong-password"), ("nobody@example.com", PASSWORD)],
    ids=["wrong-password", "unknown-email"],
)
def test_bad_credentials_give_the_same_401(email: str, password: str) -> None:
    response = login(make_client(kit()), email, password)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "invalid_credentials",
        "message": "El correo o la contrasena no son correctos.",
    }


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": "a@b.co"},
        {"email": "", "password": "x"},
        {"email": "a@b.co", "password": "x" * 201},
    ],
    ids=["empty", "no-password", "blank-email", "huge-password"],
)
def test_malformed_login_is_422(body: dict) -> None:
    assert make_client(kit()).post("/auth/login", json=body).status_code == 422


def test_login_is_rate_limited_per_address_and_per_email() -> None:
    client = make_client(kit(per_minute=2))

    statuses = [login(client, "nobody@example.com", "x").status_code for _ in range(3)]
    assert statuses == [401, 401, 429]
    limited = login(client, "nobody@example.com", "x")
    assert limited.json()["detail"] == "rate_limited" and int(limited.headers["retry-after"]) >= 1


def test_unconfigured_auth_answers_503_instead_of_crashing() -> None:
    client = make_client(None, app_env="production")

    assert login(client).json()["detail"] == "auth_not_configured"
    assert login(client).status_code == 503
    assert client.get("/_admin").status_code == 503
    assert client.get("/health").status_code in (200, 503)  # the rest of the app still answers


def test_storage_failure_is_503_without_detail() -> None:
    response = login(make_client(kit(FakeUsers(broken=True))))

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_unavailable"


def test_login_logs_never_contain_the_password_or_the_email(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    login(make_client(kit()), ADMIN.email, "a-very-secret-attempt")
    login(make_client(kit()), "nobody@example.com", PASSWORD)

    assert "a-very-secret-attempt" not in caplog.text and "root@example.com" not in caplog.text
    assert "nobody@example.com" not in caplog.text


def test_require_role_contract() -> None:
    client = make_client(kit())

    missing = client.get("/_admin")
    assert (missing.status_code, missing.json()["detail"]) == (401, "not_authenticated")
    assert missing.headers["www-authenticate"] == "Bearer"
    assert client.get("/_admin", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/_admin", headers={"Authorization": "Basic abc"}).status_code == 401
    forbidden = client.get("/_admin", headers=bearer(client, CLIENT.email))
    assert (forbidden.status_code, forbidden.json()["detail"]) == (403, "forbidden")
    assert client.get("/_admin", headers=bearer(client, ADMIN.email)).json() == {"role": "admin"}
    assert client.get("/_any", headers=bearer(client, CLIENT.email)).json() == {"sub": CLIENT.id}
