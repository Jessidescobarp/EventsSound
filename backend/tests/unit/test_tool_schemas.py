"""Tool argument schemas: strict, bounded, no price fields, no coercion."""

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from eventssound.adapters.agent.tool_schemas import EventRequestArgs, SearchArgs
from eventssound.domain.catalog import EquipmentCategory
from eventssound.domain.errors import DomainError
from eventssound.domain.event_request import EventRequest, EventType, VenueType

VALID: dict[str, Any] = {
    "event_type": "wedding",
    "start": "2026-11-14T18:00:00-05:00",
    "end": "2026-11-14T23:00:00-05:00",
    "guest_count": 120,
    "distance_km": 12,
    "venue": "outdoor",
    "items": [{"code": "sound_speaker_15", "quantity": 2}],
    "packages": [{"code": "pkg_party", "quantity": 1}],
}


def request_args(**overrides: Any) -> dict[str, Any]:
    return {**VALID, **overrides}


# --- buscar_equipamiento ---------------------------------------------------------------------


def test_search_args_defaults_and_category_by_value() -> None:
    args = SearchArgs.model_validate({"query": "luces", "category": "dj"})

    assert (args.query, args.category, args.limit) == ("luces", EquipmentCategory.DJ, 5)
    assert SearchArgs.model_validate({"query": "luces"}).category is None


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "luces", "price_override": 1},
        {"query": ""},
        {"query": "a" * 201},
        {"query": 5},
        {"query": "luces", "limit": 0},
        {"query": "luces", "limit": 11},
        {"query": "luces", "limit": "3"},
        {"query": "luces", "limit": True},
        {"query": "luces", "category": "submarines"},
        {"query": "luces", "category": 3},
        {},
    ],
)
def test_search_args_reject_invalid_payloads(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SearchArgs.model_validate(payload)


def test_search_args_accept_the_boundaries() -> None:
    assert SearchArgs.model_validate({"query": "a" * 200, "limit": 10}).limit == 10
    assert SearchArgs.model_validate({"query": "a", "limit": 1}).limit == 1


# --- consultar_disponibilidad / calcular_precio ------------------------------------------------


def test_event_request_args_build_the_domain_request() -> None:
    request = EventRequestArgs.model_validate(VALID).to_domain()

    assert isinstance(request, EventRequest)
    assert request.event_type is EventType.WEDDING and request.venue is VenueType.OUTDOOR
    assert request.start == datetime(2026, 11, 14, 23, tzinfo=UTC)
    assert [(line.code, line.quantity) for line in request.items] == [("sound_speaker_15", 2)]
    assert [(line.code, line.quantity) for line in request.packages] == [("pkg_party", 1)]


def test_a_z_suffix_is_a_valid_utc_offset() -> None:
    args = EventRequestArgs.model_validate(
        request_args(start="2026-11-14T18:00:00Z", end="2026-11-14T23:00:00Z")
    )

    assert args.to_domain().start == datetime(2026, 11, 14, 18, tzinfo=UTC)


@pytest.mark.parametrize("field", ["unit_price", "total", "discount_bps", "rate", "price"])
def test_price_fields_are_refused(field: str) -> None:
    with pytest.raises(ValidationError):
        EventRequestArgs.model_validate(request_args(**{field: 1}))


def test_price_fields_inside_a_line_are_refused() -> None:
    line = {"code": "sound_speaker_15", "quantity": 1, "unit_price": 1}

    with pytest.raises(ValidationError):
        EventRequestArgs.model_validate(request_args(items=[line]))


@pytest.mark.parametrize("quantity", ["3", True, 3.0, None])
def test_quantity_is_not_coerced(quantity: object) -> None:
    line = {"code": "sound_speaker_15", "quantity": quantity}

    with pytest.raises(ValidationError):
        EventRequestArgs.model_validate(request_args(items=[line]))


@pytest.mark.parametrize(
    "overrides",
    [
        {"guest_count": "50"},
        {"guest_count": True},
        {"distance_km": "5"},
        {"event_type": "party"},
        {"event_type": 1},
        {"venue": "garden"},
        {"start": 1_700_000_000},
        {"start": "not a date"},
        {"start": "2026-11-14T18:00:00"},  # naive
        {"items": "sound_speaker_15"},
        {"items": [{"code": "x"}]},
        {"items": [{"code": "sound_speaker_15", "quantity": 0}]},
        {"items": [{"code": "sound_speaker_15", "quantity": 10_001}]},
        {"items": [{"code": "UPPER", "quantity": 1}]},
        {"items": [{"code": "ab", "quantity": 1}]},
        {"items": [{"code": "sound_speaker_15\n", "quantity": 1}]},
        {"items": [{"code": "a_b_c", "quantity": 1}] * 101, "packages": []},
    ],
)
def test_malformed_event_requests_fail_validation(overrides: dict[str, Any]) -> None:
    with pytest.raises((ValidationError, DomainError)):
        EventRequestArgs.model_validate(request_args(**overrides)).to_domain()


@pytest.mark.parametrize(
    "overrides",
    [
        {"guest_count": 0},
        {"guest_count": 100_001},
        {"distance_km": -1},
        {"distance_km": 5_001},
        {"items": [], "packages": []},  # no lines
    ],
)
def test_numeric_and_line_bounds_are_enforced_by_the_schema(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EventRequestArgs.model_validate(request_args(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"end": "2026-11-14T18:00:00-05:00"},  # end == start
        {"end": "2026-11-14T17:00:00-05:00"},  # end < start
        {"end": "2026-12-20T18:00:00-05:00"},  # longer than 31 days
    ],
    ids=["end-equals-start", "end-before-start", "over-31-days"],
)
def test_ordering_and_duration_are_enforced_by_the_domain_request(
    overrides: dict[str, Any],
) -> None:
    args = EventRequestArgs.model_validate(request_args(**overrides))  # the schema accepts them

    with pytest.raises(DomainError):
        args.to_domain()


def test_one_hundred_lines_are_accepted() -> None:
    lines = [{"code": f"item_{i:03d}", "quantity": 1} for i in range(100)]

    args = EventRequestArgs.model_validate(request_args(items=lines, packages=[]))

    assert len(args.to_domain().items) == 100
