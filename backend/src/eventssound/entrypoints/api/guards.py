"""Chat guards.

`ChatBodyGuard` is an ASGI middleware scoped to `POST /quote/chat`: it answers the kill switch
(503) and an oversized body (413) BEFORE FastAPI buffers or parses anything, counting the bytes
as they stream in (a missing or lying Content-Length does not help). The fail-closed wrappers
turn an error in the rate limiter or the budget into a refusal: never serve uncapped LLM spend.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from eventssound.application.llm import LlmUnavailable
from eventssound.application.messages_es_chat import CHAT_ERRORS
from eventssound.application.quote_chat import RateLimited
from eventssound.application.usage import RateDecision, RateLimiter, Reservation, UsageBudget
from eventssound.config import Settings

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 16 * 1024
CHAT_PATH = "/quote/chat"


class ChatRefusal(Exception):
    """A guard refused the request; the app handler renders the public body."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def chat_guard(request: Request) -> None:
    """Route-level backstop for the kill switch (the middleware normally answers first)."""
    if not request.app.state.settings.chat_active:
        raise ChatRefusal(503, "chat_disabled")


def _refusal(status: int, code: str) -> JSONResponse:
    body = {"detail": code, "message": CHAT_ERRORS[code]}
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


class ChatBodyGuard:
    def __init__(self, app: ASGIApp, settings: Settings, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.settings = settings
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != CHAT_PATH:
            await self.app(scope, receive, send)
            return
        if not self.settings.chat_active:
            await _refusal(503, "chat_disabled")(scope, receive, send)
            return
        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0  # malformed: the streaming count below still applies
        if declared > self.max_bytes:
            await _refusal(413, "payload_too_large")(scope, receive, send)
            return

        received = 0
        rejected = False

        async def counted_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    rejected = True
                    await _refusal(413, "payload_too_large")(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            if not rejected:  # the app's own answer to the aborted read is dropped
                await send(message)

        await self.app(scope, counted_receive, guarded_send)


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
