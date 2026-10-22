"""Admin use cases over the agent configuration: read, plan a change and preview its risks.

A change is always planned the same way, from the request alone: the server recomputes the
field-by-field diff against the current version, so nothing the client computed is trusted.
Errors never carry values; field names only.
"""

import dataclasses
import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from eventssound.application.agent_config import AgentSettingsSource, defaults_from_settings
from eventssound.application.confirmation import hash_change
from eventssound.application.errors import VersionConflict
from eventssound.application.messages_es_agent_config import WARNINGS
from eventssound.application.ports import AgentConfigRepository
from eventssound.domain.agent_config import (
    HARD_MAX_DAILY_COST_MICRO_USD,
    HARD_MAX_DAILY_TOKENS,
    HARD_MAX_RATE_LIMIT_PER_MINUTE,
    AgentConfig,
    AuditEntry,
    StoredAgentConfig,
    validate_config,
    validate_note,
)
from eventssound.domain.errors import InvalidAgentConfig
from eventssound.domain.model_prices import ModelPrice, price_for

FIELDS = tuple(f.name for f in dataclasses.fields(AgentConfig))
TECHNICAL_FIELDS = frozenset(
    {"llm_model", "daily_token_cap", "daily_cost_cap_micro_usd", "chat_rate_limit_per_minute"}
)
TEXT_FIELDS = frozenset({"refusal_message", "closing_message", "welcome_message"})
BEHAVIOR_FIELDS = frozenset({"tone", "off_topic_policy"})
CEILINGS = {
    "max_daily_tokens": HARD_MAX_DAILY_TOKENS,
    "max_daily_cost_micro_usd": HARD_MAX_DAILY_COST_MICRO_USD,
    "max_rate_limit_per_minute": HARD_MAX_RATE_LIMIT_PER_MINUTE,
}
HISTORY_LOOKBACK = 200  # how many recent versions a rollback can target
Action = Literal["save", "rollback"]


class NoChanges(Exception):
    """The requested configuration equals the current one."""


class UnknownVersion(Exception):
    """A rollback target that is not among the recent versions."""


class AdminSettingsSource(AgentSettingsSource, Protocol):
    llm_provider: str
    llm_input_price_micro_usd_per_mtok: int
    llm_output_price_micro_usd_per_mtok: int
    llm_model_prices: Mapping[str, tuple[int, int]]

    @property
    def chat_active(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class ModelInUse:
    """What answers the chat. Never the base URL or any key."""

    provider: str
    model: str
    status: Literal["active", "disabled", "replay"]
    input_price_per_mtok: int
    output_price_per_mtok: int
    cost_cap_applies: bool
    free: bool = False


@dataclass(frozen=True, slots=True)
class CurrentConfig:
    config: AgentConfig
    version: int  # 0 means the Settings defaults, nothing stored
    updated_at: datetime | None
    updated_by: str | None


@dataclass(frozen=True, slots=True)
class Plan:
    action: Action
    base_version: int
    old: AgentConfig
    new: AgentConfig
    diff: dict[str, list[Any]]  # field -> [old, new]

    @property
    def requires_password(self) -> bool:
        return not TECHNICAL_FIELDS.isdisjoint(self.diff)

    @property
    def digest(self) -> str:
        return hash_change(self.action, self.diff)


@dataclass(frozen=True, slots=True)
class RiskWarning:
    code: str
    severity: Literal["info", "warning", "danger"]
    message_es: str


def failing_field(error: InvalidAgentConfig) -> str | None:
    """The config field (or `note`) a validation error names (messages start with it)."""
    word = str(error).split(" ", 1)[0]
    return word if word in (*FIELDS, "note") else None


_VALID = AgentConfig("neutral", "normal", "Hola.", "Gracias.", "Hola.", "vendor/model", 1, 1, 1)


def risk_warnings(plan: Plan, model: ModelInUse, estimate: int | None) -> list[RiskWarning]:
    found: list[tuple[str, Literal["info", "warning", "danger"]]] = []
    for name in ("daily_token_cap", "daily_cost_cap_micro_usd"):
        if name in plan.diff:
            before, after = plan.diff[name]
            if before > 0 and after > before:  # 0 means unmetered: any cap is a restriction
                found.append(
                    ("cap_raised_2x", "danger") if after > 2 * before else ("cap_raised", "warning")
                )
    if "llm_model" in plan.diff:
        found.append(("model_changed", "warning"))
    if "chat_rate_limit_per_minute" in plan.diff:
        before, after = plan.diff["chat_rate_limit_per_minute"]
        if after > before:
            found.append(("rate_limit_raised", "warning"))
    if not TEXT_FIELDS.isdisjoint(plan.diff):
        found.append(("texts_changed", "info"))
    if not BEHAVIOR_FIELDS.isdisjoint(plan.diff):
        found.append(("behavior_changed", "info"))
    if plan.requires_password and model.cost_cap_applies and "llm_model" in plan.diff:
        found.append(("paid_model_cost", "warning"))  # the new model spends against the cap
    if plan.requires_password and model.free:
        found.append(("free_model_limits", "info"))  # says the cost cap does not apply
    elif plan.requires_password and not model.cost_cap_applies and model.status != "replay":
        found.append(("cost_cap_not_binding", "warning"))
    if plan.requires_password and estimate is None:
        found.append(("cost_unknown", "danger" if "llm_model" in plan.diff else "warning"))
    found.append(("immediate_effect", "warning" if plan.requires_password else "info"))
    unique: dict[str, Any] = {}
    for code, severity in found:  # a cap raise may appear for both caps: one entry per code
        unique.setdefault(code, severity)
    return [RiskWarning(code, severity, WARNINGS[code]) for code, severity in unique.items()]


class AgentConfigAdmin:
    def __init__(self, repository: AgentConfigRepository, settings: AdminSettingsSource) -> None:
        self._repository = repository
        self._settings = settings

    @property
    def allowed_models(self) -> Collection[str]:
        return self._settings.allowed_llm_models

    @property
    def paid_models(self) -> list[str]:
        """The allowed models with a known, non-zero price: their spend counts against the cap."""
        prices = ((m, price_for(m, self._settings)) for m in self.allowed_models)
        return [
            m
            for m, price in prices
            if price is not None
            and not price.free
            and (price.input_micro_usd_per_mtok or price.output_micro_usd_per_mtok)
        ]

    @property
    def free_models(self) -> list[str]:
        """The allowed models that cost nothing, by the price table (not by the id alone)."""
        prices = ((m, price_for(m, self._settings)) for m in self.allowed_models)
        return [m for m, price in prices if price is not None and price.free]

    def current(self) -> CurrentConfig:
        """Fresh from storage (RepositoryUnavailable / InvalidStoredData propagate)."""
        stored = self._repository.get_active()
        if stored is None:
            return CurrentConfig(defaults_from_settings(self._settings), 0, None, None)
        user = stored.created_by_user_id
        return CurrentConfig(
            stored.config, stored.version, stored.created_at, None if user is None else str(user)
        )

    def model_in_use(self, config: AgentConfig) -> ModelInUse:
        s = self._settings
        if not s.chat_active:
            status = "disabled"
        else:
            status = "replay" if s.llm_provider == "replay" else "active"
        # Replay never calls a model: it keeps the environment model whatever is configured.
        model = s.llm_model if s.llm_provider == "replay" else config.llm_model
        # The price table, like the runtime: a model without a price keeps the environment pair.
        price = price_for(model, s) or ModelPrice(
            s.llm_input_price_micro_usd_per_mtok, s.llm_output_price_micro_usd_per_mtok, False
        )
        prices = (price.input_micro_usd_per_mtok, price.output_micro_usd_per_mtok)
        applies = s.llm_provider == "openrouter" and any(prices)
        return ModelInUse(s.llm_provider, model, status, *prices, applies, price.free)

    def max_daily_cost_estimate(self, config: AgentConfig) -> int | None:
        """Worst case per day in micro-USD: the cost cap, or what the token cap can cost.

        A free model costs 0, which is known. None when it is unknown: a model without a price, or
        prices left at 0 on a real provider for a model that is not free. The replay provider
        spends nothing, so 0 is its real answer.
        """
        s = self._settings
        if s.llm_provider == "replay":
            return 0
        table = price_for(config.llm_model, s)
        if table is None:
            return None
        if table.free:
            return 0
        price = max(table.input_micro_usd_per_mtok, table.output_micro_usd_per_mtok)
        if price == 0:
            return None
        by_tokens = math.ceil(config.daily_token_cap * price / 1_000_000)
        return min(config.daily_cost_cap_micro_usd, by_tokens)

    def out_of_bounds(self, config: AgentConfig) -> list[str]:
        """Every field that would fail validation (the environment defaults may be outside the
        bounds); each is swapped for a valid placeholder to find the next one."""
        bad: list[str] = []
        current = config
        for _ in FIELDS:
            try:
                validate_config(current, self.allowed_models)
                break
            except InvalidAgentConfig as error:
                name = failing_field(error)
                if name is None or name in bad:
                    break
                bad.append(name)
                fill = next(iter(self.allowed_models), config.llm_model)
                current = dataclasses.replace(
                    current, **{name: fill if name == "llm_model" else getattr(_VALID, name)}
                )
        return bad

    def plan(
        self,
        changes: Mapping[str, Any] | None,
        rollback_to_version: int | None,
        base_version: int,
        note: str | None = None,
    ) -> Plan:
        """The validated change from the current version (and its note, so a bad one is refused
        before a confirmation token is spent). Raises VersionConflict, InvalidAgentConfig,
        UnknownVersion or NoChanges."""
        validate_note(note)
        current = self.current()
        if base_version != current.version:
            raise VersionConflict
        if rollback_to_version is not None:
            target = next(
                (
                    s.config
                    for s in self._repository.history(HISTORY_LOOKBACK)
                    if s.version == rollback_to_version
                ),
                None,
            )
            if target is None:
                raise UnknownVersion
            candidate, action = target, "rollback"
        else:
            if not changes or not set(changes) <= set(FIELDS):
                raise InvalidAgentConfig("changes must name known fields")
            candidate, action = dataclasses.replace(current.config, **changes), "save"
        new = validate_config(candidate, self.allowed_models)
        diff = {
            name: [getattr(current.config, name), getattr(new, name)]
            for name in FIELDS
            if getattr(current.config, name) != getattr(new, name)
        }
        if not diff:
            raise NoChanges
        return Plan(action, base_version, current.config, new, diff)  # type: ignore[arg-type]

    def apply(self, plan: Plan, user_id: str, note: str | None) -> StoredAgentConfig:
        """Save the planned change as the next version (VersionConflict if it moved meanwhile)."""
        try:
            author: UUID | None = UUID(user_id)
        except ValueError:
            author = None
        return self._repository.save(
            plan.new, base_version=plan.base_version, user_id=author, note=note, action=plan.action
        )

    def history(self, limit: int) -> list[AuditEntry]:
        return self._repository.audit(limit)
