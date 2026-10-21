"""Runtime abuse detection: security events and the temporary block on the chat.

Events hold a kind, a time and a hashed client key. Raw addresses, emails, passwords and message
text are never stored. A client that gets too many off-topic or injection refusals in a short
window is blocked from the chat until the window slides past them.
"""

import hashlib
import hmac
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from eventssound.application.quotes import Page

logger = logging.getLogger(__name__)

CHAT_REFUSED = "chat_refused"  # the agent refused: off-topic or injection attempt
LOGIN_FAILED = "login_failed"
# Only these two kinds are stored: both are bounded (by the block and by the login limiters).
# Blocked and rate-limited requests are only logged, so a flood cannot grow the table.

REFUSED_LIMIT = 5
# Admin-selectable `off_topic_policy` -> refusals allowed per window. Fixed in code.
REFUSED_LIMIT_BY_POLICY = {"normal": REFUSED_LIMIT, "strict": 3}
BLOCK_WINDOW = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class StoredEvent:
    id: int
    at: datetime
    kind: str
    client: str


class SecurityLog(Protocol):
    def add(self, kind: str, client: str, at: datetime) -> None: ...

    def count_since(self, kind: str, client: str, since: datetime) -> int: ...

    def page(self, limit: int, offset: int) -> Page[StoredEvent]:
        """Newest first."""
        ...

    def summary(self, since: datetime) -> dict[str, int]:
        """Events per kind since `since`."""
        ...


def derive_key(secret: str) -> bytes:
    """A key for client pseudonyms, bound to this purpose so the secret itself is never reused."""
    return hmac.new(secret.encode(), b"security-events-v1", hashlib.sha256).digest()


def client_key(ip: str, key: bytes) -> str:
    """Stable pseudonym of an address: 16 hex chars of HMAC-SHA256(key, ip)."""
    return hmac.new(key, ip.encode(), hashlib.sha256).hexdigest()[:16]


class AbuseGate:
    """Records security events and decides whether a client is temporarily blocked.

    Fail open: if the log cannot be read or written, `is_blocked` answers False and `record`
    swallows the error. The rate limiter and the daily budget stay the hard caps, so an outage of
    this log must not take the chat down. The block is a sliding window: it ends by itself
    `window` after the last counted refusal; blocked requests are not stored, so a blocked
    client cannot extend its own block.

    `enabled=False` turns the chat block off (no blocking, no refusal rows). It is for a
    deployment where every visitor would share one client key (behind a proxy whose address is
    not resolved), where a block would lock everyone out.
    """

    def __init__(
        self,
        log: SecurityLog,
        key: bytes,
        clock: Callable[[], datetime],
        enabled: bool = True,
        refused_limit: int = REFUSED_LIMIT,
        window: timedelta = BLOCK_WINDOW,
        limit_source: Callable[[], int] | None = None,
    ) -> None:
        self._log = log
        self._key = key
        self._enabled = enabled
        self._clock = clock
        self._limit = refused_limit
        self._limit_source = limit_source
        self._window = window

    def record(self, kind: str, ip: str) -> None:
        if kind == CHAT_REFUSED and not self._enabled:
            return
        try:
            self._log.add(kind, client_key(ip, self._key), self._clock())
        except Exception as error:
            logger.warning("security event not saved error=%s", type(error).__name__)

    def is_blocked(self, ip: str) -> bool:
        if not self._enabled:
            return False
        try:
            since = self._clock() - self._window
            limit = self._current_limit()
            return self._log.count_since(CHAT_REFUSED, client_key(ip, self._key), since) >= limit
        except Exception as error:
            logger.warning("abuse check failed open error=%s", type(error).__name__)
            return False

    def _current_limit(self) -> int:
        """The limit of the active policy, read per request; the fixed default if it fails."""
        if self._limit_source is None:
            return self._limit
        try:
            return self._limit_source()
        except Exception as error:  # noqa: BLE001  (fail-safe: keep the default limit)
            logger.warning("abuse limit source failed error=%s", type(error).__name__)
            return self._limit
