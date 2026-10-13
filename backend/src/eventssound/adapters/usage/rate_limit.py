"""In-memory sliding-window rate limiter behind the `RateLimiter` port (D31).

State is per process and resets on restart: it is burst control, not a money control (the
daily budget is). Client keys are hashed with a per-process salt, so no address is kept in
memory structures or logs. The global key `*` has its own, higher limit.
"""

import hashlib
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable

from eventssound.application.usage import RateDecision

GLOBAL_KEY = "*"
MINUTE = 60
HOUR = 3600
_PURGE_EVERY = 256


class InMemoryRateLimiter:
    def __init__(
        self,
        per_minute: int,
        *,
        per_hour: int = 40,
        global_per_minute: int = 30,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min(per_minute, per_hour, global_per_minute, max_keys) < 1:
            raise ValueError("limits and max_keys must be >= 1")
        self._client_windows = ((MINUTE, per_minute), (HOUR, max(per_hour, per_minute)))
        self._global_windows = ((MINUTE, global_per_minute),)
        self._max_keys = max_keys
        self._clock = clock
        self._salt = secrets.token_bytes(16)
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}
        self._calls = 0

    def hit(self, key: str) -> RateDecision:
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        windows = self._global_windows if key == GLOBAL_KEY else self._client_windows
        name = key if key == GLOBAL_KEY else self._digest(key)
        now = self._clock()
        with self._lock:
            self._calls += 1
            if self._calls % _PURGE_EVERY == 0:
                self._purge(now)
            stamps = self._hits.get(name)
            if stamps is None:
                if len(self._hits) >= self._max_keys:
                    self._purge(now)
                if len(self._hits) >= self._max_keys:
                    # Fail closed under key flooding instead of growing without bound.
                    return RateDecision(False, MINUTE)
                stamps = self._hits[name] = deque()
            longest = max(window for window, _ in windows)
            while stamps and stamps[0] <= now - longest:
                stamps.popleft()
            retry = 0.0
            for window, limit in windows:
                inside = [t for t in stamps if t > now - window]
                if len(inside) >= limit:
                    retry = max(retry, inside[-limit] + window - now)
            if retry > 0:
                return RateDecision(False, max(1, int(retry) + 1))
            stamps.append(now)
            return RateDecision(True, 0)

    def _digest(self, key: str) -> str:
        return hashlib.blake2s(key.encode(), key=self._salt, digest_size=8).hexdigest()

    def _purge(self, now: float) -> None:
        longest = max(window for window, _ in self._client_windows)
        for name in [n for n, s in self._hits.items() if not s or s[-1] <= now - longest]:
            del self._hits[name]
