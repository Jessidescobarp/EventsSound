"""ActiveConfigProvider: TTL cache, invalidate, last-good snapshot and fail-safe fallback."""

import threading
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from eventssound.application.agent_config import ActiveConfigProvider, defaults_from_settings
from eventssound.application.errors import RepositoryUnavailable
from eventssound.domain.agent_config import AgentConfig, StoredAgentConfig

SETTINGS = SimpleNamespace(
    llm_model="vendor/model-a",
    llm_daily_token_cap=100_000,
    llm_daily_cost_cap_micro_usd=1_000_000,
    chat_rate_limit_per_minute=5,
    allowed_llm_models=("vendor/model-a", "vendor/model-b"),
)
DEFAULTS = defaults_from_settings(SETTINGS)


def stored(version: int, **changes: object) -> StoredAgentConfig:
    config: AgentConfig = replace(DEFAULTS, **changes)
    return StoredAgentConfig(config, version, datetime(2026, 10, 20, tzinfo=UTC), None)


class FakeRepo:
    def __init__(self, active: StoredAgentConfig | None = None) -> None:
        self.active: StoredAgentConfig | None = active
        self.error: Exception | None = None
        self.calls = 0

    def get_active(self) -> StoredAgentConfig | None:
        self.calls += 1
        if self.error:
            raise self.error
        return self.active


class Clock:
    now = 100.0

    def __call__(self) -> float:
        return self.now


def make(repo: FakeRepo, ttl: float = 15.0) -> tuple[ActiveConfigProvider, Clock]:
    clock = Clock()
    return ActiveConfigProvider(repo, SETTINGS, ttl_seconds=ttl, clock=clock), clock  # type: ignore[arg-type]


def test_empty_table_is_the_settings_defaults_and_is_cached_within_the_ttl() -> None:
    repo = FakeRepo()
    provider, clock = make(repo)
    first = provider.current()
    clock.now += 14.9
    assert provider.current() is first
    assert (first.config, first.version, repo.calls) == (DEFAULTS, 0, 1)


def test_reloads_after_the_ttl_and_picks_up_the_new_version() -> None:
    repo = FakeRepo()
    provider, clock = make(repo)
    assert provider.version == 0
    repo.active = stored(2, daily_token_cap=7)
    clock.now += 15.0  # boundary: a snapshot is fresh only strictly before the TTL
    assert (provider.version, provider.current().config.daily_token_cap) == (2, 7)
    assert repo.calls == 2


def test_invalidate_forces_the_next_call_to_reload() -> None:
    repo = FakeRepo(stored(1))
    provider, _ = make(repo)
    provider.current()
    repo.active = stored(2)
    provider.invalidate()
    assert provider.version == 2 and repo.calls == 2


def test_invalidate_during_a_load_leaves_the_snapshot_expired() -> None:
    repo = FakeRepo(stored(1))
    provider, _ = make(repo)
    original = repo.get_active

    def invalidating() -> StoredAgentConfig | None:
        result = original()
        provider.invalidate()  # an apply lands while this (older) read is in flight
        return result

    repo.get_active = invalidating  # type: ignore[method-assign]
    provider.current()
    repo.get_active = original  # type: ignore[method-assign]
    repo.active = stored(2)
    assert provider.version == 2


@pytest.mark.parametrize(
    "error", [RepositoryUnavailable(), RuntimeError("boom")], ids=["unavailable", "unexpected"]
)
def test_failure_keeps_the_last_good_snapshot_and_backs_off_for_a_ttl(error: Exception) -> None:
    repo = FakeRepo(stored(3, daily_token_cap=9))
    provider, clock = make(repo)
    assert provider.version == 3
    repo.error = error
    clock.now += 20
    assert provider.current().config.daily_token_cap == 9
    calls = repo.calls
    provider.current()
    assert repo.calls == calls  # a dead database is not hammered on every request


def test_failure_without_a_good_snapshot_serves_the_defaults() -> None:
    repo = FakeRepo()
    repo.error = RepositoryUnavailable()
    provider, _ = make(repo)
    assert (provider.current().config, provider.version) == (DEFAULTS, 0)


def test_a_stored_config_that_stops_validating_does_not_revert_to_defaults() -> None:
    repo = FakeRepo(stored(3, daily_token_cap=9))
    provider, clock = make(repo)
    provider.current()
    repo.active = stored(4, daily_token_cap=2_000_000)  # above the hard ceiling
    clock.now += 20
    assert (provider.version, provider.current().config.daily_token_cap) == (3, 9)


def test_other_threads_get_the_stale_snapshot_while_one_refreshes() -> None:
    repo = FakeRepo(stored(1))
    provider, clock = make(repo)
    first = provider.current()
    clock.now += 20
    entered, release = threading.Event(), threading.Event()
    original = repo.get_active

    def blocked() -> StoredAgentConfig | None:
        entered.set()
        assert release.wait(timeout=5)
        return original()

    repo.get_active = blocked  # type: ignore[method-assign]
    refresher = threading.Thread(target=provider.current)
    refresher.start()
    assert entered.wait(timeout=5)  # a refresh is now in flight, stuck in the repository
    try:
        assert provider.current() is first  # served at once from the stale snapshot
    finally:
        release.set()
        refresher.join(timeout=5)
