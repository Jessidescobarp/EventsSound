"""Deterministic parsing of Spanish day+month expressions ("15 de diciembre", "5 nov", "15/12").

A missing year resolves to the next occurrence on or after `today`: weak models do poor date
math, so the agent owns this instead of trusting the LLM.
"""

import re
import unicodedata
from datetime import date

_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "sept": 9,
    "set": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}
_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))
_TEXTUAL = re.compile(rf"\b(\d{{1,2}})\s*(?:de\s+)?({_NAMES})\b(?:\s+(?:de|del)?\s*(\d{{4}})\b)?")
_NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b")
_LOOKAHEAD_YEARS = 4  # enough to reach the next 29 February


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _resolve(day: int, month: int, year: int | None, today: date) -> date | None:
    if year is not None:
        try:
            return date(year, month, day)
        except ValueError:
            return None
    for candidate_year in range(today.year, today.year + _LOOKAHEAD_YEARS + 1):
        try:
            candidate = date(candidate_year, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    return None


def parse_spanish_date(text: str, today: date) -> date | None:
    """The first valid date in `text`, or None. Numeric dates are day/month (Latin American)."""
    folded = _fold(text)
    found: list[tuple[int, date]] = []
    for match in _TEXTUAL.finditer(folded):
        year = int(match.group(3)) if match.group(3) else None
        resolved = _resolve(int(match.group(1)), _MONTHS[match.group(2)], year, today)
        if resolved is not None:
            found.append((match.start(), resolved))
    for match in _NUMERIC.finditer(folded):
        year = int(match.group(3)) if match.group(3) else None
        resolved = _resolve(int(match.group(1)), int(match.group(2)), year, today)
        if resolved is not None:
            found.append((match.start(), resolved))
    return min(found, key=lambda pair: pair[0])[1] if found else None
