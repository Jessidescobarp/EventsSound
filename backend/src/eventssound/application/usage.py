"""Ports for the daily LLM budget and the request rate limiter."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Reservation:
    """A reserved slice of the daily budget, released by `settle`."""

    day: date
    tokens: int
    cost_micro_usd: int


class UsageBudget(Protocol):
    """Daily token and cost budget. `reserve` returns None when the budget is exhausted."""

    def reserve(self, tokens: int, cost_micro_usd: int) -> Reservation | None: ...

    def settle(
        self, reservation: Reservation, actual_tokens: int, actual_cost_micro_usd: int
    ) -> None:
        """Replace the reserved slice with the actual usage (also called after failures)."""
        ...


@dataclass(frozen=True, slots=True)
class RateDecision:
    allowed: bool
    retry_after_seconds: int


class RateLimiter(Protocol):
    """Record one request for a key and decide whether it is allowed."""

    def hit(self, key: str) -> RateDecision: ...
