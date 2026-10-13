"""Ports and use case for the quote agent chat. No framework imports here: LangGraph
lives in `adapters/agent`, and everything pure (sanitizing, limits, the meter) stays
in this module so the pipeline can be re-run by a plain sequential runner if needed.
"""

import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

from eventssound.application.chat_input import sanitize_turns
from eventssound.application.llm import TokenUsage, estimate_cost_micro_usd, estimate_tokens
from eventssound.application.usage import RateLimiter, UsageBudget
from eventssound.domain.availability import AvailabilityReport
from eventssound.domain.event_request import EventRequest
from eventssound.domain.pricing import Quote

# Prompt scaffolding per LLM call (system prompt, schema); the floor for unreported usage.
_CALL_OVERHEAD_TOKENS = 300


class InvalidChat(Exception):
    """The chat history is structurally invalid (caps, roles, order)."""


class RateLimited(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate limited")
        self.retry_after_seconds = retry_after_seconds


class BudgetExhausted(Exception):
    """The daily LLM budget is exhausted or its store is down (fail closed)."""


class AgentLimitExceeded(Exception):
    """A hard bound was exceeded inside the agent (a bug, not user input)."""


class AgentStatus(StrEnum):
    CLARIFICATION = "clarification"
    QUOTE = "quote"
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str

    def __post_init__(self) -> None:
        if self.role not in ("user", "assistant"):
            raise ValueError("role must be 'user' or 'assistant'")
        if not self.content:
            raise ValueError("content must not be empty")


@dataclass(slots=True)
class UsageMeter:
    """Mutated in place by the agent so usage survives an exception that aborts the run."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    embed_calls: int = 0
    repairs: int = 0
    tools: list[str] = field(default_factory=list)
    node_ms: dict[str, int] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class AgentInput:
    turns: tuple[ChatTurn, ...]
    now: datetime
    request_id: str
    meter: UsageMeter
    deadline_monotonic: float


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    status: AgentStatus
    reply: str
    reply_source: Literal["llm", "template", "static"]
    quote: Quote | None
    event_request: EventRequest | None
    availability: AvailabilityReport | None
    missing_fields: tuple[str, ...]
    degraded: tuple[str, ...]


class QuoteAgent(Protocol):
    def run(self, data: AgentInput) -> AgentOutcome: ...


@dataclass(frozen=True, slots=True)
class ChatResult:
    outcome: AgentOutcome
    meter: UsageMeter


@dataclass(frozen=True, slots=True)
class ChatLimits:
    """Every chat bound in one frozen dataclass (defaults; the container may override)."""

    max_messages: int = 8
    max_message_chars: int = 1000
    max_total_chars: int = 4000
    max_llm_calls: int = 3
    request_token_ceiling: int = 8000
    deadline_seconds: float = 40
    input_price_micro_usd: int = 0
    output_price_micro_usd: int = 0


def quote_chat(
    turns: Sequence[ChatTurn],
    client_key: str,
    *,
    agent: QuoteAgent,
    budget: UsageBudget,
    limiter: RateLimiter,
    clock: Callable[[], datetime],
    limits: ChatLimits,
    request_id: str | None = None,
) -> ChatResult:
    """One chat request: rate limit -> sanitize -> reserve -> agent -> settle.

    `settle` always runs (also on agent failure), so a failed request releases the
    unused part of the reservation instead of losing it.
    """
    client = limiter.hit(client_key)
    if not client.allowed:
        # A denied client must not consume the global window: one noisy IP would starve everyone.
        raise RateLimited(client.retry_after_seconds)
    global_decision = limiter.hit("*") if client_key != "*" else client
    if not global_decision.allowed:
        raise RateLimited(global_decision.retry_after_seconds)

    try:
        pairs = sanitize_turns(
            tuple((turn.role, turn.content) for turn in turns),
            max_messages=limits.max_messages,
            max_message_chars=limits.max_message_chars,
            max_total_chars=limits.max_total_chars,
        )
    except ValueError as exc:
        raise InvalidChat(str(exc)) from exc
    clean = tuple(ChatTurn(role, content) for role, content in pairs)

    # Worst-case cost of the ceiling: reserving 0 would leave D34's cost cap unenforced.
    reserved_cost = -(-limits.request_token_ceiling // 1_000_000) * max(
        limits.input_price_micro_usd, limits.output_price_micro_usd
    )
    reservation = budget.reserve(limits.request_token_ceiling, reserved_cost)
    if reservation is None:
        raise BudgetExhausted()

    meter = UsageMeter()
    data = AgentInput(
        turns=clean,
        now=clock(),
        request_id=request_id or uuid.uuid4().hex,
        meter=meter,
        deadline_monotonic=time.monotonic() + limits.deadline_seconds,
    )
    try:
        outcome = agent.run(data)
    finally:
        prompt, completion = meter.prompt_tokens, meter.completion_tokens
        if meter.llm_calls and not meter.total_tokens:
            # A call was made but no usage came back (provider error after billing, timeout,
            # or a response without usage): settle an estimate, never zero.
            chars = sum(len(turn.content) for turn in clean)
            per_call = estimate_tokens(chars) + _CALL_OVERHEAD_TOKENS
            prompt = min(limits.request_token_ceiling, per_call * meter.llm_calls)
        cost = estimate_cost_micro_usd(
            TokenUsage(prompt, completion),
            limits.input_price_micro_usd,
            limits.output_price_micro_usd,
        )
        budget.settle(reservation, prompt + completion, cost)
    return ChatResult(outcome=outcome, meter=meter)
