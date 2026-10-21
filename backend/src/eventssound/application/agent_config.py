"""Fallback and fail-safe loading of the admin-editable agent configuration."""

import logging
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Protocol

from eventssound.application.messages_es import REFUSAL, TEMPLATE_CLOSING, WELCOME
from eventssound.application.ports import AgentConfigRepository
from eventssound.domain.agent_config import AgentConfig, validate_config

logger = logging.getLogger("eventssound.agent_config")


class AgentSettingsSource(Protocol):
    """The slice of Settings the fallback reads (the real Settings satisfies it)."""

    llm_model: str
    llm_daily_token_cap: int
    llm_daily_cost_cap_micro_usd: int
    chat_rate_limit_per_minute: int

    @property
    def allowed_llm_models(self) -> Collection[str]: ...


@dataclass(frozen=True)
class ActiveAgentConfig:
    config: AgentConfig
    version: int  # 0 means "defaults from Settings", nothing stored


def defaults_from_settings(settings: AgentSettingsSource) -> AgentConfig:
    """Today's behavior, built from trusted environment values.

    These are NOT validated, so they may be outside `validate_config` bounds (0 means unmetered,
    a rate limit above 60). An editor must not preload them into a form and save them blindly.
    """
    return AgentConfig(
        tone="neutral",
        off_topic_policy="normal",
        refusal_message=REFUSAL,
        closing_message=TEMPLATE_CLOSING,
        welcome_message=WELCOME,
        llm_model=settings.llm_model,
        daily_token_cap=settings.llm_daily_token_cap,
        daily_cost_cap_micro_usd=settings.llm_daily_cost_cap_micro_usd,
        chat_rate_limit_per_minute=settings.chat_rate_limit_per_minute,
    )


def load_active_config(
    repository: AgentConfigRepository, settings: AgentSettingsSource
) -> ActiveAgentConfig:
    """The stored config, or the Settings defaults when it is missing, unreadable or invalid.

    Never raises: the chat must keep working with today's behavior. Logs the failure class only,
    never stored values.
    """
    try:
        stored = repository.get_active()
        if stored is not None:
            config = validate_config(stored.config, settings.allowed_llm_models)
            return ActiveAgentConfig(config, stored.version)
    except Exception as error:  # noqa: BLE001  (fail-safe by contract)
        logger.warning("agent config unavailable, using defaults: %s", type(error).__name__)
    return ActiveAgentConfig(defaults_from_settings(settings), 0)


DEFAULT_TTL_SECONDS = 15.0


class ActiveConfigProvider:
    """A cached snapshot of the active config, refreshed after a short TTL.

    Safe to call from many threads and on every request: the fast path takes no lock, a single
    thread refreshes while the others keep using the previous snapshot, and a failed refresh
    keeps the last good snapshot (the Settings defaults when there never was one). `current`
    never raises. A refresh that returns the defaults (nothing stored, or a read that failed or
    no longer validates) does not replace a stored config seen before: rows are never deleted,
    so that case is a failure, and the chat must not silently change behavior because of it.
    """

    def __init__(
        self,
        repository: AgentConfigRepository,
        settings: AgentSettingsSource,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._snapshot: ActiveAgentConfig | None = None
        self._expires_at = float("-inf")
        self._generation = 0

    @property
    def version(self) -> int:
        return self.current().version

    def invalidate(self) -> None:
        """The next `current` reloads; a load already running is not trusted to be fresh."""
        self._generation += 1
        self._expires_at = float("-inf")

    def current(self) -> ActiveAgentConfig:
        snapshot = self._snapshot
        if snapshot is not None and self._clock() < self._expires_at:
            return snapshot
        # One thread refreshes; the rest serve the stale snapshot instead of queueing on the DB.
        if not self._lock.acquire(blocking=snapshot is None):
            assert snapshot is not None
            return snapshot
        try:
            return self._refresh()
        finally:
            self._lock.release()

    def _refresh(self) -> ActiveAgentConfig:
        previous = self._snapshot
        if previous is not None and self._clock() < self._expires_at:
            return previous  # another thread refreshed while this one waited
        generation = self._generation
        try:
            loaded = load_active_config(self._repository, self._settings)
        except Exception:  # noqa: BLE001  (defensive: current() must never raise)
            loaded = ActiveAgentConfig(defaults_from_settings(self._settings), 0)
        if previous is not None and previous.version > 0 and loaded.version == 0:
            loaded = previous
        self._snapshot = loaded
        # An invalidate during the load leaves the snapshot expired so the next call reloads.
        self._expires_at = (
            self._clock() + self._ttl if generation == self._generation else float("-inf")
        )
        return loaded
