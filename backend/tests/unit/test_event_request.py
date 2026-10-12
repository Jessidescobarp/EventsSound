"""EventRequest: input bounds and normalization."""

import dataclasses
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from eventssound.domain.errors import InvalidEventRequest
from eventssound.domain.event_request import (
    EventRequest,
    EventType,
    RequestedLine,
    VenueType,
)

BOGOTA = timezone(timedelta(hours=-5))
START = datetime(2026, 11, 7, 18, 0, tzinfo=BOGOTA)


def make_request(**overrides: Any) -> EventRequest:
    values: dict[str, Any] = {
        "event_type": EventType.WEDDING,
        "start": START,
        "end": START + timedelta(hours=6),
        "guest_count": 120,
        "distance_km": 25,
        "venue": VenueType.INDOOR,
        "items": (RequestedLine("sound_speaker", 2),),
    }
    values.update(overrides)
    return EventRequest(**values)


def test_valid_request_is_built_and_frozen() -> None:
    request = make_request()
    assert request.packages == ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.guest_count = 1  # type: ignore[misc]


def test_package_only_request_is_valid() -> None:
    request = make_request(items=(), packages=(RequestedLine("pkg_basic", 1),))
    assert request.packages == (RequestedLine("pkg_basic", 1),)


def test_collections_are_coerced_to_tuples() -> None:
    request = make_request(items=[RequestedLine("sound_speaker", 1)])
    assert isinstance(request.items, tuple)


INVALID: dict[str, Callable[[], EventRequest]] = {
    "naive-start": lambda: make_request(start=datetime(2026, 11, 7, 18, 0)),
    "naive-end": lambda: make_request(end=datetime(2026, 11, 8, 1, 0)),
    "end-equals-start": lambda: make_request(end=START),
    "end-before-start": lambda: make_request(end=START - timedelta(hours=1)),
    "over-31-days": lambda: make_request(end=START + timedelta(days=31, seconds=1)),
    "zero-guests": lambda: make_request(guest_count=0),
    "too-many-guests": lambda: make_request(guest_count=100_001),
    "bool-guests": lambda: make_request(guest_count=True),
    "negative-distance": lambda: make_request(distance_km=-1),
    "too-far": lambda: make_request(distance_km=5_001),
    "float-distance": lambda: make_request(distance_km=1.5),
    "no-lines": lambda: make_request(items=()),
    "zero-quantity": lambda: make_request(items=(RequestedLine("sound_speaker", 0),)),
    "huge-quantity": lambda: make_request(items=(RequestedLine("sound_speaker", 10_001),)),
    "float-quantity": lambda: make_request(items=(RequestedLine("sound_speaker", 1.5),)),
    "empty-code": lambda: make_request(items=(RequestedLine("", 1),)),
    "too-many-lines": lambda: make_request(
        items=tuple(RequestedLine(f"item_{i:03}", 1) for i in range(101))
    ),
    "bad-event-type": lambda: make_request(event_type="wedding"),
    "bad-venue": lambda: make_request(venue="indoor"),
}


@pytest.mark.parametrize("build", INVALID.values(), ids=INVALID.keys())
def test_invalid_requests_are_rejected(build: Callable[[], EventRequest]) -> None:
    with pytest.raises(InvalidEventRequest):
        build()


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"end": START + timedelta(days=31)}, id="exactly-31-days"),
        pytest.param({"guest_count": 1}, id="one-guest"),
        pytest.param({"guest_count": 100_000}, id="max-guests"),
        pytest.param({"distance_km": 0}, id="zero-distance"),
        pytest.param({"distance_km": 5_000}, id="max-distance"),
        pytest.param({"items": (RequestedLine("sound_speaker", 10_000),)}, id="max-quantity"),
    ],
)
def test_bounds_are_inclusive(overrides: dict[str, Any]) -> None:
    make_request(**overrides)


def test_hundred_lines_across_items_and_packages_are_allowed() -> None:
    items = tuple(RequestedLine(f"item_{i:03}", 1) for i in range(60))
    packages = tuple(RequestedLine(f"pkg_{i:03}", 1) for i in range(40))
    make_request(items=items, packages=packages)


def test_normalized_merges_duplicates_and_sorts_by_code() -> None:
    request = make_request(
        items=(
            RequestedLine("light_par", 1),
            RequestedLine("sound_speaker", 2),
            RequestedLine("light_par", 3),
        ),
        packages=(RequestedLine("pkg_b", 1), RequestedLine("pkg_a", 1), RequestedLine("pkg_b", 1)),
    )
    normalized = request.normalized()
    assert normalized.items == (RequestedLine("light_par", 4), RequestedLine("sound_speaker", 2))
    assert normalized.packages == (RequestedLine("pkg_a", 1), RequestedLine("pkg_b", 2))
    assert request.items[0] == RequestedLine("light_par", 1)  # input untouched


def test_normalized_is_order_independent_and_idempotent() -> None:
    lines = (RequestedLine("a_item", 1), RequestedLine("b_item", 2), RequestedLine("a_item", 5))
    forward = make_request(items=lines).normalized()
    backward = make_request(items=lines[::-1]).normalized()
    assert forward == backward
    assert forward.normalized() == forward


def test_merged_quantity_over_the_bound_is_rejected() -> None:
    request = make_request(items=(RequestedLine("sound_speaker", 6_000),) * 2)
    with pytest.raises(InvalidEventRequest):
        request.normalized()
