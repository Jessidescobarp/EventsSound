"""Every Spanish string the system itself writes (refusals, clarifications, template).

The LLM never produces these; they are rendered from validated facts only, so they are
safe to show to the user verbatim. Written without accents, matching the public contract
examples in the design.
"""

import re

REFUSAL = (
    "Solo puedo ayudarte a cotizar equipos de sonido, luces y DJ para eventos."
    " Cuentame que evento tienes en mente: tipo, fecha, numero de invitados y lugar."
)

CLARIFICATION_INTRO = "Para armar tu cotizacion necesito algunos datos mas:"

# Fixed priority: a clarification asks at most MAX_CLARIFICATION_FIELDS at a time.
CLARIFICATION_FIELD_ORDER = (
    "event_date",
    "start_time",
    "end_time_or_duration",
    "guest_count",
    "distance_or_locality",
    "equipment",
)

_CLARIFICATION_FIELDS = {
    "event_date": "Que fecha va a ser el evento?",
    "start_time": "A que hora empieza?",
    "end_time_or_duration": "A que hora termina o cuantas horas dura?",
    "guest_count": "Cuantos invitados habra?",
    "distance_or_locality": "En que ciudad o a cuantos kilometros de Bogota es el evento?",
    "equipment": "Que equipos necesitas?",
}

MAX_CLARIFICATION_FIELDS = 3

SHORTAGE_INTRO = "No pudimos garantizar todo el equipo:"
_SHORTAGE_LINE = "- {name}: pediste {requested}, hay {available}."

TEMPLATE_CLOSING = "Los valores los calcula nuestro sistema de precios."


def render_clarification(missing_fields: object) -> str:
    """Numbered Spanish questions for the missing fields, at most 3, in priority order."""
    if not isinstance(missing_fields, tuple | list | set | frozenset):
        raise ValueError("missing_fields must be a collection of field codes")
    unknown = set(missing_fields) - set(_CLARIFICATION_FIELDS)
    if unknown:
        raise ValueError(f"unknown field codes: {sorted(unknown)}")
    ordered = [c for c in CLARIFICATION_FIELD_ORDER if c in set(missing_fields)]
    if not ordered:
        raise ValueError("missing_fields must not be empty")
    lines = [
        f"{i}. {_CLARIFICATION_FIELDS[code]}"
        for i, code in enumerate(ordered[:MAX_CLARIFICATION_FIELDS], 1)
    ]
    return f"{CLARIFICATION_INTRO}\n" + "\n".join(lines)


def render_shortage_lines(shortages) -> list[str]:
    """One line per shortage; names come from the catalog, never from user text."""
    lines: list[str] = []
    for shortage in shortages:
        name = re.sub(r"\s+", " ", shortage.name).strip()
        lines.append(
            _SHORTAGE_LINE.format(
                name=name, requested=shortage.requested, available=shortage.available
            )
        )
    return lines
