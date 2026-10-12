"""The validated input of `BookingRepository.find_reservations`, shared by every implementation."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime

from eventssound.domain.errors import InvalidAvailability


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise InvalidAvailability(f"{name} must be a timezone-aware datetime")
    try:
        return value.astimezone(UTC)
    except OverflowError:
        raise InvalidAvailability(f"{name} is out of the supported range") from None


@dataclass(frozen=True, slots=True, init=False)
class ReservationQuery:
    """Item codes and a half-open window `[window_start, window_end)`, normalized to UTC."""

    item_codes: frozenset[str]
    window_start: datetime
    window_end: datetime

    def __init__(
        self, item_codes: Collection[str], window_start: datetime, window_end: datetime
    ) -> None:
        if isinstance(item_codes, str | bytes):
            raise InvalidAvailability("item_codes must be a collection of codes")
        try:
            codes = frozenset(item_codes)
        except TypeError:
            raise InvalidAvailability("item_codes must be a collection of codes") from None
        if not all(isinstance(code, str) for code in codes):
            raise InvalidAvailability("item_codes must contain only strings")
        start, end = _utc(window_start, "window_start"), _utc(window_end, "window_end")
        if end <= start:
            raise InvalidAvailability("window_end must be after window_start")
        object.__setattr__(self, "item_codes", codes)
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)
