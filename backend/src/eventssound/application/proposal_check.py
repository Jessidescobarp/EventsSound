"""Facts and the deterministic Spanish template for a quote.

Pure stdlib + domain: the template must pass `verify_proposal` by construction, so both
live in this module (verification lands with the graph slice).
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

from eventssound.application.messages_es import (
    SHORTAGE_INTRO,
    TEMPLATE_CLOSING,
    render_shortage_lines,
)
from eventssound.domain.catalog import Catalog
from eventssound.domain.event_request import EventRequest
from eventssound.domain.pricing import LineKind, Quote

_WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


@dataclass(frozen=True, slots=True)
class FactLine:
    """One quote line reduced to plain ints/strs (no Money, no tz) for the template and checks."""

    code: str
    label: str | None
    quantity: int
    kind: LineKind
    unit_amount: int | None
    rate_bps: int | None
    basis: int | None
    amount: int


@dataclass(frozen=True, slots=True)
class ShortageFact:
    item_code: str
    name: str
    requested: int
    available: int


@dataclass(frozen=True, slots=True)
class QuoteFacts:
    """Everything the template and the verifier may use. No raw user text ever lands here."""

    start: datetime
    end: datetime
    guest_count: int
    distance_km: int
    rental_days: int
    lines: tuple[FactLine, ...]
    subtotal: int
    total: int
    catalog_names: dict[str, str]
    canary: str
    sentinel_phrases: tuple[str, ...] = ()
    shortages: tuple[ShortageFact, ...] = ()

    @classmethod
    def from_quote(
        cls,
        quote: Quote,
        request: EventRequest,
        catalog: Catalog,
        *,
        canary: str,
        sentinel_phrases: tuple[str, ...] = (),
        shortages: tuple[ShortageFact, ...] = (),
    ) -> "QuoteFacts":
        lines = tuple(
            FactLine(
                code=line.code,
                label=line.label,
                quantity=line.quantity,
                kind=line.kind,
                unit_amount=line.unit_amount.amount if line.unit_amount is not None else None,
                rate_bps=line.rate_bps,
                basis=line.basis.amount if line.basis is not None else None,
                amount=line.amount.amount,
            )
            for line in quote.lines
        )
        names = {item.code: item.name for item in catalog.items}
        names.update({package.code: package.name for package in catalog.packages})
        return cls(
            start=request.start,
            end=request.end,
            guest_count=request.guest_count,
            distance_km=request.distance_km,
            rental_days=quote.rental_days,
            lines=lines,
            subtotal=quote.subtotal.amount,
            total=quote.total.amount,
            catalog_names=names,
            canary=canary,
            sentinel_phrases=tuple(sentinel_phrases),
            shortages=tuple(shortages),
        )


def _pesos(amount: int) -> str:
    formatted = f"{abs(amount):,}".replace(",", ".")
    return f"-${formatted}" if amount < 0 else f"${formatted}"


def _hora(value: datetime) -> str:
    hour = value.hour % 12 or 12
    suffix = "a. m." if value.hour < 12 else "p. m."
    return f"{hour}:{value.minute:02d} {suffix}"


def _date_span(start: datetime, end: datetime) -> str:
    if start.date() == end.date():
        return (
            f"el {_WEEKDAYS[start.weekday()]} {start.day} de {_MONTHS[start.month - 1]} "
            f"de {start.year}"
        )
    return (
        f"del {start.day} de {_MONTHS[start.month - 1]} "
        f"al {end.day} de {_MONTHS[end.month - 1]} de {end.year}"
    )


def _line_bullets(facts: QuoteFacts) -> list[str]:
    bullets: list[str] = []
    for line in facts.lines:
        if line.kind is LineKind.ROUNDING and line.amount == 0:
            continue
        pct = f"({line.rate_bps // 100}%)" if line.rate_bps is not None else ""
        if line.kind in (LineKind.ITEM, LineKind.PACKAGE):
            bullets.append(f"- {line.quantity} x {line.label}: {_pesos(line.amount)} COP")
        elif line.kind is LineKind.PACKAGE_DISCOUNT:
            bullets.append(f"- Descuento de paquete: {_pesos(line.amount)} COP")
        elif line.kind is LineKind.GUEST_SIZE:
            bullets.append(f"- Recargo por numero de invitados {pct}: {_pesos(line.amount)} COP")
        elif line.kind is LineKind.WEEKEND_HOLIDAY:
            bullets.append(f"- Recargo fin de semana {pct}: {_pesos(line.amount)} COP")
        elif line.kind is LineKind.NIGHT:
            bullets.append(f"- Recargo horario nocturno {pct}: {_pesos(line.amount)} COP")
        elif line.kind is LineKind.DISTANCE:
            bullets.append(f"- Transporte ({line.quantity} km): {_pesos(line.amount)} COP")
        elif line.kind is LineKind.ROUNDING:
            bullets.append(f"- Ajuste de redondeo: {_pesos(line.amount)} COP")
    return bullets


def render_template(facts: QuoteFacts) -> str:
    """Deterministic Spanish quote text; plain text with `-` bullets, no HTML or URLs."""
    greeting = (
        f"Hola, esta es tu propuesta {_date_span(facts.start, facts.end)}, "
        f"de {_hora(facts.start)} a {_hora(facts.end)}, con {facts.guest_count} invitados."
    )
    parts = [greeting, *_line_bullets(facts), f"Total: {_pesos(facts.total)} COP"]
    if facts.shortages:
        parts.append("")
        parts.append(SHORTAGE_INTRO)
        parts.extend(render_shortage_lines(facts.shortages))
    parts.append(TEMPLATE_CLOSING)
    return "\n".join(parts)


def facts_payload(facts: QuoteFacts, *, event_type: str, available: bool) -> dict:
    """The exact facts the draft prompt receives (D13): no user text, no raw offsets."""
    return {
        "event_type": event_type,
        "date": _date_span(facts.start, facts.end),
        "start": _hora(facts.start),
        "end": _hora(facts.end),
        "guest_count": facts.guest_count,
        "distance_km": facts.distance_km,
        "rental_days": facts.rental_days,
        # `text` is the template bullet (Spanish name plus the line total), so surcharges that
        # carry no label are still named and the draft cannot read a line total as a unit price.
        "lines": [
            {
                "text": bullet[2:],
                "quantity": line.quantity,
                "amount_cop": line.amount,
            }
            for line, bullet in zip(
                [ln for ln in facts.lines if not (ln.kind is LineKind.ROUNDING and ln.amount == 0)],
                _line_bullets(facts),
                strict=True,
            )
        ],
        "subtotal_cop": facts.subtotal,
        "total_cop": facts.total,
        "availability": "disponible" if available else "con faltantes",
    }


# --- Verification (design D25): every check fails closed, reasons are stable codes ---


@dataclass(frozen=True, slots=True)
class VerificationResult:
    ok: bool
    reasons: tuple[str, ...]


def _fold(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)
    ).lower()


_MONEY_DOLLAR = re.compile(r"\$\s*(\d{1,3}(?:[.,]\d{3})+|\d+)")
_MONEY_WORD = re.compile(
    r"\b(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d{1,2})?)\s*(COP|pesos|peso|mil|millones)\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = [
    "uno",
    "dos",
    "tres",
    "cuatro",
    "cinco",
    "seis",
    "siete",
    "ocho",
    "nueve",
    "diez",
    "once",
    "doce",
    "trece",
    "catorce",
    "quince",
    "dieciseis",
    "diecisiete",
    "dieciocho",
    "diecinueve",
    "veinte",
    "veintiuno",
    "veintidos",
    "veintitres",
    "veinticuatro",
    "veinticinco",
    "veintiseis",
    "veintisiete",
    "veintiocho",
    "veintinueve",
    "treinta",
    "cuarenta",
    "cincuenta",
    "sesenta",
    "setenta",
    "ochenta",
    "noventa",
    "cien",
    "ciento",
    "doscientos",
    "trescientos",
    "cuatrocientos",
    "quinientos",
    "seiscientos",
    "setecientos",
    "ochocientos",
    "novecientos",
    "un",
    "mil",
    "millon",
    "millones",
    "y",
]
_WORD_MONEY = re.compile(
    r"\b(?:"
    + "|".join(_NUMBER_WORDS)
    + r")(?:\s+(?:"
    + "|".join(_NUMBER_WORDS)
    + r")){0,6}\s+(?:de\s+)?(?:pesos|peso|COP)\b",
    re.IGNORECASE,
)
_FORBIDDEN = (
    re.compile(r"https?://|www\."),
    re.compile(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}", re.IGNORECASE),
    re.compile(r"\[[^\]]*\]\(|!\[[^\]]*\]\("),
    re.compile(r"</?[a-z][^>]*>", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9._-])@[A-Za-z_][A-Za-z_0-9]+"),
)
_PHONE = re.compile(r"(?<![\d.])(\d{7,12})(?![\d.])")
_DIGIT_GROUP = re.compile(r"\d+(?:[.,]\d+)*")
_MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_DATE_NAMED = re.compile(
    r"\b(\d{1,2})\s+de\s+(" + "|".join(_MONTHS_ES) + r")(?:\s+de\s+(\d{4}))?\b"
)
_DATE_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_TIME_COLON = re.compile(r"\b(\d{1,2}):(\d{2})(?::\d{2})?\b")
_TIME_WORD = re.compile(r"(?<![\d:])(\d{1,2})\s*(a\.?\s*m\.?|p\.?\s*m\.?)\b")


def _parse_money(number: str, word: str | None) -> int | None:
    parts = re.split(r"[.,]", number)
    multiplier = (word or "").lower()
    if len(parts) == 1:
        value = int(parts[0])
    elif 1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:]):
        value = int("".join(parts))
    elif len(parts) == 2 and multiplier in ("mil", "millones") and len(parts[1]) <= 2:
        return int(
            round(float(number.replace(",", ".")) * (1000 if multiplier == "mil" else 1_000_000))
        )
    else:
        return None
    if multiplier == "mil":
        value *= 1000
    elif multiplier == "millones":
        value *= 1_000_000
    return value


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def _strip_spans(text: str, spans: list[tuple[int, int]]) -> str:
    result, offset = text, 0
    for start, end in _merge_spans(spans):
        result = result[: start - offset] + " " + result[end - offset :]
        offset += end - start - 1
    return result


def _allowed_numbers(facts: QuoteFacts) -> set[int]:
    allowed: set[int] = {
        facts.guest_count,
        facts.rental_days,
        facts.distance_km,
        facts.start.year,
        facts.end.year,
    }
    for line in facts.lines:
        allowed.add(line.quantity)
        if line.rate_bps is not None:
            allowed.add(line.rate_bps // 100)
        if line.label:
            allowed.update(int(d) for d in re.findall(r"\d+", line.label))
    for shortage in facts.shortages:
        allowed.update((shortage.requested, shortage.available))
        allowed.update(int(d) for d in re.findall(r"\d+", shortage.name))
    return allowed


def _amounts(facts: QuoteFacts) -> set[int]:
    values = {abs(facts.subtotal), abs(facts.total)}
    for line in facts.lines:
        values.add(abs(line.amount))
        if line.unit_amount is not None:
            values.add(abs(line.unit_amount))
        if line.basis is not None:
            values.add(abs(line.basis))
    return values


def verify_proposal(text: str, facts: QuoteFacts) -> VerificationResult:
    """Fail-closed checks on an LLM draft against validated facts (design D25)."""
    if not isinstance(text, str):
        raise TypeError("text must be a str")

    # Spans of recognized money/date/time tokens (text coordinates, merged before stripping)
    money_spans: list[tuple[int, int]] = []
    for pattern in (_MONEY_DOLLAR, _MONEY_WORD):
        money_spans.extend(m.span() for m in pattern.finditer(text))
    date_spans: list[tuple[int, int]] = []
    for pattern in (_DATE_NAMED, _DATE_SLASH, _DATE_ISO):
        date_spans.extend(m.span() for m in pattern.finditer(text))
    time_spans: list[tuple[int, int]] = []
    for pattern in (_TIME_COLON, _TIME_WORD):
        time_spans.extend(m.span() for m in pattern.finditer(text))

    # 1. length and control characters
    length_reason = ()
    if not 80 <= len(text) <= 1_500 or any(
        (ord(c) < 32 and c not in "\t\n") or ord(c) == 127 for c in text
    ):
        length_reason = ("length",)

    # 2. forbidden content: URLs, emails, markdown links, HTML tags, phones, handles
    stripped = _strip_spans(text, money_spans + date_spans + time_spans)
    url_reason = ()
    if any(pattern.search(stripped) for pattern in _FORBIDDEN) or _PHONE.search(stripped):
        url_reason = ("url",)

    # 3. canary and system-prompt fragments (accent- and case-folded)
    folded = _fold(text)
    canary_reason = ()
    if (facts.canary and _fold(facts.canary) in folded) or any(
        _fold(phrase) in folded for phrase in facts.sentinel_phrases if phrase
    ):
        canary_reason = ("canary",)

    # 4. numbers: recognized money must be a quote amount, the rest the allowed set
    amounts = _amounts(facts)
    allowed = _allowed_numbers(facts)
    money_values: list[int] = []
    unknown_amount = False
    for pattern in (_MONEY_DOLLAR, _MONEY_WORD):
        for match in pattern.finditer(text):
            word = match.group(2) if pattern is _MONEY_WORD else None
            value = _parse_money(match.group(1), word)
            if value is None or value not in amounts:
                unknown_amount = True
            else:
                money_values.append(value)
    if _WORD_MONEY.search(_strip_spans(text, money_spans)):
        unknown_amount = True
    number_reasons: list[str] = []
    if unknown_amount:
        number_reasons.append("unknown_amount")
    remaining = _strip_spans(text, money_spans + date_spans + time_spans)
    for match in _DIGIT_GROUP.finditer(remaining):
        parts = re.split(r"[.,]", match.group(0))
        if 1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:]):
            value: int | float = int("".join(parts))
        elif len(parts) == 1:
            value = int(parts[0])
        else:
            value = -1.0  # decimal-ish: never in the allowed set, fail closed
        if value not in allowed:
            if "unknown_number" not in number_reasons:
                number_reasons.append("unknown_number")
            break

    # 5. the total must appear (template formatting or as a recognized money value)
    total_reason = ()
    total_digits = f"{facts.total:,}".replace(",", ".")
    if (
        re.search(rf"(?<!\d){re.escape(total_digits)}(?!\d)", text) is None
        and abs(facts.total) not in money_values
    ):
        total_reason = ("missing_total",)

    # 6. dates and times must be the event's own
    event_dates = (facts.start.date(), facts.end.date())

    def _is_event_date(year: int, month: int, day: int) -> bool:
        try:
            return date(year, month, day) in event_dates
        except ValueError:
            return False  # calendar-impossible date: fail closed

    date_reason = ()
    for match in _DATE_NAMED.finditer(text):
        if not _is_event_date(
            int(match.group(3) or facts.start.year), _MONTHS_ES[match.group(2)], int(match.group(1))
        ):
            date_reason = ("unknown_date",)
            break
    if not date_reason:
        for match in _DATE_SLASH.finditer(text):
            year = int(match.group(3))
            if year < 100:
                year += 2000
            if not _is_event_date(year, int(match.group(2)), int(match.group(1))):
                date_reason = ("unknown_date",)
                break
    if not date_reason:
        for match in _DATE_ISO.finditer(text):
            if not _is_event_date(int(match.group(1)), int(match.group(2)), int(match.group(3))):
                date_reason = ("unknown_date",)
                break
    time_reason = ()
    start_hm = (facts.start.hour, facts.start.minute)
    end_hm = (facts.end.hour, facts.end.minute)
    for match in _TIME_COLON.finditer(text):
        hour, minute = int(match.group(1)), int(match.group(2))
        suffix = re.match(r"\s*(a\.?\s*m\.?|p\.?\s*m\.?)\b", text[match.end() :])
        if suffix:
            if not 1 <= hour <= 12:
                time_reason = ("unknown_time",)
                break
            if suffix.group(1).startswith("p"):
                hour = hour if hour == 12 else hour + 12
            else:
                hour = 0 if hour == 12 else hour
        elif not 0 <= hour <= 23:
            time_reason = ("unknown_time",)
            break
        if (hour, minute) not in (start_hm, end_hm):
            time_reason = ("unknown_time",)
            break
    if not time_reason:
        for match in _TIME_WORD.finditer(text):
            hour = int(match.group(1))
            if match.group(2).startswith("p"):
                hour = hour if hour == 12 else hour + 12
            else:
                hour = 0 if hour == 12 else hour
            if (hour, 0) not in (start_hm, end_hm):
                time_reason = ("unknown_time",)
                break

    # 7. catalog entries mentioned in the text must be in the quote lines
    item_reason = ()
    known_codes = {line.code for line in facts.lines} | {s.item_code for s in facts.shortages}
    for code, name in facts.catalog_names.items():
        if _fold(name) in folded and code not in known_codes:
            item_reason = ("unknown_item",)
            break

    ordered: list[str] = []
    for reason in (
        *length_reason,
        *url_reason,
        *canary_reason,
        *number_reasons,
        *total_reason,
        *date_reason,
        *time_reason,
        *item_reason,
    ):
        if reason not in ordered:
            ordered.append(reason)
    return VerificationResult(not ordered, tuple(ordered))
