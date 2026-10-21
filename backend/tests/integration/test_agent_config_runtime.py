"""The chat reads the ACTIVE agent config at runtime and behaves as today when none is stored."""

import dataclasses
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient

from eventssound.application.agent_config import defaults_from_settings
from eventssound.application.quote_chat import AgentOutcome, AgentStatus
from eventssound.config import Settings
from eventssound.entrypoints.api import container
from eventssound.entrypoints.api.app import create_app
from fakes import InMemoryAgentConfigRepository, InMemorySecurityLog

URL = "/quote/chat"
BODY = {"messages": [{"role": "user", "content": "Necesito sonido para 100 personas"}]}


class FakeAgent:
    def run(self, data: Any) -> AgentOutcome:
        return AgentOutcome(AgentStatus.CLARIFICATION, "Hola", "static", None, None, None, (), ())


def make(repo: InMemoryAgentConfigRepository, **parts: Any) -> tuple[TestClient, Settings]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://u:p@127.0.0.1:1/x",  # type: ignore[arg-type]
        llm_model="vendor/model-a",
        llm_model_allowlist="vendor/model-a,vendor/model-b",  # type: ignore[arg-type]
    )
    app = create_app(
        settings,
        quote_agent=FakeAgent(),  # type: ignore[arg-type]
        security_log=InMemorySecurityLog(),  # type: ignore[arg-type]
        agent_config_repository=repo,  # type: ignore[arg-type]
        **parts,
    )
    return TestClient(app), settings


def stored(repo: InMemoryAgentConfigRepository, settings: Settings, **changes: Any) -> None:
    repo.put(dataclasses.replace(defaults_from_settings(settings), **changes))


def test_without_a_stored_config_the_chat_answers_as_before() -> None:
    client, _ = make(InMemoryAgentConfigRepository())
    assert client.post(URL, json=BODY).status_code == 200
    assert client.app.state.agent_config.version == 0  # type: ignore[attr-defined]


def test_a_broken_config_store_never_breaks_the_chat() -> None:
    client, _ = make(InMemoryAgentConfigRepository(broken=True))
    assert client.post(URL, json=BODY).status_code == 200


@pytest.mark.parametrize(
    ("changes", "status"),
    [({}, 200), ({"daily_token_cap": 1}, 503)],
    ids=["same-as-env", "tiny-token-cap"],
)
def test_the_stored_daily_caps_govern_the_budget(changes: dict[str, int], status: int) -> None:
    repo = InMemoryAgentConfigRepository()
    client, settings = make(repo)
    stored(repo, settings, **changes)
    response = client.post(URL, json=BODY)
    assert response.status_code == status
    if status == 503:
        assert response.json()["detail"] == "daily_budget_exhausted"


def test_an_applied_change_takes_effect_after_invalidate() -> None:
    repo = InMemoryAgentConfigRepository()
    client, settings = make(repo)
    assert client.post(URL, json=BODY).status_code == 200
    stored(repo, settings, daily_token_cap=1)
    provider: Callable[[], None] = client.app.state.agent_config.invalidate  # type: ignore[attr-defined]
    provider()
    assert client.post(URL, json=BODY).status_code == 503


@pytest.mark.parametrize(
    ("limit", "statuses"),
    [(None, [200] * 5 + [429]), (2, [200, 200, 429]), (8, [200] * 8 + [429])],
    ids=["env-default-5", "lowered-to-2", "raised-to-8"],
)
def test_the_stored_per_minute_limit_governs_the_chat_rate_limit(
    limit: int | None, statuses: list[int]
) -> None:
    repo = InMemoryAgentConfigRepository()
    client, settings = make(repo)
    if limit is not None:
        stored(repo, settings, chat_rate_limit_per_minute=limit)
    assert [client.post(URL, json=BODY).status_code for _ in statuses] == statuses


class CountingBuild:
    def __init__(self) -> None:
        self.models: list[str] = []

    def __call__(self, model: str) -> Any:
        self.models.append(model)
        return FakeAgent()


def test_a_model_change_rebuilds_the_agent_exactly_once() -> None:
    build, live = CountingBuild(), ["vendor/a"]
    lazy = container.LazyQuoteAgent(build, lambda: live[0])
    for _ in range(3):
        lazy.run(None)  # type: ignore[arg-type]
    assert build.models == ["vendor/a"]
    live[0] = "vendor/b"
    for _ in range(3):
        lazy.run(None)  # type: ignore[arg-type]
    assert build.models == ["vendor/a", "vendor/b"]
    lazy.reset()  # the catalog-change reset still works and rebuilds with the current model
    lazy.run(None)  # type: ignore[arg-type]
    assert build.models == ["vendor/a", "vendor/b", "vendor/b"]


def test_concurrent_requests_after_a_model_change_share_one_rebuild() -> None:
    build, live = CountingBuild(), ["vendor/a"]
    lazy = container.LazyQuoteAgent(build, lambda: live[0])
    lazy.run(None)  # type: ignore[arg-type]
    live[0] = "vendor/b"
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _: lazy.run(None), range(32)))  # type: ignore[arg-type]
    assert build.models == ["vendor/a", "vendor/b"]


def test_a_failing_model_source_keeps_the_agent_already_built() -> None:
    build, live = CountingBuild(), ["vendor/a"]

    def source() -> str:
        if live[0] == "down":
            raise RuntimeError("config store down")
        return live[0]

    lazy = container.LazyQuoteAgent(build, source)
    lazy.run(None)  # type: ignore[arg-type]
    live[0] = "down"
    lazy.run(None)  # type: ignore[arg-type]
    assert build.models == ["vendor/a"]


def test_without_a_model_source_the_build_takes_no_argument() -> None:
    built: list[int] = []
    lazy = container.LazyQuoteAgent(lambda: built.append(1) or FakeAgent())  # type: ignore[arg-type,return-value]
    lazy.run(None)  # type: ignore[arg-type]
    lazy.run(None)  # type: ignore[arg-type]
    assert built == [1]


def test_the_provider_uses_the_active_model_but_keeps_provider_and_key_in_settings() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://u:p@127.0.0.1:1/x",  # type: ignore[arg-type]
        llm_provider="openrouter",
        llm_model="vendor/env",
        openrouter_api_key="sk-test-key",  # type: ignore[arg-type]
    )
    assert "vendor/active" in repr(container.make_llm_provider(settings, "vendor/active"))
    assert "vendor/env" in repr(container.make_llm_provider(settings))
    assert "sk-test-key" not in repr(container.make_llm_provider(settings, "vendor/active"))


def test_replay_never_rebuilds_on_a_model_edit() -> None:
    repo = InMemoryAgentConfigRepository()
    client, settings = make(repo)
    agent = container.make_quote_agent(settings, None, client.app.state.agent_config)  # type: ignore[arg-type,attr-defined]
    source = agent._model_source  # type: ignore[attr-defined]
    before = source()
    stored(repo, settings, llm_model="vendor/model-b")
    client.app.state.agent_config.invalidate()  # type: ignore[attr-defined]
    assert client.app.state.agent_config.current().config.llm_model == "vendor/model-b"  # type: ignore[attr-defined]
    assert source() == before == "vendor/model-a"


def test_a_late_thread_with_a_stale_model_does_not_rebuild_over_a_newer_one() -> None:
    build = CountingBuild()
    stale_next = [False]

    def source() -> str:
        if stale_next[0]:  # the unlocked read of a request that started before the switch to B
            stale_next[0] = False
            return "vendor/a"
        return "vendor/b"

    lazy = container.LazyQuoteAgent(build, source)
    lazy.run(None)  # type: ignore[arg-type]  # builds B
    stale_next[0] = True
    # The late request sees A outside the lock; inside it must re-read, find B and keep it.
    lazy.run(None)  # type: ignore[arg-type]
    assert build.models == ["vendor/b"]


def test_a_failing_rebuild_keeps_serving_the_previous_agent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    live, failing = ["vendor/a"], [False]

    def build(model: str) -> Any:
        if failing[0]:
            raise RuntimeError("catalog down sk-secret-123")
        return FakeAgent()

    lazy = container.LazyQuoteAgent(build, lambda: live[0])
    lazy.run(None)  # type: ignore[arg-type]
    first = lazy._built  # type: ignore[attr-defined]
    live[0], failing[0] = "vendor/b", True
    with caplog.at_level("WARNING"):
        lazy.run(None)  # type: ignore[arg-type]
    assert lazy._built is first  # type: ignore[attr-defined]  # the stale pair stays
    assert "RuntimeError" in caplog.text and "sk-secret-123" not in caplog.text
    failing[0] = False
    lazy.run(None)  # type: ignore[arg-type]
    assert lazy._built[1] == "vendor/b"  # type: ignore[attr-defined]  # recovered on retry


def test_a_failing_first_build_still_propagates() -> None:
    def build(model: str) -> Any:
        raise RuntimeError("boom")

    lazy = container.LazyQuoteAgent(build, lambda: "vendor/a")
    with pytest.raises(RuntimeError):
        lazy.run(None)  # type: ignore[arg-type]
