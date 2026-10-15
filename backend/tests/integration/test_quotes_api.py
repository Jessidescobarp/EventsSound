"""Quote persistence from the chat route plus `/me/quotes` and `/admin/*` (fakes, no database)."""

from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agent_fixtures import make_catalog, neutral_rules
from eventssound.adapters.auth.tokens import JwtTokenIssuer
from eventssound.adapters.usage.memory import InMemoryUsageBudget
from eventssound.adapters.usage.rate_limit import InMemoryRateLimiter
from eventssound.application.auth import AuthService
from eventssound.application.errors import RepositoryUnavailable
from eventssound.application.quote_chat import AgentOutcome, AgentStatus
from eventssound.application.quotes import BookingRow, NewQuote, Page, StoredQuote
from eventssound.config import Settings
from eventssound.domain.event_request import EventRequest, EventType, RequestedLine, VenueType
from eventssound.domain.pricing import calculate_price
from eventssound.domain.user import Role, User
from eventssound.entrypoints.api.app import create_app
from eventssound.entrypoints.api.auth_kit import AuthKit

CHAT = {"messages": [{"role": "user", "content": "Necesito sonido para 100 personas"}]}
START = datetime(2026, 10, 17, 20, tzinfo=UTC)
REQUEST = EventRequest(
    EventType.WEDDING,
    START,
    START + timedelta(hours=2),
    100,
    10,
    VenueType.INDOOR,
    items=(RequestedLine("sound_speaker_15", 2),),
)
QUOTE = calculate_price(REQUEST, make_catalog(), neutral_rules())
SECRET = SecretStr("q" * 40)
ANA = User("66666666-6666-4666-8666-666666666666", "ana@example.com", Role.CLIENT, "h:pw")
ROOT = User("77777777-7777-4777-8777-777777777777", "root@example.com", Role.ADMIN, "h:pw")


class Agent:
    def __init__(self, status: AgentStatus = AgentStatus.QUOTE) -> None:
        self.status = status

    def run(self, data: object) -> AgentOutcome:
        if self.status is AgentStatus.QUOTE:
            return AgentOutcome(self.status, "Hola", "static", QUOTE, REQUEST, None, (), ())
        return AgentOutcome(self.status, "Mas datos", "static", None, None, None, ("guests",), ())


class Store:
    def __init__(self, broken: bool = False) -> None:
        self.rows: list[tuple[str, NewQuote]] = []
        self.broken = broken
        self._ids = count(1)

    def add(self, quote: NewQuote) -> str:
        if self.broken:
            raise RepositoryUnavailable
        quote_id = f"quote-{next(self._ids)}"
        self.rows.append((quote_id, quote))
        return quote_id

    def page(self, user_id: str | None, limit: int, offset: int) -> Page[StoredQuote]:
        if self.broken:
            raise RepositoryUnavailable
        mine = [(i, q) for i, q in reversed(self.rows) if user_id in (None, q.user_id)]
        items = tuple(
            StoredQuote(
                i,
                START,
                q.user_id is not None,
                {ANA.id: ANA.email}.get(q.user_id or ""),
                q.event_type,
                q.event_start,
                q.event_end,
                q.guest_count,
                q.total_cop,
                q.available,
                q.quote,
                q.event_request,
            )
            for i, q in mine[offset : offset + limit]
        )
        return Page(items, len(mine), limit, offset)


class Bookings:
    def page(self, limit: int, offset: int) -> Page[BookingRow]:
        rows = tuple(
            BookingRow(f"BK-{n}", "sound_x", 1, START, START + timedelta(hours=1), "pending", START)
            for n in range(3)
        )
        return Page(rows[offset : offset + limit], len(rows), limit, offset)


class Hasher:
    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"h:{password}"


class Users:
    def by_email(self, email: str) -> User | None:
        return {u.email: u for u in (ANA, ROOT)}.get(email)


def make_client(store: Store | None = None, agent: Agent | None = None) -> tuple[TestClient, Store]:
    store = store or Store()
    tokens = JwtTokenIssuer(SECRET, 60)
    kit = AuthKit(
        AuthService(Users(), Hasher(), tokens, dummy_hash="h:x"),
        tokens,
        InMemoryRateLimiter(100),
        InMemoryRateLimiter(100),
    )
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://u:p@127.0.0.1:1/x",
        chat_enabled=True,
        llm_provider="replay",
    )  # type: ignore[call-arg]
    app = create_app(
        settings,
        quote_agent=agent or Agent(),
        usage_budget=InMemoryUsageBudget(token_cap=1_000_000, cost_cap_micro_usd=10_000_000),
        rate_limiter=InMemoryRateLimiter(100),
        auth_kit=kit,
        quote_store=store,
        booking_lister=Bookings(),
    )
    return TestClient(app), store


def token_for(client: TestClient, user: User) -> dict[str, str]:
    body = {"email": user.email, "password": "pw"}
    return {
        "Authorization": f"Bearer {client.post('/auth/login', json=body).json()['access_token']}"
    }


def test_a_quote_is_saved_and_its_id_is_returned() -> None:
    client, store = make_client()

    response = client.post("/quote/chat", json=CHAT)

    body = response.json()
    assert response.status_code == 200 and body["status"] == "quote"
    assert body["quote_id"] == "quote-1"
    saved = store.rows[0][1]
    assert saved.user_id is None and saved.event_type == "wedding" and saved.guest_count == 100
    assert saved.total_cop == body["quote"]["total"] and saved.available is None
    assert saved.quote == body["quote"] and saved.event_request == body["event_request"]


def test_the_message_text_and_reply_are_never_stored() -> None:
    client, store = make_client()

    client.post("/quote/chat", json=CHAT)

    stored = repr(store.rows[0][1])
    assert "Necesito sonido" not in stored and "Hola" not in stored


def test_a_logged_in_caller_owns_the_quote_and_a_bad_token_does_not_break_the_chat() -> None:
    client, store = make_client()

    client.post("/quote/chat", json=CHAT, headers=token_for(client, ANA))
    broken = client.post("/quote/chat", json=CHAT, headers={"Authorization": "Bearer nope"})

    assert store.rows[0][1].user_id == ANA.id
    assert broken.status_code == 200 and store.rows[1][1].user_id is None


def test_clarifications_are_not_saved() -> None:
    client, store = make_client(agent=Agent(AgentStatus.CLARIFICATION))

    body = client.post("/quote/chat", json=CHAT).json()

    assert body["quote_id"] is None and store.rows == []


def test_a_storage_failure_never_blocks_the_chat_answer() -> None:
    client, _ = make_client(Store(broken=True))

    response = client.post("/quote/chat", json=CHAT)

    assert response.status_code == 200
    assert response.json()["status"] == "quote" and response.json()["quote_id"] is None


def test_me_quotes_lists_only_the_callers_quotes() -> None:
    client, _ = make_client()
    client.post("/quote/chat", json=CHAT)
    client.post("/quote/chat", json=CHAT, headers=token_for(client, ANA))

    assert client.get("/me/quotes").status_code == 401
    page = client.get("/me/quotes", headers=token_for(client, ANA)).json()

    assert (page["total"], page["limit"], page["offset"]) == (1, 20, 0)
    assert page["items"][0]["registered"] is True and page["items"][0]["quote"]["lines"]
    assert page["items"][0]["owner_email"] == ANA.email


def test_admin_lists_are_admin_only_and_paginated() -> None:
    client, _ = make_client()
    for _ in range(3):
        client.post("/quote/chat", json=CHAT)
    ana, root = token_for(client, ANA), token_for(client, ROOT)

    assert client.get("/admin/quotes").status_code == 401
    assert client.get("/admin/quotes", headers=ana).status_code == 403
    assert client.get("/admin/bookings", headers=ana).status_code == 403
    page = client.get("/admin/quotes?limit=2&offset=1", headers=root).json()
    assert (page["total"], len(page["items"]), page["limit"], page["offset"]) == (3, 2, 2, 1)
    bookings = client.get("/admin/bookings?limit=2", headers=root).json()
    assert bookings["total"] == 3 and bookings["items"][0]["booking_code"] == "BK-0"


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=abc"])
def test_page_parameters_are_bounded(query: str) -> None:
    client, _ = make_client()

    assert client.get(f"/admin/quotes?{query}", headers=token_for(client, ROOT)).status_code == 422


def test_storage_failure_on_a_list_is_a_503_without_detail() -> None:
    client, store = make_client()
    headers = token_for(client, ROOT)
    store.broken = True

    response = client.get("/admin/quotes", headers=headers)

    assert response.status_code == 503 and response.json()["detail"] == "storage_unavailable"


def test_an_old_shaped_stored_quote_never_breaks_the_list() -> None:
    client, store = make_client()
    store.add(
        NewQuote(
            None,
            "wedding",
            START,
            START + timedelta(hours=1),
            10,
            1000,
            None,
            {"legacy_field": 1},
            {"legacy": True},
        )
    )

    response = client.get("/admin/quotes", headers=token_for(client, ROOT))

    assert response.status_code == 200
    assert response.json()["items"][0]["quote"] == {"legacy_field": 1}


def test_offset_has_an_upper_bound() -> None:
    client, _ = make_client()

    assert (
        client.get("/admin/quotes?offset=100001", headers=token_for(client, ROOT)).status_code
        == 422
    )
