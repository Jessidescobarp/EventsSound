"""The `Extraction` model: the only data derived from raw user text that survives `understand`.

Strict by design (D8): `extra="forbid"`, bounded lengths, and a restricted character set so a
compromised model can only pass through data that is safe to echo to a user later.
"""

import re
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, field_validator

INTENTS = ("quote", "other")
EVENT_TYPES = ("wedding", "corporate", "birthday", "quinceanera", "graduation", "concert")
VENUES = ("indoor", "outdoor")

MAX_ITEMS = 8
MAX_NEEDS = 8
MAX_MENTION_CHARS = 80
MAX_NEED_CHARS = 60
MAX_LOCALITY_CHARS = 60
MAX_QUANTITY = 10_000
MAX_GUESTS = 100_000
MAX_DISTANCE_KM = 5_000
DURATION_MIN_HOURS = 0.5
DURATION_MAX_HOURS = 72

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# Letters, digits, spaces and . , ; : - / ' # % ( )  — anything else is refused.
_CHARSET = re.compile(r"^[A-Za-z0-9 .,;:/'#%()\-]+$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def _check_charset(value: str, field: str) -> str:
    if not _CHARSET.fullmatch(value):
        raise ValueError(f"{field} contains characters outside the allowed set")
    return value


class ItemMention(_Strict):
    mention: str = Field(min_length=1, max_length=MAX_MENTION_CHARS)
    quantity: StrictInt = Field(ge=1, le=MAX_QUANTITY)

    @field_validator("mention")
    @classmethod
    def _mention_charset(cls, value: str) -> str:
        return _check_charset(value, "mention")


class Extraction(_Strict):
    intent: str = Field(pattern="quote|other")
    event_type: str | None = Field(default=None, pattern="|".join(EVENT_TYPES))
    event_date: str | None = Field(default=None, pattern=_DATE.pattern)
    start_time: str | None = Field(default=None, pattern=_TIME.pattern)
    end_time: str | None = Field(default=None, pattern=_TIME.pattern)
    duration_hours: float | None = Field(default=None, ge=DURATION_MIN_HOURS, le=DURATION_MAX_HOURS)
    end_date: str | None = Field(default=None, pattern=_DATE.pattern)
    guest_count: StrictInt | None = Field(default=None, ge=1, le=MAX_GUESTS)
    distance_km: StrictInt | None = Field(default=None, ge=0, le=MAX_DISTANCE_KM)
    locality: str | None = Field(default=None, max_length=MAX_LOCALITY_CHARS)
    venue: str | None = Field(default=None, pattern="|".join(VENUES))
    items: list[ItemMention] = Field(default_factory=list, max_length=MAX_ITEMS)
    needs: list[Annotated[str, StringConstraints(min_length=1, max_length=MAX_NEED_CHARS)]] = Field(
        default_factory=list, max_length=MAX_NEEDS
    )

    @field_validator("event_date", "end_date")
    @classmethod
    def _real_date(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("date must be a real calendar date") from None
        return value

    @field_validator("locality")
    @classmethod
    def _locality_charset(cls, value: str | None) -> str | None:
        return None if value is None else _check_charset(value, "locality")

    @field_validator("needs")
    @classmethod
    def _needs_charset(cls, values: list[str]) -> list[str]:
        for value in values:
            _check_charset(value, "needs")
        return values
