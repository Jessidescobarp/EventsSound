"""POST /quote/chat through the production wiring: container -> graph agent -> Postgres.

Only the HTTP transport of OpenRouter is faked. Every other piece is the one production builds,
so a wiring default that unit tests override (like `AgentDeps.token_factory`) cannot hide.
"""

import functools
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.agent.nodes import AgentDeps
from eventssound.adapters.db.seed import seed_catalog
from eventssound.adapters.db.seed_data import SEED_BOOKINGS, SEED_ITEMS, SEED_PACKAGES
from eventssound.config import Settings
from eventssound.entrypoints.api import container
from eventssound.entrypoints.api.app import create_app

EXTRACTION = {
    "distance_km": 45,
    "duration_hours": 3.5,
    "end_date": "2026-10-17",
    "end_time": "23:30",
    "event_date": "2026-10-17",
    "event_type": "birthday",
    "guest_count": 150,
    "intent": "quote",
    "items": [
        {"mention": "parlantes activos de 15 pulgadas", "quantity": 2},
        {"mention": "mezcladora de 16 canales", "quantity": 1},
    ],
    "locality": None,
    "needs": [],
    "start_time": "20:00",
    "venue": None,
}
BODY = {"messages": [{"role": "user", "content": "Necesito 2 parlantes y 1 mezcladora el sabado."}]}


def test_default_token_factory_is_a_callable_that_yields_a_fresh_token() -> None:
    deps = AgentDeps(*([None] * 5), limits=None, timezone=None)  # type: ignore[arg-type]
    assert deps.token_factory() != deps.token_factory()


def test_chat_answers_200_with_the_production_wiring(
    session_factory: sessionmaker[Session],
    migrated_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_catalog(session_factory, SEED_ITEMS, SEED_PACKAGES, SEED_BOOKINGS)

    def handler(request: httpx.Request) -> httpx.Response:
        structured = "response_format" in json.loads(request.content)
        text = json.dumps(EXTRACTION) if structured else "Hola, esta es tu cotizacion."
        usage = {"prompt_tokens": 1200, "completion_tokens": 300}
        message = {"role": "assistant", "content": text}
        choice = {"index": 0, "finish_reason": "stop", "message": message}
        return httpx.Response(200, json={"model": "m/x", "choices": [choice], "usage": usage})

    monkeypatch.setattr(
        container,
        "OpenRouterProvider",
        functools.partial(container.OpenRouterProvider, transport=httpx.MockTransport(handler)),
    )
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="production",
        DATABASE_URL=migrated_database,  # type: ignore[call-arg]
        llm_provider="openrouter",
        llm_model="vendor/model",
        openrouter_api_key=SecretStr("sk-or-test-key-0000000000"),
        llm_input_price_micro_usd_per_mtok=94_000,
        llm_output_price_micro_usd_per_mtok=250_000,
    )

    response = TestClient(create_app(settings)).post("/quote/chat", json=BODY)

    assert response.status_code == 200, response.text
