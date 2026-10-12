"""The three read-only tools and the executor that dispatches them.

The graph, never the model, picks the tool. Model text only supplies arguments, which are
validated first; a name outside the allowlist runs nothing. Failures come back as closed-set
`ToolError`s with fixed messages: no exception text, SQL, host or user string reaches the caller.
Money is only produced by the injected `price` callable (the deterministic domain oracle).
"""

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from eventssound.adapters.agent.tool_schemas import EventRequestArgs, SearchArgs
from eventssound.application.errors import RepositoryUnavailable
from eventssound.application.search import EquipmentSearch, InvalidSearch
from eventssound.domain.availability import AvailabilityReport
from eventssound.domain.catalog import Catalog
from eventssound.domain.errors import DomainError, UnknownCatalogEntry
from eventssound.domain.event_request import EventRequest
from eventssound.domain.pricing import Quote

logger = logging.getLogger(__name__)

ALLOWED_TOOLS = frozenset({"buscar_equipamiento", "consultar_disponibilidad", "calcular_precio"})
ERROR_CODES = frozenset(
    {"unknown_tool", "invalid_arguments", "unknown_code", "unavailable", "internal"}
)
_MESSAGES = {
    "unknown_tool": "The requested tool does not exist.",
    "invalid_arguments": "The tool arguments are not valid.",
    "unknown_code": "A requested code is not in the catalog.",
    "unavailable": "The data source is temporarily unavailable.",
    "internal": "The tool failed unexpectedly.",
}
_NAME_CHARS = re.compile(r"[^A-Za-z0-9_]")


class ToolBudgetExceeded(Exception):
    """More tool calls than the per-request budget allows: the pipeline must stop."""


@dataclass(frozen=True, slots=True)
class ToolError:
    code: str
    message: str
    subject: str | None = None  # only a catalog-code-shaped string (unknown_code), never free text


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None


def _failure(code: str, subject: str | None = None) -> ToolResult:
    return ToolResult(False, None, ToolError(code, _MESSAGES[code], subject))


def _log_name(name: object) -> str:
    """A bounded, identifier-only form of a possibly hostile tool name."""
    return _NAME_CHARS.sub("?", str(name)[:40])


class ToolExecutor:
    """One instance per chat request: it owns that request's call budget."""

    def __init__(
        self,
        *,
        search: EquipmentSearch,
        load_catalog: Callable[[], Catalog],
        check_availability: Callable[[EventRequest], AvailabilityReport],
        price: Callable[[EventRequest], Quote],
        max_calls: int = 6,
    ) -> None:
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("max_calls must be a positive int")
        self._search = search
        self._load_catalog = load_catalog
        self._check_availability = check_availability
        self._price = price
        self._max_calls = max_calls
        self._attempts = 0
        self._calls: list[str] = []
        self.handlers: dict[str, Callable[[Any], dict[str, Any]]] = {
            "buscar_equipamiento": self._buscar_equipamiento,
            "consultar_disponibilidad": self._consultar_disponibilidad,
            "calcular_precio": self._calcular_precio,
        }

    @property
    def calls(self) -> tuple[str, ...]:
        """Names of the allowlisted tools that were dispatched, in order."""
        return tuple(self._calls)

    def invoke(self, name: str, arguments: Any) -> ToolResult:
        if self._attempts >= self._max_calls:
            raise ToolBudgetExceeded("tool call budget exhausted")
        self._attempts += 1
        started = time.monotonic()
        allowed = isinstance(name, str) and name in ALLOWED_TOOLS
        if allowed:
            self._calls.append(name)
            result = self._run(self.handlers[name], arguments)
        else:
            result = _failure("unknown_tool")
        logger.info(
            "tool name=%s outcome=%s duration_ms=%d",
            _log_name(name),
            "ok" if result.ok else result.error.code,  # type: ignore[union-attr]
            (time.monotonic() - started) * 1000,
        )
        return result

    def _run(self, handler: Callable[[Any], dict[str, Any]], arguments: Any) -> ToolResult:
        try:
            return ToolResult(True, handler(arguments))
        except (ValidationError, InvalidSearch):
            return _failure("invalid_arguments")
        except UnknownCatalogEntry as exc:
            return _failure("unknown_code", exc.code)
        except DomainError:
            return _failure("invalid_arguments")
        except RepositoryUnavailable:
            return _failure("unavailable")
        except Exception as exc:  # noqa: BLE001  (anything else is "internal", class name only)
            logger.error("tool failed: %s", type(exc).__name__)
            return _failure("internal")

    def _buscar_equipamiento(self, arguments: Any) -> dict[str, Any]:
        args = SearchArgs.model_validate(arguments)
        (found,) = self._search.search([args.query], args.category, args.limit)
        catalog = self._load_catalog()
        hits: list[dict[str, Any]] = []
        for hit in found.hits:
            if hit.kind == "item":
                item = catalog.item(hit.code)
                name, category = item.name, item.category.value
                unit_price_cop = item.unit_price.amount
            else:
                package = catalog.package(hit.code)
                name, category = package.name, None
                unit_price_cop = package.base_unit_price(catalog).amount
            hits.append(
                {
                    "code": hit.code,
                    "name": name,
                    "category": category,
                    "unit_price_cop": unit_price_cop,
                    "kind": hit.kind,
                    "rank": hit.rank,
                }
            )
        return {"hits": hits}

    def _consultar_disponibilidad(self, arguments: Any) -> dict[str, Any]:
        request = EventRequestArgs.model_validate(arguments).to_domain()
        report = self._check_availability(request)
        return {
            "is_available": report.is_available,
            "shortages": [
                {"item_code": s.item_code, "requested": s.requested, "available": s.remaining}
                for s in report.shortages
            ],
        }

    def _calcular_precio(self, arguments: Any) -> dict[str, Any]:
        request = EventRequestArgs.model_validate(arguments).to_domain()
        return self._price(request).to_dict()
