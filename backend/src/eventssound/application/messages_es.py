"""Every Spanish string the system itself writes (refusals, clarifications, template).

The LLM never produces these; they are rendered from validated facts only, so they are
safe to show to the user verbatim. Written without accents, matching the public contract
examples in the design.
"""

import functools
import itertools
import re
import unicodedata

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
    "distance_or_locality": "A cuantos kilometros de Bogota (aprox.) queda el lugar del evento?",
    "equipment": "Que equipos necesitas?",
}

MAX_CLARIFICATION_FIELDS = 3

# Sent when the model could not produce a usable extraction even after the one repair.
CLARIFICATION_REPHRASE = (
    "No logre interpretar bien los datos de tu evento. Repetilo, por favor: que tipo de evento "
    "es, en que fecha y a que hora, cuantos invitados van y que equipos necesitas."
)

CLARIFY_ITEMS_INTRO = (
    "Hay algunos equipos que no supe ubicar en el catalogo. A cual te refieres exactamente:"
)
_MAX_ITEM_OPTIONS = 3
MAX_OPTIONS = 6
VIEW_ALL_OPTION = "Ver todo el catalogo"

SHORTAGE_INTRO = "No pudimos garantizar todo el equipo:"
_SHORTAGE_LINE = "- {name}: pediste {requested}, hay {available}."

TEMPLATE_CLOSING = "Los valores los calcula nuestro sistema de precios."

# Default greeting; admin-editable through AgentConfig.
WELCOME = (
    "Hola, soy el asistente de EventSoundDR. Cuentame tu evento (tipo, fecha, invitados y lugar)"
    " y te armo una cotizacion de sonido, luces y DJ."
)


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


def normalize_message(text: str) -> str:
    """The form our static messages take after the chat sanitizer: NFKC, whitespace collapsed.

    `sanitize_turns` runs on assistant turns too, so a real clarification reaches the agent on one
    line. Recognition compares against this form of the rendered templates, so they cannot drift.
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


@functools.cache
def _known_questions() -> dict[str, tuple[str, ...]]:
    """Every message `render_clarification` can produce (ordered subsets of up to 3 fields)."""
    combos = (
        c
        for size in range(1, MAX_CLARIFICATION_FIELDS + 1)
        for c in itertools.combinations(CLARIFICATION_FIELD_ORDER, size)
    )
    return {normalize_message(render_clarification(c)): c for c in combos}


def asked_fields(assistant_text: str) -> tuple[str, ...]:
    """Inverse of `render_clarification`: the field codes a static question message asked.

    Assistant turns are client-supplied, so this only selects which field the user's next
    answer is read as. The text must equal a rendered message exactly (modulo whitespace):
    extra text, shifted numbering or a lookalike intro select nothing.
    """
    return _known_questions().get(normalize_message(assistant_text), ())


def clarified_mentions(assistant_text: str) -> tuple[str, ...] | None:
    """The mentions an items clarification (`render_clarify_items`) asked about, else None."""
    text = normalize_message(assistant_text)
    head = normalize_message(CLARIFY_ITEMS_INTRO) + " - "
    if not text.startswith(head):
        return None
    entries = text[len(head) :].split(" - ")
    if any(": " not in entry for entry in entries):
        return None
    return tuple(entry.partition(": ")[0] for entry in entries)


def render_clarify_items(
    ambiguous: object,
    unresolved: object = (),
) -> str:
    """Ask which catalog entry a mention means, or say a mention was not found.

    `ambiguous` is an iterable of (mention, catalog_names); `unresolved` a collection of
    mentions that matched nothing. Only catalog names and charset-limited mentions appear.
    """
    if not isinstance(ambiguous, tuple | list) or not isinstance(unresolved, tuple | list):
        raise ValueError("ambiguous and unresolved must be sequences")
    lines: list[str] = []
    for entry in ambiguous:
        if not isinstance(entry, tuple | list) or len(entry) != 2:
            raise ValueError("each ambiguous entry must be (mention, names)")
        mention, names = entry
        names = tuple(names[:_MAX_ITEM_OPTIONS])
        if not names:
            raise ValueError("an ambiguous mention needs at least one catalog name")
        if len(names) == 1:
            options = names[0]
        elif len(names) == 2:
            options = f"{names[0]} o {names[1]}"
        else:
            options = f"{names[0]}, {names[1]} o {names[2]}"
        lines.append(f"- {mention}: {options}")
    for mention in unresolved:
        lines.append(f"- {mention}: no lo encontre en el catalogo, proba con otro nombre.")
    if not lines:
        raise ValueError("nothing to clarify")
    return f"{CLARIFY_ITEMS_INTRO}\n" + "\n".join(lines)


def clarify_item_options(
    ambiguous: tuple, unresolved: tuple, suggestions: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """Clickable answers for `render_clarify_items`: exactly the text the customer would type.

    Ambiguous mentions offer their catalog names (deduplicated, stable order, capped). When
    nothing matched at all, offer the suggested catalog names plus a "see everything" option.
    Never built from user or model text.
    """
    names = tuple(dict.fromkeys(name for _, candidates in ambiguous for name in candidates))
    if names:
        return names[:MAX_OPTIONS]
    if unresolved:
        return (*dict.fromkeys(suggestions[:_MAX_ITEM_OPTIONS]), VIEW_ALL_OPTION)
    return ()


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
