"""ToolExecutor: allowlist, safe errors, budget, and results equal to the domain oracle."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from typing import Any

import pytest

from agent_fixtures import make_catalog
from eventssound.adapters.agent.tools import (
    ALLOWED_TOOLS,
    ToolBudgetExceeded,
    ToolExecutor,
    ToolResult,
)
from eventssound.adapters.search.keyword import KeywordSearch
from eventssound.application.availability import check_event_availability
from eventssound.application.catalog import list_catalog
from eventssound.application.errors import InvalidStoredData, RepositoryUnavailable
from eventssound.application.pricing import price_quote
from eventssound.domain.availability import (
    Booking,
    BookingStatus,
    default_availability_rules,
)
from eventssound.domain.event_request import EventRequest
from eventssound.domain.pricing import calculate_price
from eventssound.domain.pricing_rules import default_pricing_rules
from fakes import (
    BrokenBookingRepository,
    BrokenCatalogRepository,
    InMemoryBookingRepository,
    InMemoryCatalogRepository,
)

CATALOG = make_catalog()
START = datetime(2026, 11, 14, 23, tzinfo=UTC)
END = datetime(2026, 11, 15, 4, tzinfo=UTC)
ARGS: dict[str, Any] = {
    "event_type": "wedding",
    "start": "2026-11-14T18:00:00-05:00",
    "end": "2026-11-14T23:00:00-05:00",
    "guest_count": 120,
    "distance_km": 12,
    "venue": "outdoor",
    "items": [{"code": "sound_speaker_15", "quantity": 2}],
}


def build(
    bookings: tuple[Booking, ...] = (),
    *,
    catalog_repository: Any = None,
    booking_repository: Any = None,
    max_calls: int = 6,
    price: Callable[[EventRequest], Any] | None = None,
) -> ToolExecutor:
    catalogs = catalog_repository or InMemoryCatalogRepository(CATALOG)
    bookings_repo = booking_repository or InMemoryBookingRepository(bookings)
    return ToolExecutor(
        search=KeywordSearch(CATALOG),
        load_catalog=partial(list_catalog, catalogs),
        check_availability=lambda request: check_event_availability(
            request, catalogs, bookings_repo, default_availability_rules()
        ),
        price=price or (lambda request: price_quote(request, catalogs, default_pricing_rules())),
        max_calls=max_calls,
    )


def reservation(item: str, quantity: int) -> Booking:
    return Booking("bk_1", item, quantity, START, END, BookingStatus.CONFIRMED)


# --- registry and allowlist ----------


def test_the_registry_is_exactly_the_three_tools() -> None:
    assert {"buscar_equipamiento", "consultar_disponibilidad", "calcular_precio"} == ALLOWED_TOOLS
    assert set(build().handlers) == set(ALLOWED_TOOLS)


@pytest.mark.parametrize(
    "name", ["borrar_catalogo", "", "BUSCAR_EQUIPAMIENTO", "calcular_precio ", None, 5]
)
def test_an_unknown_tool_runs_nothing(name: object) -> None:
    calls: list[str] = []
    executor = ToolExecutor(
        search=_Spy(calls),
        load_catalog=lambda: calls.append("catalog") or CATALOG,  # type: ignore[func-returns-value]
        check_availability=lambda r: calls.append("availability"),  # type: ignore[arg-type, return-value]
        price=lambda r: calls.append("price"),  # type: ignore[arg-type, return-value]
    )

    result = executor.invoke(name, {})  # type: ignore[arg-type]

    assert not result.ok and result.error.code == "unknown_tool"
    assert calls == []


def test_unknown_tool_logs_only_a_bounded_name(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="eventssound.adapters.agent.tools"):
        build().invoke("x" * 500 + "\nINJECTED", {"secret": "hunter2"})

    assert "hunter2" not in caplog.text and "INJECTED" not in caplog.text
    assert len(caplog.text) < 400


# --- buscar_equipamiento ----------


def test_search_returns_catalog_data_for_each_hit() -> None:
    result = build().invoke("buscar_equipamiento", {"query": "parlante"})

    assert result.ok and result.error is None
    hits = {hit["code"]: hit for hit in result.data["hits"]}
    assert hits["sound_speaker_15"] == {
        "code": "sound_speaker_15",
        "name": "Parlante activo de 15 pulgadas",
        "category": "sound",
        "unit_price_cop": 80_000,
        "kind": "item",
        "rank": hits["sound_speaker_15"]["rank"],
    }
    package = hits["pkg_party"]
    assert package["kind"] == "package" and package["category"] is None
    assert package["unit_price_cop"] == CATALOG.package("pkg_party").base_unit_price(CATALOG).amount


def test_search_respects_category_and_limit() -> None:
    result = build().invoke(
        "buscar_equipamiento", {"query": "parlante consola", "category": "dj", "limit": 1}
    )

    assert result.ok and result.data == {"hits": []}
    limited = build().invoke("buscar_equipamiento", {"query": "parlante", "limit": 1})
    assert len(limited.data["hits"]) == 1


def test_search_with_nothing_found_is_ok_and_empty() -> None:
    result = build().invoke("buscar_equipamiento", {"query": "submarino nuclear"})

    assert result.ok and result.data == {"hits": []}


@pytest.mark.parametrize("query", ["   ", "\u200b"])
def test_a_blank_search_is_invalid_arguments(query: str) -> None:
    result = build().invoke("buscar_equipamiento", {"query": query})

    assert not result.ok and result.error.code == "invalid_arguments"


# --- consultar_disponibilidad ----------


def test_availability_reports_a_shortage_with_requested_and_available() -> None:
    held = (reservation("sound_speaker_15", 2),)

    result = build(held).invoke("consultar_disponibilidad", ARGS)

    assert result.ok
    assert result.data == {
        "is_available": False,
        "shortages": [{"item_code": "sound_speaker_15", "requested": 2, "available": 1}],
    }


def test_availability_ok_when_stock_is_free() -> None:
    result = build().invoke("consultar_disponibilidad", ARGS)

    assert result.data == {"is_available": True, "shortages": []}


def test_a_package_member_shortage_is_reported() -> None:
    args = {**ARGS, "items": [], "packages": [{"code": "pkg_dj", "quantity": 4}]}

    result = build().invoke("consultar_disponibilidad", args)

    assert result.data["is_available"] is False
    assert {s["item_code"] for s in result.data["shortages"]} == {
        "dj_controller",
        "sound_speaker_15",
    }


def test_an_unknown_code_is_reported_by_name() -> None:
    args = {**ARGS, "items": [{"code": "no_existe", "quantity": 1}]}

    for tool in ("consultar_disponibilidad", "calcular_precio"):
        result = build().invoke(tool, args)

        assert not result.ok
        assert (result.error.code, result.error.subject) == ("unknown_code", "no_existe")


# --- calcular_precio ----------


def test_price_is_the_oracle_quote_unmodified() -> None:
    request = EventRequest(
        **{**_domain_fields(), "items": _lines("sound_speaker_15", 2), "packages": ()}
    )
    oracle = calculate_price(request, CATALOG, default_pricing_rules())

    result = build().invoke("calcular_precio", ARGS)

    assert result.ok
    assert result.data == oracle.to_dict()
    assert result.data["total"] == oracle.total.amount


# --- invalid arguments never reach the use case ----------


@pytest.mark.parametrize(
    ("tool", "payload"),
    [
        ("buscar_equipamiento", {"query": "luces", "price_override": 1}),
        ("calcular_precio", {**ARGS, "total": 1}),
        ("calcular_precio", {**ARGS, "items": [{"code": "sound_speaker_15", "quantity": "3"}]}),
        ("calcular_precio", {**ARGS, "guest_count": 0}),
        ("consultar_disponibilidad", {**ARGS, "end": ARGS["start"]}),
        ("consultar_disponibilidad", {**ARGS, "start": "2026-11-14T18:00:00"}),
        ("consultar_disponibilidad", {**ARGS, "items": []}),
        ("consultar_disponibilidad", "not a dict"),
        ("calcular_precio", None),
    ],
)
def test_invalid_arguments_fail_without_calling_the_use_case(tool: str, payload: Any) -> None:
    calls: list[str] = []
    executor = ToolExecutor(
        search=_Spy(calls),
        load_catalog=lambda: calls.append("catalog") or CATALOG,
        check_availability=lambda r: calls.append("availability"),  # type: ignore[arg-type, return-value]
        price=lambda r: calls.append("price"),  # type: ignore[arg-type, return-value]
    )

    result = executor.invoke(tool, payload)

    assert not result.ok and result.error.code == "invalid_arguments"
    assert calls == []


def test_user_text_is_not_echoed_in_the_error() -> None:
    result = build().invoke(
        "buscar_equipamiento", {"query": "ok", "x": "<script>alert(1)</script>"}
    )

    assert "script" not in repr(result) and "alert" not in repr(result)


# --- safe errors ----------


class _Secret(RepositoryUnavailable):
    pass


class _LeakyCatalog:
    def get_catalog(self) -> Any:
        raise RepositoryUnavailable("host db.internal refused the connection")


@pytest.mark.parametrize(
    "tool", ["buscar_equipamiento", "consultar_disponibilidad", "calcular_precio"]
)
def test_repository_down_maps_to_unavailable_without_leaking(tool: str) -> None:
    payload = {"query": "luz"} if tool == "buscar_equipamiento" else ARGS

    result = build(catalog_repository=_LeakyCatalog()).invoke(tool, payload)

    assert not result.ok and result.error.code == "unavailable"
    assert "db.internal" not in repr(result)


def test_a_broken_booking_store_maps_to_unavailable() -> None:
    result = build(booking_repository=BrokenBookingRepository()).invoke(
        "consultar_disponibilidad", ARGS
    )

    assert result.error.code == "unavailable"


def test_a_broken_catalog_fake_maps_to_unavailable() -> None:
    result = build(catalog_repository=BrokenCatalogRepository()).invoke("calcular_precio", ARGS)

    assert result.error.code == "unavailable"


def test_other_failures_are_internal_and_logged_by_class_name_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Boom(Exception):
        pass

    def explode(_: EventRequest) -> Any:
        raise Boom("password=hunter2 SELECT * FROM users")

    executor = build(price=explode)

    with caplog.at_level(logging.INFO, logger="eventssound.adapters.agent.tools"):
        result = executor.invoke("calcular_precio", ARGS)

    assert not result.ok and result.error.code == "internal"
    assert "hunter2" not in repr(result) and "hunter2" not in caplog.text
    assert "Boom" in caplog.text


def test_invalid_stored_data_is_internal() -> None:
    class Corrupt:
        def get_catalog(self) -> Any:
            raise InvalidStoredData("row 3 is bad: secret")

    result = build(catalog_repository=Corrupt()).invoke("calcular_precio", ARGS)

    assert result.error.code == "internal" and "secret" not in repr(result)


def test_error_codes_are_a_closed_set() -> None:
    from eventssound.adapters.agent.tools import ERROR_CODES

    assert {
        "unknown_tool",
        "invalid_arguments",
        "unknown_code",
        "unavailable",
        "internal",
    } == ERROR_CODES


# --- accounting ----------


def test_calls_are_recorded_and_logged_without_arguments_or_results(
    caplog: pytest.LogCaptureFixture,
) -> None:
    executor = build()

    with caplog.at_level(logging.INFO, logger="eventssound.adapters.agent.tools"):
        executor.invoke("buscar_equipamiento", {"query": "parlante secretword"})
        executor.invoke("calcular_precio", ARGS)

    assert executor.calls == ("buscar_equipamiento", "calcular_precio")
    assert "secretword" not in caplog.text and "Parlante" not in caplog.text
    assert "buscar_equipamiento" in caplog.text and "ok" in caplog.text


def test_the_call_budget_stops_the_pipeline() -> None:
    executor = build(max_calls=2)
    executor.invoke("buscar_equipamiento", {"query": "luz"})
    executor.invoke("buscar_equipamiento", {"query": "luz"})

    with pytest.raises(ToolBudgetExceeded):
        executor.invoke("buscar_equipamiento", {"query": "luz"})

    assert len(executor.calls) == 2


def test_rejected_calls_also_consume_the_budget() -> None:
    executor = build(max_calls=1)
    executor.invoke("borrar_catalogo", {})

    with pytest.raises(ToolBudgetExceeded):
        executor.invoke("buscar_equipamiento", {"query": "luz"})


@pytest.mark.parametrize("max_calls", [0, -1, True, 1.5])
def test_the_budget_must_be_a_positive_int(max_calls: object) -> None:
    with pytest.raises(ValueError):
        build(max_calls=max_calls)  # type: ignore[arg-type]


def test_a_result_is_a_plain_immutable_value() -> None:
    result = build().invoke("buscar_equipamiento", {"query": "luz"})

    assert isinstance(result, ToolResult)
    with pytest.raises(AttributeError):
        result.ok = False  # type: ignore[misc]


# --- helpers ----------


class _Spy:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def search(self, *args: object) -> Any:
        self._calls.append("search")
        raise AssertionError("must not be called")


def _domain_fields() -> dict[str, Any]:
    from eventssound.domain.event_request import EventType, VenueType

    return {
        "event_type": EventType.WEDDING,
        "start": datetime(2026, 11, 14, 23, tzinfo=UTC),
        "end": datetime(2026, 11, 15, 4, tzinfo=UTC),
        "guest_count": 120,
        "distance_km": 12,
        "venue": VenueType.OUTDOOR,
    }


def _lines(code: str, quantity: int) -> tuple[Any, ...]:
    from eventssound.domain.event_request import RequestedLine

    return (RequestedLine(code, quantity),)
