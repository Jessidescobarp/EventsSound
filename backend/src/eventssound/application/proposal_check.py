"""Facts and the deterministic Spanish template for a quote.

Pure stdlib + domain: the template must pass `verify_proposal` by construction, so both
live in this module (verification lands with the graph slice).
"""

from dataclasses import dataclass
from datetime import datetime

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
