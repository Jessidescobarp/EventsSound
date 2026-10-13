"""Client-side pacing for a rate-limited provider (free OpenRouter models: 20 requests/minute)."""

import time
from collections.abc import Callable

from eventssound.application.llm import LlmProvider, LlmRequest, LlmResponse

MARGIN = 1.05  # 5% slower than the limit: clock drift and server-side windows are not exact


class PacedProvider:
    """Spaces the START of consecutive requests by `60 / rpm` seconds (plus a margin)."""

    def __init__(
        self,
        inner: LlmProvider,
        *,
        rpm: int = 20,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rpm < 1:
            raise ValueError("rpm must be >= 1")
        self.interval = 60 / rpm * MARGIN
        self.requests = 0
        self._inner, self._clock, self._sleep = inner, clock, sleep
        self._last: float | None = None

    def complete(self, request: LlmRequest) -> LlmResponse:
        if self._last is not None:
            wait = self._last + self.interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()
        self.requests += 1
        return self._inner.complete(request)
