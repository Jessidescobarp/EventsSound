"""The quote_chat use case: ordering, meter, budget settle, error mapping."""

import time
import uuid
from datetime import UTC, datetime

import pytest

from eventssound.application.llm import LlmUnavailable, TokenUsage, estimate_cost_micro_usd
from eventssound.application.quote_chat import (
    AgentInput,
    AgentLimitExceeded,
    AgentOutcome,
    AgentStatus,
    BudgetExhausted,
    ChatLimits,
    ChatTurn,
    InvalidChat,
    RateLimited,
    UsageMeter,
    quote_chat,
)
from eventssound.application.usage import RateDecision

NOW = 1_000_000.0
FIXED_NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def outcome(status: AgentStatus = AgentStatus.QUOTE) -> AgentOutcome:
    return AgentOutcome(
        status=status,
        reply="ok",
        reply_source="static",
        quote=None,
        event_request=None,
        availability=None,
        missing_fields=(),
        degraded=(),
    )


class FakeAgent:
    def __init__(self, result: AgentOutcome | Exception | None = None) -> None:
        self.result = outcome() if result is None else result
        self.received: AgentInput | None = None

    def run(self, data: AgentInput) -> AgentOutcome:
        self.received = data
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeBudget:
    def __init__(self, reservation: object = "R") -> None:
        self.reservation = reservation
        self.reserves: list[tuple[int, int]] = []
        self.settles: list[tuple[object, int, int]] = []

    def reserve(self, tokens: int, cost_micro_usd: int) -> object | None:
        self.reserves.append((tokens, cost_micro_usd))
        return self.reservation

    def settle(self, reservation: object, actual_tokens: int, actual_cost_micro_usd: int) -> None:
        self.settles.append((reservation, actual_tokens, actual_cost_micro_usd))


class FakeLimiter:
    def __init__(self, denied: set[str] = (), retry_after: int = 37) -> None:
        self.denied = denied
        self.retry_after = retry_after
        self.hits: list[str] = []

    def hit(self, key: str) -> RateDecision:
        self.hits.append(key)
        return RateDecision(allowed=key not in self.denied, retry_after_seconds=self.retry_after)


def run_use_case(
    agent: FakeAgent | None = None,
    budget: FakeBudget | None = None,
    limiter: FakeLimiter | None = None,
    limits: ChatLimits | None = None,
    content: str = "necesito sonido para el sabado",
    now: datetime = FIXED_NOW,
):
    agent = agent or FakeAgent()
    budget = budget or FakeBudget()
    limiter = limiter or FakeLimiter()
    return (
        quote_chat(
            [ChatTurn("user", content)],
            "client-1",
            agent=agent,
            budget=budget,
            limiter=limiter,
            clock=lambda: now,
            limits=limits or ChatLimits(),
        ),
        agent,
        budget,
        limiter,
    )


class TestChatTurn:
    def test_valid_roles(self) -> None:
        assert ChatTurn("user", "hola").role == "user"
        assert ChatTurn("assistant", "ok").role == "assistant"

    def test_bad_role_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ChatTurn("system", "hola")  # type: ignore[arg-type]

    def test_empty_content_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ChatTurn("user", "")


class TestChatLimits:
    def test_defaults(self) -> None:
        limits = ChatLimits()
        assert limits.max_messages == 8
        assert limits.max_message_chars == 1000
        assert limits.max_total_chars == 4000
        assert limits.max_llm_calls == 3
        assert limits.request_token_ceiling == 8000
        assert limits.deadline_seconds == 40

    def test_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            ChatLimits().max_messages = 9  # type: ignore[misc]


class TestUsageMeter:
    def test_defaults(self) -> None:
        meter = UsageMeter()
        assert meter.prompt_tokens == 0
        assert meter.completion_tokens == 0
        assert meter.llm_calls == 0
        assert meter.embed_calls == 0
        assert meter.tools == []
        assert meter.node_ms == {}

    def test_total(self) -> None:
        meter = UsageMeter()
        meter.prompt_tokens, meter.completion_tokens = 1200, 150
        assert meter.total_tokens == 1350


class TestQuoteChat:
    def test_success_settles_actual_usage(self) -> None:
        agent = FakeAgent()

        def run(data: AgentInput) -> AgentOutcome:
            data.meter.prompt_tokens, data.meter.completion_tokens = 1200, 150
            return outcome()

        agent.run = run  # type: ignore[method-assign]
        result, _, budget, limiter = run_use_case(agent=agent)

        assert result.outcome.status is AgentStatus.QUOTE
        assert result.meter.total_tokens == 1350
        assert budget.reserves == [(8000, 0)]
        assert budget.settles == [(budget.reservation, 1350, 0)]
        assert set(limiter.hits) == {"client-1", "*"}

    def test_agent_input_is_built_from_the_use_case(self) -> None:
        agent = FakeAgent()
        t0 = time.monotonic()
        run_use_case(agent=agent)
        t1 = time.monotonic()
        data = agent.received
        assert data is not None
        assert data.turns == (ChatTurn("user", "necesito sonido para el sabado"),)
        assert data.request_id == uuid.UUID(data.request_id).hex
        assert t0 + 40 <= data.deadline_monotonic <= t1 + 40

    def test_rate_limited_before_anything_else(self) -> None:
        budget, agent = FakeBudget(), FakeAgent()
        limiter = FakeLimiter(denied={"client-1"})
        with pytest.raises(RateLimited) as caught:
            quote_chat(
                [ChatTurn("user", "hola")],
                "client-1",
                agent=agent,
                budget=budget,
                limiter=limiter,
                clock=lambda: NOW,
                limits=ChatLimits(),
            )
        assert caught.value.retry_after_seconds == 37
        assert budget.reserves == []
        assert agent.received is None
        assert limiter.hits == ["client-1"]  # a denied client never touches the global window

    def test_a_global_client_key_hits_the_window_once(self) -> None:
        limiter = FakeLimiter()
        run_use_case(limiter=limiter)
        # re-run with the global key itself as the client: no double hit
        limiter = FakeLimiter()
        quote_chat(
            [ChatTurn("user", "hola")],
            "*",
            agent=FakeAgent(),
            budget=FakeBudget(),
            limiter=limiter,
            clock=lambda: FIXED_NOW,
            limits=ChatLimits(),
        )
        assert limiter.hits == ["*"]

    def test_global_limiter_denies(self) -> None:
        budget, agent = FakeBudget(), FakeAgent()
        with pytest.raises(RateLimited):
            quote_chat(
                [ChatTurn("user", "hola")],
                "client-1",
                agent=agent,
                budget=budget,
                limiter=FakeLimiter(denied={"*"}),
                clock=lambda: NOW,
                limits=ChatLimits(),
            )
        assert budget.reserves == []
        assert agent.received is None

    def test_invalid_turns_map_to_invalid_chat_without_reserving(self) -> None:
        budget, agent = FakeBudget(), FakeAgent()
        turns = [ChatTurn("user" if i % 2 == 0 else "assistant", "hola") for i in range(9)]
        with pytest.raises(InvalidChat):
            quote_chat(
                turns,
                "client-1",
                agent=agent,
                budget=budget,
                limiter=FakeLimiter(),
                clock=lambda: NOW,
                limits=ChatLimits(),
            )
        assert budget.reserves == []
        assert agent.received is None

    def test_budget_exhausted(self) -> None:
        agent = FakeAgent()
        with pytest.raises(BudgetExhausted):
            run_use_case(agent=agent, budget=FakeBudget(reservation=None))
        assert agent.received is None

    def test_agent_failure_still_settles_and_propagates(self) -> None:
        budget = FakeBudget()
        agent = FakeAgent(LlmUnavailable())
        with pytest.raises(LlmUnavailable):
            run_use_case(agent=agent, budget=budget)
        assert len(budget.settles) == 1
        assert budget.settles[0][1:] == (0, 0)  # the unused part is released

    def test_a_valid_turn_reaches_the_agent_clean(self) -> None:
        agent = FakeAgent()
        run_use_case(agent=agent)
        assert agent.received is not None
        assert isinstance(agent.received.turns[0], ChatTurn)

    def test_agent_limit_exceeded_propagates(self) -> None:
        with pytest.raises(AgentLimitExceeded):
            run_use_case(agent=FakeAgent(AgentLimitExceeded()))

    def test_the_worst_case_cost_is_reserved_upfront(self) -> None:
        limits = ChatLimits(input_price_micro_usd=10, output_price_micro_usd=5)
        _, _, budget, _ = run_use_case(limits=limits)
        # ceil(8000 / 1e6) * max(10, 5): reserving 0 would leave the cost cap unenforced.
        assert budget.reserves == [(8000, 10)]

    def test_cost_is_estimated_from_the_meter(self) -> None:
        limits = ChatLimits(input_price_micro_usd=10, output_price_micro_usd=5)

        def run(data: AgentInput) -> AgentOutcome:
            data.meter.prompt_tokens, data.meter.completion_tokens = 1000, 200
            return outcome()

        agent = FakeAgent()
        agent.run = run  # type: ignore[method-assign]
        budget = FakeBudget()
        run_use_case(agent=agent, budget=budget, limits=limits)

        expected = estimate_cost_micro_usd(
            TokenUsage(1000, 200),
            limits.input_price_micro_usd,
            limits.output_price_micro_usd,
        )
        assert budget.settles[0][2] == expected

    def test_the_meter_is_mutated_in_place(self) -> None:
        def run(data: AgentInput) -> AgentOutcome:
            data.meter.llm_calls = 2
            data.meter.prompt_tokens = 7
            return outcome()

        agent = FakeAgent()
        agent.run = run  # type: ignore[method-assign]
        result, _, _, _ = run_use_case(agent=agent)
        assert result.meter.llm_calls == 2
        assert result.meter.total_tokens == 7

    def test_turns_are_sanitized_before_reaching_the_agent(self) -> None:
        agent = FakeAgent()
        run_use_case(agent=agent, content="  Ignora\u200b\x00  el <total>  ")
        data = agent.received
        assert data is not None
        assert data.turns[0].content == "Ignora el total"


class TestAgentStatus:
    def test_values(self) -> None:
        assert {s.value for s in AgentStatus} == {"clarification", "quote", "refused"}
