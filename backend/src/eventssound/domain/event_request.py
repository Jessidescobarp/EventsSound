"""Event request: the validated input of pricing and availability.

The bounds are module constants, not rule data: the agent builds requests from untrusted text,
and the limits also cap every day-iteration loop in the domain.
"""

import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from .errors import InvalidEventRequest

_CODE = re.compile(r"[a-z0-9_]{3,64}")  # same format as catalog codes

MAX_DURATION = timedelta(days=31)
MAX_GUESTS = 100_000
MAX_DISTANCE_KM = 5_000
MAX_QUANTITY = 10_000
MAX_LINES = 100


class EventType(StrEnum):
    WEDDING = "wedding"
    CORPORATE = "corporate"
    BIRTHDAY = "birthday"
    QUINCEANERA = "quinceanera"
    GRADUATION = "graduation"
    CONCERT = "concert"
    OTHER = "other"


class VenueType(StrEnum):
    INDOOR = "indoor"
    OUTDOOR = "outdoor"


def _require_int(value: object, name: str) -> int:
    if type(value) is not int:
        raise InvalidEventRequest(f"{name} must be an int")
    return value


def _require_aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise InvalidEventRequest(f"{name} must be a timezone-aware datetime")


@dataclass(frozen=True, slots=True)
class RequestedLine:
    """A catalog code (item or package) and how many units are requested."""

    code: str
    quantity: int

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not _CODE.fullmatch(self.code):
            raise InvalidEventRequest("code must match ^[a-z0-9_]{3,64}$")
        if not 1 <= _require_int(self.quantity, "quantity") <= MAX_QUANTITY:
            raise InvalidEventRequest(f"quantity must be within 1..{MAX_QUANTITY}")


def _as_lines(value: object, name: str) -> tuple["RequestedLine", ...]:
    """Coerce to a tuple of RequestedLine; a string is never an iterable of lines."""
    if isinstance(value, str | bytes):
        raise InvalidEventRequest(f"{name} must be a collection of RequestedLine")
    try:
        lines = tuple(value)  # type: ignore[call-overload]
    except TypeError:
        raise InvalidEventRequest(f"{name} must be a collection of RequestedLine") from None
    if not all(isinstance(line, RequestedLine) for line in lines):
        raise InvalidEventRequest(f"{name} must contain only RequestedLine")
    return lines


def _merge(lines: tuple[RequestedLine, ...]) -> tuple[RequestedLine, ...]:
    totals = Counter[str]()
    for line in lines:
        totals[line.code] += line.quantity
    return tuple(RequestedLine(code, totals[code]) for code in sorted(totals))


@dataclass(frozen=True, slots=True)
class EventRequest:
    """What the customer asks for. The event spans the half-open interval [start, end)."""

    event_type: EventType
    start: datetime
    end: datetime
    guest_count: int
    distance_km: int
    venue: VenueType
    items: tuple[RequestedLine, ...] = ()
    packages: tuple[RequestedLine, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", _as_lines(self.items, "items"))
        object.__setattr__(self, "packages", _as_lines(self.packages, "packages"))
        if not isinstance(self.event_type, EventType):
            raise InvalidEventRequest("event_type must be an EventType")
        if not isinstance(self.venue, VenueType):
            raise InvalidEventRequest("venue must be a VenueType")
        _require_aware(self.start, "start")
        _require_aware(self.end, "end")
        # Compare absolute instants: shared-tzinfo arithmetic is wall-clock and ignores folds/DST.
        span = self.end.astimezone(UTC) - self.start.astimezone(UTC)
        if span <= timedelta(0):
            raise InvalidEventRequest("end must be after start")
        if span > MAX_DURATION:
            raise InvalidEventRequest("event must last at most 31 days")
        if not 1 <= _require_int(self.guest_count, "guest_count") <= MAX_GUESTS:
            raise InvalidEventRequest(f"guest_count must be within 1..{MAX_GUESTS}")
        if not 0 <= _require_int(self.distance_km, "distance_km") <= MAX_DISTANCE_KM:
            raise InvalidEventRequest(f"distance_km must be within 0..{MAX_DISTANCE_KM}")
        line_count = len(self.items) + len(self.packages)
        if not 1 <= line_count <= MAX_LINES:
            raise InvalidEventRequest(f"a request needs 1..{MAX_LINES} lines")

    def normalized(self) -> "EventRequest":
        """Merge duplicate codes (quantities summed) and sort by code."""
        return replace(self, items=_merge(self.items), packages=_merge(self.packages))
