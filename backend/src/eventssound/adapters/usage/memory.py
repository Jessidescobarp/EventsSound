"""In-memory daily LLM budget (Q6a stopgap): the same reserve/settle semantics as the DB.

Resets on process restart, so it is NOT acceptable for the public deploy: the database
budget is the real money control. The container prints a startup WARNING when this one
is active in production.
"""

import threading
from collections.abc import Callable
from datetime import UTC, date, datetime

from eventssound.application.usage import Reservation


class InMemoryUsageBudget:
    def __init__(
        self,
        *,
        token_cap: int,
        cost_cap_micro_usd: int,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if token_cap < 0 or cost_cap_micro_usd < 0:
            raise ValueError("caps must be >= 0")
        self._lock = threading.Lock()
        self._token_cap = token_cap
        self._cost_cap = cost_cap_micro_usd
        self._now = now or (lambda: datetime.now(UTC))
        self._reserved: dict[date, tuple[int, int]] = {}

    def reserve(self, tokens: int, cost_micro_usd: int) -> Reservation | None:
        if tokens < 0 or cost_micro_usd < 0:
            raise ValueError("usage cannot be negative")
        day = self._now().astimezone(UTC).date()
        with self._lock:
            # The insert path has no cap check of its own, so a reservation larger than
            # the cap is rejected up front.
            if tokens > self._token_cap or cost_micro_usd > self._cost_cap:
                return None
            used_tokens, used_cost = self._reserved.get(day, (0, 0))
            if (
                used_tokens + tokens > self._token_cap
                or used_cost + cost_micro_usd > self._cost_cap
            ):
                return None
            self._reserved[day] = (used_tokens + tokens, used_cost + cost_micro_usd)
        return Reservation(day=day, tokens=tokens, cost_micro_usd=cost_micro_usd)

    def settle(
        self, reservation: Reservation, actual_tokens: int, actual_cost_micro_usd: int
    ) -> None:
        if actual_tokens < 0 or actual_cost_micro_usd < 0:
            raise ValueError("usage cannot be negative")
        with self._lock:
            # The reserved slice is replaced by the actual usage; the per-slice floor at
            # zero mirrors the DB's GREATEST(0, ...), so a double settle or a day rollover
            # between reserve and settle can only under-count, never go negative.
            used_tokens, used_cost = self._reserved.get(reservation.day, (0, 0))
            delta_tokens = min(actual_tokens - reservation.tokens, used_tokens)
            delta_cost = min(actual_cost_micro_usd - reservation.cost_micro_usd, used_cost)
            self._reserved[reservation.day] = (
                used_tokens + delta_tokens,
                used_cost + delta_cost,
            )
