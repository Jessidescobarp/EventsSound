"""Saved quotes and the paginated reads behind `/me/quotes` and `/admin/*`.

Quotes are saved automatically by the chat route (the server is the only writer, so there is
no public endpoint that accepts client-built quote JSON). Only the validated quote and event
fields are kept: no message text, reply, address, name or email.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


@dataclass(frozen=True, slots=True)
class NewQuote:
    user_id: str | None
    event_type: str
    event_start: datetime
    event_end: datetime
    guest_count: int
    total_cop: int
    available: bool | None
    quote: dict[str, Any]
    event_request: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StoredQuote:
    id: str
    created_at: datetime
    registered: bool  # saved while a user was logged in
    owner_email: str | None  # that account's email (demo accounts only); None when anonymous
    event_type: str
    event_start: datetime
    event_end: datetime
    guest_count: int
    total_cop: int
    available: bool | None
    quote: dict[str, Any]
    event_request: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BookingRow:
    booking_code: str
    item_code: str
    quantity: int
    starts_at: datetime
    ends_at: datetime
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: tuple[T, ...]
    total: int
    limit: int
    offset: int


class QuoteStore(Protocol):
    def add(self, quote: NewQuote) -> str: ...

    def page(self, user_id: str | None, limit: int, offset: int) -> Page[StoredQuote]:
        """Newest first (`created_at DESC, id DESC`); `user_id` None means every quote."""
        ...


class BookingLister(Protocol):
    def page(self, limit: int, offset: int) -> Page[BookingRow]: ...


def record_quote(store: QuoteStore, quote: NewQuote) -> str | None:
    """Best effort: a storage failure is logged by class and never blocks the chat answer."""
    try:
        return store.add(quote)
    except Exception as error:
        logger.warning("quote not saved error=%s", type(error).__name__)
        return None
