"""Golden contract: the serialised worked-example quote is the shape the agent and evals consume.

Changing anything below is a contract change and must be a deliberate edit of this file.
"""

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from eventssound.domain.catalog import Catalog, EquipmentCategory, EquipmentItem
from eventssound.domain.event_request import EventRequest, EventType, RequestedLine, VenueType
from eventssound.domain.money import Money
from eventssound.domain.pricing import calculate_price
from eventssound.domain.pricing_rules import default_pricing_rules

BOGOTA = ZoneInfo("America/Bogota")


def worked_example() -> dict[str, Any]:
    catalog = Catalog(
        items=(
            EquipmentItem(
                "speaker_active", "Parlante activo", EquipmentCategory.SOUND, 10, Money(120_000)
            ),
            EquipmentItem(
                "mixer_16ch", "Mezcladora 16 canales", EquipmentCategory.SOUND, 2, Money(79_900)
            ),
        ),
        packages=(),
    )
    request = EventRequest(
        event_type=EventType.WEDDING,
        start=datetime(2026, 10, 10, 20, 0, tzinfo=BOGOTA),  # Saturday
        end=datetime(2026, 10, 10, 23, 30, tzinfo=BOGOTA),
        guest_count=150,
        distance_km=45,
        venue=VenueType.OUTDOOR,
        items=(RequestedLine("speaker_active", 2), RequestedLine("mixer_16ch", 1)),
    )
    return calculate_price(request, catalog, default_pricing_rules()).to_dict()  # type: ignore[return-value]


def line(kind: str, code: str, amount: int, **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": kind,
        "code": code,
        "label": None,
        "quantity": 1,
        "periods": 1,
        "unit_amount": None,
        "rate_bps": None,
        "basis": None,
        "amount": amount,
    }
    return {**base, **fields}


GOLDEN_LINES = [
    line("item", "mixer_16ch", 79_900, label="Mezcladora 16 canales", unit_amount=79_900),
    line(
        "item", "speaker_active", 240_000, label="Parlante activo", quantity=2, unit_amount=120_000
    ),
    line("guest_size", "guest_size", 31_990, rate_bps=1000, basis=319_900),
    line("weekend_holiday", "weekend_holiday", 47_985, rate_bps=1500, basis=319_900),
    line("night", "night", 63_980, rate_bps=2000, basis=319_900),
    line("distance", "distance_band_2", 75_000, quantity=25, unit_amount=3_000),
    line("rounding", "rounding", 145),
]

GOLDEN: dict[str, Any] = {
    "version": 1,
    "rules_version": "synthetic-v1",
    "currency": "COP",
    "rental_days": 1,
    "lines": GOLDEN_LINES,
    "subtotal": 538_855,
    "total": 539_000,
}


def test_worked_example_matches_the_golden_snapshot() -> None:
    assert worked_example() == GOLDEN


def test_golden_snapshot_is_json_serialisable_and_keeps_its_key_order() -> None:
    data = worked_example()
    assert json.loads(json.dumps(data)) == data
    assert list(data) == list(GOLDEN)
    assert all(list(entry) == list(GOLDEN_LINES[0]) for entry in data["lines"])
    assert len(data["lines"]) == len(GOLDEN_LINES) == 7  # guards against a vacuous comparison


def test_golden_lines_reconcile_with_the_total() -> None:
    assert sum(entry["amount"] for entry in GOLDEN_LINES) == GOLDEN["total"]
