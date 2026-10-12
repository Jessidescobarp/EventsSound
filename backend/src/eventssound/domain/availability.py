"""Stock availability over time: a pure function of in-memory bookings.

Intervals are half-open `[start, end)` over absolute instants. Two uses of one unit must be at
least `buffer` apart, which is the same as expanding every interval by `buffer / 2` on both sides
and testing plain overlap. Units are interchangeable, so the units needed are the peak number of
concurrently expanded intervals (a sweep line), never the sum of all overlapping bookings.
"""

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from .catalog import MAX_INT32, Catalog, EquipmentItem
from .errors import InvalidAvailability, InvalidRules
from .event_request import EventRequest

_ITEM_CODE = re.compile(r"[a-z0-9_]{3,64}")  # same format as catalog codes
_BOOKING_CODE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_MINUTE = timedelta(minutes=1)
MAX_BUFFER = timedelta(days=7)


class BookingStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"

    @classmethod
    def blocking(cls) -> frozenset["BookingStatus"]:
        """Statuses that consume stock: pending holds it conservatively, cancelled frees it."""
        return frozenset({cls.PENDING, cls.CONFIRMED})


def _utc(value: object, name: str) -> datetime:
    """The absolute instant of an aware datetime; anything else is a domain error."""
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise InvalidAvailability(f"{name} must be a timezone-aware datetime")
    try:
        return value.astimezone(UTC)
    except OverflowError:
        raise InvalidAvailability(f"{name} is out of the supported range") from None


def _shift(value: datetime, delta: timedelta) -> datetime:
    try:
        return value + delta
    except OverflowError:
        raise InvalidAvailability("datetime is out of the supported range") from None


def _require_quantity(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise InvalidAvailability(f"{name} must be an int >= 1")
    return value


def _check_interval(start: object, end: object) -> tuple[datetime, datetime]:
    utc_start, utc_end = _utc(start, "start"), _utc(end, "end")
    if utc_end <= utc_start:
        raise InvalidAvailability("end must be after start")
    return utc_start, utc_end


@dataclass(frozen=True, slots=True)
class Booking:
    """One reserved item of one booking over `[start, end)`."""

    code: str
    item_code: str
    quantity: int
    start: datetime
    end: datetime
    status: BookingStatus

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not _BOOKING_CODE.fullmatch(self.code):
            raise InvalidAvailability("booking code must match [A-Za-z0-9_-]{1,64}")
        if not isinstance(self.item_code, str) or not _ITEM_CODE.fullmatch(self.item_code):
            raise InvalidAvailability("item_code must match [a-z0-9_]{3,64}")
        if _require_quantity(self.quantity, "quantity") > MAX_INT32:
            raise InvalidAvailability(f"quantity must be at most {MAX_INT32}")
        _check_interval(self.start, self.end)
        if not isinstance(self.status, BookingStatus):
            raise InvalidAvailability("status must be a BookingStatus")


@dataclass(frozen=True, slots=True)
class AvailabilityRules:
    """Availability rule data. `buffer` is the minimum gap between two uses of one unit."""

    buffer: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.buffer, timedelta):
            raise InvalidRules("buffer must be a timedelta")
        if not timedelta(0) <= self.buffer <= MAX_BUFFER:
            raise InvalidRules("buffer must be within 0..7 days")
        if self.buffer % _MINUTE:
            raise InvalidRules("buffer must be a whole number of minutes")


def default_availability_rules() -> AvailabilityRules:
    """Synthetic default: two hours between two uses of the same unit."""
    return AvailabilityRules(buffer=timedelta(hours=2))


@dataclass(frozen=True, slots=True)
class Availability:
    """Availability of one item for one interval, with the numbers needed to explain it."""

    item_code: str
    requested: int
    stock: int
    remaining: int

    def __post_init__(self) -> None:
        if not isinstance(self.item_code, str) or not _ITEM_CODE.fullmatch(self.item_code):
            raise InvalidAvailability("item_code must match [a-z0-9_]{3,64}")
        _require_quantity(self.requested, "requested")
        if type(self.stock) is not int or self.stock < 0:
            raise InvalidAvailability("stock must be an int >= 0")
        if type(self.remaining) is not int or not 0 <= self.remaining <= self.stock:
            raise InvalidAvailability("remaining must be an int within 0..stock")

    @property
    def is_available(self) -> bool:
        return self.remaining >= self.requested

    @property
    def shortfall(self) -> int:
        """Units missing to satisfy the request (0 when available)."""
        return max(0, self.requested - self.remaining)


@dataclass(frozen=True, slots=True)
class AvailabilityReport:
    """Per-item availability of a whole request, sorted by item code."""

    items: tuple[Availability, ...]

    def __post_init__(self) -> None:
        if isinstance(self.items, str | bytes):
            raise InvalidAvailability("items must be a collection of Availability")
        try:
            items = tuple(self.items)
        except TypeError:
            raise InvalidAvailability("items must be a collection of Availability") from None
        object.__setattr__(self, "items", items)
        if not items or not all(isinstance(item, Availability) for item in items):
            raise InvalidAvailability("items must be a non-empty collection of Availability")
        codes = [item.item_code for item in items]
        if codes != sorted(set(codes)):
            raise InvalidAvailability("items must be sorted by code with no duplicates")

    @property
    def is_available(self) -> bool:
        return all(item.is_available for item in self.items)

    @property
    def shortages(self) -> tuple[Availability, ...]:
        """The limiting items: those that cannot satisfy the requested quantity."""
        return tuple(item for item in self.items if not item.is_available)


def _as_bookings(value: object) -> tuple[Booking, ...]:
    """Coerce to a tuple of Booking; a string is never an iterable of bookings."""
    if isinstance(value, str | bytes):
        raise InvalidAvailability("bookings must be a collection of Booking")
    try:
        bookings = tuple(value)  # type: ignore[call-overload]
    except TypeError:
        raise InvalidAvailability("bookings must be a collection of Booking") from None
    if not all(isinstance(booking, Booking) for booking in bookings):
        raise InvalidAvailability("bookings must contain only Booking")
    return bookings


def _check_rules(rules: object) -> AvailabilityRules:
    if not isinstance(rules, AvailabilityRules):
        raise InvalidAvailability("rules must be AvailabilityRules")
    return rules


def booking_search_window(
    start: datetime, end: datetime, rules: AvailabilityRules
) -> tuple[datetime, datetime]:
    """UTC window `[start - buffer, end + buffer)` holding every booking that can affect a request.

    Computed on absolute instants (never wall-clock arithmetic in the request's zone). Storage
    adapters query this window; `available_units` selects bookings with the very same bounds.
    """
    utc_start, utc_end = _check_interval(start, end)
    buffer = _check_rules(rules).buffer
    return _shift(utc_start, -buffer), _shift(utc_end, buffer)


def available_units(
    item: EquipmentItem,
    start: datetime,
    end: datetime,
    bookings: Iterable[Booking],
    rules: AvailabilityRules,
) -> int:
    """Units of `item` free for the whole of `[start, end)`: stock minus peak concurrent use.

    `(code, item_code)` is expected to be unique per booking: a duplicated row counts twice,
    which errs toward unavailable. Bookings are first selected on their raw UTC bounds, so a
    booking far from the window never raises; one that does overlap the window but cannot be
    expanded by the buffer without leaving the datetime range fails closed with a domain error.
    """
    if not isinstance(item, EquipmentItem):
        raise InvalidAvailability("item must be an EquipmentItem")
    utc_start, utc_end = _check_interval(start, end)
    half = _check_rules(rules).buffer / 2
    held = _as_bookings(bookings)
    near_lo, near_hi = booking_search_window(utc_start, utc_end, rules)
    blocking = BookingStatus.blocking()
    events: list[tuple[datetime, int]] = []
    for booking in held:
        if booking.item_code != item.code or booking.status not in blocking:
            continue
        b_start, b_end = _utc(booking.start, "start"), _utc(booking.end, "end")
        # Expanded overlap `b_start - half < end + half` is `b_start < end + buffer`.
        if b_start < near_hi and b_end > near_lo:
            events.append((_shift(b_start, -half), booking.quantity))
            events.append((_shift(b_end, half), -booking.quantity))
    # Sorting by (time, delta) puts releases before acquisitions at the same instant.
    events.sort()
    in_use = peak = 0
    for _, delta in events:
        in_use += delta
        peak = max(peak, in_use)
    return max(0, item.stock_quantity - peak)


def check_availability(
    item: EquipmentItem,
    start: datetime,
    end: datetime,
    bookings: Iterable[Booking],
    rules: AvailabilityRules,
    quantity: int = 1,
) -> Availability:
    """Is `quantity` of `item` free for `[start, end)`? Cancelled bookings never count."""
    _require_quantity(quantity, "quantity")
    remaining = available_units(item, start, end, bookings, rules)
    return Availability(item.code, quantity, item.stock_quantity, remaining)


def required_units(request: EventRequest, catalog: Catalog) -> dict[str, int]:
    """Units needed per item code: loose items plus package members, sorted by code."""
    if not isinstance(request, EventRequest):
        raise InvalidAvailability("request must be an EventRequest")
    if not isinstance(catalog, Catalog):
        raise InvalidAvailability("catalog must be a Catalog")
    units = Counter[str]()
    for line in request.items:
        units[catalog.item(line.code).code] += line.quantity
    for line in request.packages:
        for member in catalog.package(line.code).lines:
            units[member.item_code] += member.quantity * line.quantity
    return {code: units[code] for code in sorted(units)}


def check_request_availability(
    request: EventRequest,
    catalog: Catalog,
    bookings: Iterable[Booking],
    rules: AvailabilityRules,
) -> AvailabilityReport:
    """Check every item a request needs; packages need each member in the requested quantity."""
    units = required_units(request, catalog)
    held = _as_bookings(bookings)
    return AvailabilityReport(
        tuple(
            check_availability(catalog.item(code), request.start, request.end, held, rules, needed)
            for code, needed in units.items()
        )
    )
