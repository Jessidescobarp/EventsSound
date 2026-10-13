"""Chat guards: the kill switch and body-size check run as route dependencies, so a disabled
or flooded service answers before the body is parsed. The fail-closed wrappers turn an error
in the rate limiter or the budget into a refusal: never serve uncapped LLM spend."""

import logging

from fastapi import Request

from eventssound.application.llm import LlmUnavailable
from eventssound.application.quote_chat import RateLimited
from eventssound.application.usage import RateDecision, RateLimiter, Reservation, UsageBudget

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 16 * 1024


class ChatRefusal(Exception):
    """A guard refused the request; the app handler renders the public body."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def chat_guard(request: Request) -> None:
    if not request.app.state.settings.chat_active:
        raise ChatRefusal(503, "chat_disabled")
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        declared = 0  # chunked or malformed: the Pydantic bounds still apply after parsing
    if declared > MAX_BODY_BYTES:
        raise ChatRefusal(413, "payload_too_large")


class FailClosedLimiter:
    def __init__(self, inner: RateLimiter) -> None:
        self._inner = inner

    def hit(self, key: str) -> RateDecision:
        try:
            return self._inner.hit(key)
        except Exception:
            logger.error("rate limiter failed; refusing the request")
            raise RateLimited(60) from None


class FailClosedBudget:
    def __init__(self, inner: UsageBudget) -> None:
        self._inner = inner

    def reserve(self, tokens: int, cost_micro_usd: int) -> Reservation | None:
        try:
            return self._inner.reserve(tokens, cost_micro_usd)
        except Exception:
            logger.error("budget store failed; refusing the request")
            raise LlmUnavailable() from None

    def settle(self, reservation: Reservation, actual_tokens: int, actual_cost: int) -> None:
        try:
            self._inner.settle(reservation, actual_tokens, actual_cost)
        except Exception:
            # The answer is already computed; an unsettled reservation only over-counts.
            logger.error("budget settle failed; the reservation stays counted")
