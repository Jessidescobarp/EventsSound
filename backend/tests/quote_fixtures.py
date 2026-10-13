"""Shared golden fixture: the pricing worked example (design/pricing spec) as QuoteFacts."""

from dataclasses import replace
from datetime import datetime

from eventssound.application.proposal_check import QuoteFacts
from eventssound.domain.catalog import Catalog, EquipmentCategory, EquipmentItem
from eventssound.domain.event_request import EventRequest, EventType, RequestedLine, VenueType
from eventssound.domain.money import Money
from eventssound.domain.pricing import calculate_price
from eventssound.domain.pricing_rules import default_pricing_rules

CANARY = "esd-canary-7f3a"


def golden(request_overrides: dict | None = None, guest_count: int = 150):
    """2 x speaker at 120000 + 1 x mixer at 79900, 150 guests, Sat 2026-10-17 20:00-23:30, 45 km."""
    rules = default_pricing_rules()
    kwargs = dict(
        event_type=EventType.OTHER,
        start=datetime(2026, 10, 17, 20, 0, tzinfo=rules.timezone),
        end=datetime(2026, 10, 17, 23, 30, tzinfo=rules.timezone),
        guest_count=guest_count,
        distance_km=45,
        venue=VenueType.INDOOR,
        items=(
            RequestedLine("sound_speaker_active_15", 2),
            RequestedLine("sound_mixer_16ch", 1),
        ),
    )
    if request_overrides:
        kwargs.update(request_overrides)
    request = EventRequest(**kwargs)
    catalog = Catalog(
        items=(
            EquipmentItem(
                "sound_speaker_active_15",
                "Parlante activo 15 pulgadas",
                EquipmentCategory.SOUND,
                3,
                Money(120_000),
            ),
            EquipmentItem(
                "sound_mixer_16ch",
                "Mezcladora 16 canales",
                EquipmentCategory.SOUND,
                3,
                Money(79_900),
            ),
        ),
        packages=(),
    )
    return calculate_price(request, catalog, rules), request, catalog


def facts(**overrides) -> QuoteFacts:
    quote, request, catalog = golden()
    base = QuoteFacts.from_quote(quote, request, catalog, canary=CANARY)
    return replace(base, **overrides) if overrides else base
