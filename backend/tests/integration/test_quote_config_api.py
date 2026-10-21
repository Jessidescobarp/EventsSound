"""GET /quote/config: the public welcome message and nothing else, without a database."""

import dataclasses
from typing import Any

from fastapi.testclient import TestClient

from eventssound.application.agent_config import defaults_from_settings
from eventssound.application.messages_es import WELCOME
from eventssound.config import Settings
from eventssound.entrypoints.api.app import create_app
from fakes import InMemoryAgentConfigRepository, InMemorySecurityLog

URL = "/quote/config"


def build(repo: InMemoryAgentConfigRepository, **over: Any) -> tuple[TestClient, Settings]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://u:p@127.0.0.1:1/x",  # type: ignore[arg-type]
        llm_model="vendor/model-a",
        llm_model_allowlist="vendor/model-a,vendor/model-b",  # type: ignore[arg-type]
        **over,
    )
    app = create_app(
        settings,
        security_log=InMemorySecurityLog(),  # type: ignore[arg-type]
        agent_config_repository=repo,  # type: ignore[arg-type]
    )
    return TestClient(app), settings


def test_without_a_stored_config_it_returns_the_default_welcome() -> None:
    client, _ = build(InMemoryAgentConfigRepository())
    response = client.get(URL)  # no credentials: it is public
    assert response.status_code == 200
    assert response.json() == {"welcome_message": WELCOME}
    assert response.headers["Cache-Control"] == "public, max-age=30"


def test_a_stored_welcome_is_returned_and_nothing_else_leaks() -> None:
    repo = InMemoryAgentConfigRepository()
    client, settings = build(repo)
    repo.put(dataclasses.replace(defaults_from_settings(settings), welcome_message="Hola equipo"))
    body = client.get(URL).json()
    assert set(body) == {"welcome_message"}
    assert body["welcome_message"] == "Hola equipo"


def test_it_reads_the_cached_snapshot_not_the_database_per_request() -> None:
    repo = InMemoryAgentConfigRepository()
    client, _ = build(repo)
    for _ in range(5):
        client.get(URL)
    assert repo.reads == 1


def test_a_broken_store_falls_back_to_the_default() -> None:
    client, _ = build(InMemoryAgentConfigRepository(broken=True))
    assert client.get(URL).json() == {"welcome_message": WELCOME}


def test_a_failing_provider_never_raises() -> None:
    client, _ = build(InMemoryAgentConfigRepository())

    class Exploding:
        def current(self) -> None:
            raise RuntimeError("boom")

    client.app.state.agent_config = Exploding()  # type: ignore[attr-defined]
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json() == {"welcome_message": WELCOME}


def test_it_still_answers_when_the_chat_kill_switch_is_off() -> None:
    client, _ = build(InMemoryAgentConfigRepository(), chat_enabled=False)
    assert client.get(URL).status_code == 200
