"""Strict argument schemas of the three tools.

`extra="forbid"` plus strict types: a smuggled field (`unit_price`, `total`, `discount_bps`) or a
coerced value (`"3"`, `true`) fails validation. There is deliberately no price field anywhere.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from eventssound.application.search import MAX_LIMIT, MAX_QUERY_CHARS, MIN_LIMIT
from eventssound.domain.catalog import EquipmentCategory
from eventssound.domain.event_request import (
    MAX_DISTANCE_KM,
    MAX_GUESTS,
    MAX_LINES,
    MAX_QUANTITY,
    EventRequest,
    EventType,
    RequestedLine,
    VenueType,
)

CODE_PATTERN = r"^[a-z0-9_]{3,64}$"
# Strict ISO-8601 with a mandatory offset: `fromisoformat` alone also accepts week dates, compact
# forms and, depending on the Python version, other shapes.
ISO_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def _enum_from_value(enum: type, value: Any) -> Any:
    """Models send enum values as strings; strict mode only accepts members, so convert str."""
    if type(value) is str:
        try:
            return enum(value)
        except ValueError:
            return value
    return value


class SearchArgs(_Strict):
    query: StrictStr = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    category: EquipmentCategory | None = None
    limit: StrictInt = Field(default=5, ge=MIN_LIMIT, le=MAX_LIMIT)

    @field_validator("category", mode="before")
    @classmethod
    def _category(cls, value: Any) -> Any:
        return _enum_from_value(EquipmentCategory, value)


class LineArgs(_Strict):
    code: StrictStr = Field(pattern=CODE_PATTERN)
    quantity: StrictInt = Field(ge=1, le=MAX_QUANTITY)


class EventRequestArgs(_Strict):
    event_type: EventType
    start: StrictStr = Field(pattern=ISO_PATTERN)
    end: StrictStr = Field(pattern=ISO_PATTERN)
    guest_count: StrictInt = Field(ge=1, le=MAX_GUESTS)
    distance_km: StrictInt = Field(ge=0, le=MAX_DISTANCE_KM)
    venue: VenueType
    items: list[LineArgs] = Field(default_factory=list, max_length=MAX_LINES)
    packages: list[LineArgs] = Field(default_factory=list, max_length=MAX_LINES)

    @field_validator("event_type", mode="before")
    @classmethod
    def _event_type(cls, value: Any) -> Any:
        return _enum_from_value(EventType, value)

    @field_validator("venue", mode="before")
    @classmethod
    def _venue(cls, value: Any) -> Any:
        return _enum_from_value(VenueType, value)

    @field_validator("start", "end")
    @classmethod
    def _aware_iso(cls, value: str) -> str:
        try:
            parsed = _parse(value)
            if parsed.utcoffset() is None:
                raise ValueError("datetime must carry a UTC offset")
            parsed.astimezone(UTC)  # offsets near the datetime limits overflow here
        except OverflowError:
            raise ValueError("datetime is out of the supported range") from None
        return value

    @model_validator(mode="after")
    def _line_count(self) -> "EventRequestArgs":
        if not 1 <= len(self.items) + len(self.packages) <= MAX_LINES:
            raise ValueError(f"a request needs 1..{MAX_LINES} lines")
        return self

    def to_domain(self) -> EventRequest:
        """Build the domain request; its own bounds (duration, order) raise DomainError."""
        return EventRequest(
            event_type=self.event_type,
            start=_parse(self.start),
            end=_parse(self.end),
            guest_count=self.guest_count,
            distance_km=self.distance_km,
            venue=self.venue,
            items=tuple(RequestedLine(line.code, line.quantity) for line in self.items),
            packages=tuple(RequestedLine(line.code, line.quantity) for line in self.packages),
        )


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)
