"""Abuse block on the chat, login failure events and `/admin/security` (fakes, no database)."""

import logging
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from test_quotes_api import ANA, CHAT, ROOT, Agent, make_client, token_for

from eventssound.adapters.usage.rate_limit import InMemoryRateLimiter
from eventssound.application.quote_chat import AgentOutcome, AgentStatus
from eventssound.application.security import CHAT_REFUSED, LOGIN_FAILED, client_key, derive_key
from eventssound.config import Settings
from eventssound.entrypoints.api.container import make_abuse_gate
from fakes import InMemorySecurityLog


class CountingAgent(Agent):
    def __init__(self, status: AgentStatus) -> None:
        super().__init__(status)
        self.calls = 0

    def run(self, data: object) -> AgentOutcome:
        self.calls += 1
        return super().run(data)


def build(agent: Agent | None = None, **app_args: object) -> tuple[TestClient, InMemorySecurityLog]:
    log = InMemorySecurityLog()
    client, _ = make_client(
        agent=agent or Agent(AgentStatus.REFUSED), trusted_hops=1, security_log=log, **app_args
    )
    return client, log


def chat(client: TestClient, ip: str = "10.0.0.1"):  # noqa: ANN201
    return client.post("/quote/chat", json=CHAT, headers={"X-Forwarded-For": ip})


def test_five_refusals_block_the_sixth_without_calling_the_agent() -> None:
    agent = CountingAgent(AgentStatus.REFUSED)
    client, log = build(agent)

    first = [chat(client).status_code for _ in range(5)]
    blocked = chat(client)
    other = chat(client, "10.0.0.2")

    assert first == [200] * 5 and other.status_code == 200
    assert agent.calls == 6  # five answered + the other client; the blocked one never got in
    assert blocked.status_code == 429 and blocked.json()["detail"] == "temporarily_blocked"
    assert blocked.headers["Retry-After"] == "600"
    # Only refusals are stored: blocked and rate-limited requests add no rows.
    assert [k for k, _, _ in log.rows] == [CHAT_REFUSED] * 6


def test_rate_limited_requests_add_no_rows(caplog: pytest.LogCaptureFixture) -> None:
    client, log = build(Agent(), rate_limiter=InMemoryRateLimiter(1))

    with caplog.at_level(logging.INFO):
        statuses = [chat(client).status_code for _ in range(2)]

    assert statuses == [200, 429] and log.rows == []
    assert "10.0.0.1" not in caplog.text


@pytest.mark.parametrize(
    ("env", "hops", "active"),
    [
        ("production", 0, False),  # one shared key behind the proxy: a block would lock everyone
        ("production", 1, True),
        ("local", 0, True),
    ],
)
def test_the_gate_needs_a_trustworthy_client_address_in_production(
    env: str, hops: int, active: bool
) -> None:
    secret = "j" * 40
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://u:p@127.0.0.1:1/x",
        app_env=env,
        trusted_proxy_hops=hops,
        jwt_secret=secret,
    )  # type: ignore[call-arg]
    log = InMemorySecurityLog()
    for _ in range(5):
        log.add(CHAT_REFUSED, client_key("1.1.1.1", derive_key(secret)), datetime.now(UTC))
    gate = make_abuse_gate(settings, log)

    assert gate.is_blocked("1.1.1.1") is active
    gate.record(CHAT_REFUSED, "2.2.2.2")
    assert len(log.rows) == 5 + int(active)


def test_a_failed_login_records_one_event_without_the_email() -> None:
    client, log = build()

    response = client.post("/auth/login", json={"email": ANA.email, "password": "wrong"})
    ok = client.post("/auth/login", json={"email": ANA.email, "password": "pw"})

    assert (response.status_code, ok.status_code) == (401, 200)
    assert len(log.rows) == 1 and log.rows[0][0] == LOGIN_FAILED
    assert ANA.email not in repr(log.rows) and "wrong" not in repr(log.rows)


def test_admin_security_is_admin_only_and_summarises_the_last_day() -> None:
    client, _ = build()
    for _ in range(2):
        client.post("/auth/login", json={"email": ANA.email, "password": "wrong"})
    chat(client)
    ana, root = token_for(client, ANA), token_for(client, ROOT)

    assert client.get("/admin/security").status_code == 401
    assert client.get("/admin/security", headers=ana).status_code == 403
    page = client.get("/admin/security?limit=2", headers=root).json()

    assert (page["total"], len(page["items"]), page["limit"], page["offset"]) == (3, 2, 2, 0)
    assert page["last_24h"] == {LOGIN_FAILED: 2, CHAT_REFUSED: 1}
    assert set(page["items"][0]) == {"id", "at", "kind", "client"}
