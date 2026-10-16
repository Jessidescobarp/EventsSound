"""Runtime abuse detection: security events and the temporary block on the chat.

Events hold a kind, a time and a hashed client key. Raw addresses, emails, passwords and message
text are never stored. A client that gets too many off-topic or injection refusals in a short
window is blocked from the chat until the window slides past them.
"""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from eventssound.application.quotes import Page

logger = logging.getLogger(__name__)

CHAT_REFUSED = "chat_refused"  # the agent refused: off-topic or injection attempt
CHAT_RATE_LIMITED = "chat_rate_limited"
LOGIN_FAILED = "login_failed"
CHAT_BLOCKED = "chat_blocked"  # a request turned away by the temporary block

REFUSED_LIMIT = 5
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


def client_key(ip: str, salt: str) -> str:
    """Stable pseudonym of an address: 16 hex chars of sha256(salt:ip). The address is not kept."""
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:16]


class AbuseGate:
    """Records security events and decides whether a client is temporarily blocked.

    Fail open: if the log cannot be read or written, `is_blocked` answers False and `record`
    swallows the error. The rate limiter and the daily budget stay the hard caps, so an outage of
    this log must not take the chat down. The block is a sliding window: it ends by itself
    `window` after the last counted refusal. `CHAT_BLOCKED` events are kept for visibility but
    do not count toward the limit, so a blocked client cannot extend its own block.
    """

    def __init__(
        self,
        log: SecurityLog,
        salt: str,
        clock: Callable[[], datetime],
        refused_limit: int = REFUSED_LIMIT,
        window: timedelta = BLOCK_WINDOW,
    ) -> None:
        self._log = log
        self._salt = salt
        self._clock = clock
        self._limit = refused_limit
        self._window = window

    def record(self, kind: str, ip: str) -> None:
        try:
            self._log.add(kind, client_key(ip, self._salt), self._clock())
        except Exception as error:
            logger.warning("security event not saved error=%s", type(error).__name__)

    def is_blocked(self, ip: str) -> bool:
        try:
            since = self._clock() - self._window
            return self._log.count_since(CHAT_REFUSED, client_key(ip, self._salt), since) >= (
                self._limit
            )
        except Exception as error:
            logger.warning("abuse check failed open error=%s", type(error).__name__)
            return False
