"""Deterministic parsing of Spanish quote facts: clock times, guest counts and durations.

Like `spanish_dates`, the agent owns these instead of trusting a weak model: the extraction is
stateless, so a turn that only picks an option ("Paquete Boda") must not erase earlier facts.
"""

import re
import unicodedata

_MERIDIEM = r"(a\.?\s?m\.?|p\.?\s?m\.?)"
# "8 PM", "8:30 p. m.", "20:00", "20:00:00" (seconds ignored). A bare "8" is never a time.
_CLOCK = re.compile(rf"\b(\d{{1,2}})(?::([0-5]\d))?(?::[0-5]\d)?\s*{_MERIDIEM}?(?![\w:])")
_GUESTS = re.compile(r"\b(\d{1,6})\s*(?:personas|invitados|asistentes|pax|huespedes)\b")
_HOURS = re.compile(r"\b(\d{1,2}(?:[.,]\d)?)\s*(?:horas?|hrs|hs)\b")
_MAX_GUESTS = 100_000


def fold(text: str) -> str:
    """Lower-case without accents, for accent- and case-insensitive comparison."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _to_hhmm(hour: int, minute: int, meridiem: str | None) -> str | None:
    if meridiem is not None:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem.startswith("p") else 0)
    if not (0 <= hour <= 23):
        return None
    return f"{hour:02d}:{minute:02d}"


def parse_clock_times(text: str) -> list[str]:
    """Every clock time in `text` as "HH:MM". Needs a colon or an AM/PM marker."""
    found: list[str] = []
    for match in _CLOCK.finditer(fold(text)):
        hour, minute, meridiem = int(match.group(1)), match.group(2), match.group(3)
        if minute is None and meridiem is None:
            continue
        result = _to_hhmm(hour, int(minute or 0), meridiem)
        if result is not None:
            found.append(result)
    return found


def parse_clock_time(text: str) -> str | None:
    """The first clock time in `text` as "HH:MM", or None."""
    return next(iter(parse_clock_times(text)), None)


def parse_guest_count(text: str) -> int | None:
    """The first "N personas/invitados" count in `text`, or None."""
    match = _GUESTS.search(fold(text))
    if match is None:
        return None
    count = int(match.group(1))
    return count if 1 <= count <= _MAX_GUESTS else None


def parse_duration_hours(text: str) -> float | None:
    """The first "N horas" duration in `text` (0.5..72), or None."""
    match = _HOURS.search(fold(text))
    if match is None:
        return None
    hours = float(match.group(1).replace(",", "."))
    return hours if 0.5 <= hours <= 72 else None
