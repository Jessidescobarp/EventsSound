"""Portfolio events: the Postgres store (needs DATABASE_URL_TEST) and the routes (fakes)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker

from eventssound.adapters.auth.tokens import JwtTokenIssuer
from eventssound.adapters.db.portfolio_repository import SqlAlchemyPortfolioStore
from eventssound.adapters.usage.rate_limit import InMemoryRateLimiter
from eventssound.application.auth import AuthService
from eventssound.application.errors import NotFound, RepositoryUnavailable
from eventssound.application.portfolio import StoredPortfolioEvent
from eventssound.config import Settings
from eventssound.domain.errors import InvalidPortfolioEvent
from eventssound.domain.portfolio import PortfolioEvent
from eventssound.domain.user import Role, User
from eventssound.entrypoints.api.app import create_app
from eventssound.entrypoints.api.auth_kit import AuthKit

BODY = {
    "title": "Boda en la finca",
    "kind": "Boda",
    "description": "Sonido y luces para 120 invitados.",
    "equipment": ["Sonido", "Luces LED"],
    "visible": True,
}


def event(**over: object) -> PortfolioEvent:
    values: dict[str, object] = {
        "title": "Evento",
        "kind": "Fiesta",
        "description": "Descripcion",
        "equipment": ("Sonido",),
    }
    values.update(over)
    return PortfolioEvent(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "over",
    [
        {"title": "  "},
        {"title": "x" * 121},
        {"kind": "uno\ndos"},
        {"description": "x" * 501},
        {"equipment": ["x"] * 13},
        {"equipment": [""]},
        {"equipment": "Sonido"},
        {"visible": "yes"},
    ],
)
def test_the_domain_refuses_out_of_bounds_events(over: dict) -> None:
    with pytest.raises(InvalidPortfolioEvent):
        event(**over)


def test_the_domain_trims_text() -> None:
    assert event(title="  Boda  ").title == "Boda"


@pytest.fixture
def store(migrated_database: str) -> Iterator[SqlAlchemyPortfolioStore]:
    engine: Engine = create_engine(migrated_database)
    yield SqlAlchemyPortfolioStore(sessionmaker(engine))
    engine.dispose()


def test_the_migration_seeds_the_six_illustrative_events(store: SqlAlchemyPortfolioStore) -> None:
    events = store.list_events(visible_only=True)

    assert len(events) >= 6
    assert events[0].event.title == "Boda en jardín" and "Sonido" in events[0].event.equipment


def test_add_update_and_hide_round_trip(store: SqlAlchemyPortfolioStore) -> None:
    new_id = store.add(event(title="Nuevo", equipment=("A", "B")))
    store.update(new_id, event(title="Renombrado", visible=False))

    everything = {e.id: e.event for e in store.list_events(visible_only=False)}
    visible = {e.id for e in store.list_events(visible_only=True)}

    assert everything[new_id].title == "Renombrado" and everything[new_id].visible is False
    assert new_id not in visible


def test_updating_a_missing_event_is_not_found(store: SqlAlchemyPortfolioStore) -> None:
    with pytest.raises(NotFound):
        store.update(999_999, event())


# --- routes, with a fake store -----------------------------------------------------------------

SECRET = SecretStr("q" * 40)
ANA = User("66666666-6666-4666-8666-666666666666", "ana@example.com", Role.CLIENT, "h:pw")
ROOT = User("77777777-7777-4777-8777-777777777777", "root@example.com", Role.ADMIN, "h:pw")


class FakeStore:
    def __init__(self) -> None:
        self.rows: dict[int, PortfolioEvent] = {
            1: event(title="Visible"),
            2: event(title="Oculto", visible=False),
        }
        self.broken = False

    def list_events(self, visible_only: bool) -> tuple[StoredPortfolioEvent, ...]:
        if self.broken:
            raise RepositoryUnavailable
        return tuple(
            StoredPortfolioEvent(i, e)
            for i, e in self.rows.items()
            if e.visible or not visible_only
        )

    def add(self, new: PortfolioEvent) -> int:
        if self.broken:
            raise RepositoryUnavailable
        self.rows[max(self.rows) + 1] = new
        return max(self.rows)

    def update(self, event_id: int, new: PortfolioEvent) -> None:
        if event_id not in self.rows:
            raise NotFound
        self.rows[event_id] = new


class Hasher:
    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"h:{password}"


class Users:
    def by_email(self, email: str) -> User | None:
        return {u.email: u for u in (ANA, ROOT)}.get(email)


def make_client() -> tuple[TestClient, FakeStore]:
    fake = FakeStore()
    tokens = JwtTokenIssuer(SECRET, 60)
    kit = AuthKit(
        AuthService(Users(), Hasher(), tokens, dummy_hash="h:x"),
        tokens,
        InMemoryRateLimiter(100),
        InMemoryRateLimiter(100),
    )
    settings = Settings(_env_file=None, DATABASE_URL="postgresql+psycopg://u:p@127.0.0.1:1/x")  # type: ignore[call-arg]
    return TestClient(create_app(settings, auth_kit=kit, portfolio_store=fake)), fake


def as_user(client: TestClient, user: User) -> dict[str, str]:
    body = {"email": user.email, "password": "pw"}
    token = client.post("/auth/login", json=body).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_the_public_list_shows_only_visible_events_and_needs_no_login() -> None:
    client, _ = make_client()

    titles = [e["title"] for e in client.get("/portfolio").json()["events"]]

    assert titles == ["Visible"]


def test_only_an_admin_sees_hidden_events_and_edits() -> None:
    client, fake = make_client()
    ana, root = as_user(client, ANA), as_user(client, ROOT)

    assert client.get("/admin/portfolio").status_code == 401
    assert client.get("/admin/portfolio", headers=ana).status_code == 403
    assert client.post("/admin/portfolio", json=BODY, headers=ana).status_code == 403
    assert len(client.get("/admin/portfolio", headers=root).json()["events"]) == 2

    created = client.post("/admin/portfolio", json=BODY, headers=root)
    assert created.status_code == 201
    new_id = created.json()["id"]
    hide = client.put(f"/admin/portfolio/{new_id}", json={**BODY, "visible": False}, headers=root)
    assert hide.status_code == 200 and fake.rows[new_id].visible is False
    assert "Boda en la finca" not in [e["title"] for e in client.get("/portfolio").json()["events"]]


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "title": ""},
        {**BODY, "equipment": ["x"] * 13},
        {**BODY, "title": "uno\ndos"},
        {**BODY, "extra": 1},
    ],
)
def test_invalid_events_are_refused(body: dict) -> None:
    client, fake = make_client()

    response = client.post("/admin/portfolio", json=body, headers=as_user(client, ROOT))

    assert response.status_code == 422 and len(fake.rows) == 2


def test_editing_a_missing_event_is_404_and_storage_failure_is_503() -> None:
    client, fake = make_client()
    root = as_user(client, ROOT)

    assert client.put("/admin/portfolio/99", json=BODY, headers=root).status_code == 404
    assert client.put("/admin/portfolio/0", json=BODY, headers=root).status_code == 422
    fake.broken = True
    assert client.get("/portfolio").status_code == 503
    assert client.post("/admin/portfolio", json=BODY, headers=root).status_code == 503
