"""Fallback and fail-safe loading of the admin-editable agent configuration."""

import logging
from collections.abc import Collection
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
