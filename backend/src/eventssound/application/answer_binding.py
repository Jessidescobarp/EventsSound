"""Deterministic "answer binding": read a short user reply as the answer to the question asked.

The agent is stateless and weak models re-extract the whole conversation every turn, so a bare
"5" or "11 PM" after "cuantas horas dura?" gets lost or mislabeled. The previous assistant turn is
one of our static messages (see `messages_es.asked_fields`); it only selects WHICH field the
user's own text is parsed as. Nothing from assistant text is ever copied into a fact.
"""

import re
from datetime import date

from eventssound.application.spanish_dates import parse_spanish_date
from eventssound.application.spanish_facts import fold, parse_clock_time

MAX_ANSWER_CHARS = 40  # a reply to a single question is short; longer text is not bound
_MAX_GUESTS = 100_000
_MAX_KM = 5_000
_HOUR_WORDS = {
    word: number
    for number, word in enumerate(
        ("uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez"), 1
    )
} | {"once": 11, "doce": 12}
_NUMBER = r"(\d{1,2}(?:[.,]\d)?|" + "|".join(_HOUR_WORDS) + r")"
_DURATION = re.compile(rf"{_NUMBER}\s*(?:horas?|hrs?|hs|h)?")
_UNTIL = re.compile(r"hasta\s+(?:las?\s+)?(\d{1,2})(?::([0-5]\d))?")
_BARE_HOUR = re.compile(r"(?:a\s+)?(?:las?\s+)?(\d{1,2})")
_GUESTS = re.compile(r"(\d{1,6})\s*(?:personas|invitados|asistentes|pax|huespedes)?")
_KM = re.compile(r"(?:aprox\w*\.?\s*)?(\d{1,4})\s*(?:km|kms|kilometros)?")


def pick_option(text: str, names: tuple[str, ...]) -> str | None:
    """The catalog name `text` equals (accent/case-insensitive, trimmed), else None."""
    wanted = fold(text).strip()
    return next((name for name in names if fold(name) == wanted), None)


def _hour(value: str, minute: str | None = None) -> str | None:
    return f"{int(value):02d}:{minute or '00'}" if int(value) <= 23 else None  # noqa: PLR2004


def _duration(text: str) -> dict:
    match = _DURATION.fullmatch(text)
    if match is None:
        return {}
    raw = match.group(1)
    hours = float(_HOUR_WORDS.get(raw) or raw.replace(",", "."))
    return {"duration_hours": hours} if 0.5 <= hours <= 72 else {}  # noqa: PLR2004


def _end_or_duration(text: str) -> dict:
    clock = parse_clock_time(text)
    until = _UNTIL.fullmatch(text)
    if clock is None and until is not None:
        clock = _hour(until.group(1), until.group(2))
    return {"end_time": clock} if clock else _duration(text)


def _start(text: str) -> dict:
    bare = _BARE_HOUR.fullmatch(text)
    clock = parse_clock_time(text) or (_hour(bare.group(1)) if bare else None)
    return {"start_time": clock} if clock else {}


def _bounded(pattern: re.Pattern[str], text: str, key: str, high: int) -> dict:
    match = pattern.fullmatch(text)
    return {key: int(match.group(1))} if match and 1 <= int(match.group(1)) <= high else {}


def parse_field_answer(field: str, text: str, today: date) -> dict:
    """Extraction updates for `text` read as the answer to `field`; {} when it does not fit.

    Bare numbers mean something only for the field being asked: "5" is hours for a duration
    question and guests for a guest question. Bare hours ("8") are read on a 24h clock.
    """
    folded = fold(text).strip()
    if not folded or len(folded) > MAX_ANSWER_CHARS:
        return {}
    if field == "event_date":
        parsed = parse_spanish_date(text, today)
        return {"event_date": parsed.isoformat()} if parsed else {}
    return {
        "start_time": _start,
        "end_time_or_duration": _end_or_duration,
        "guest_count": lambda t: _bounded(_GUESTS, t, "guest_count", _MAX_GUESTS),
        "distance_or_locality": lambda t: _bounded(_KM, t, "distance_km", _MAX_KM),
    }.get(field, lambda _: {})(folded)
