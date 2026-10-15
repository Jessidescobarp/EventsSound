"""Admin edits of the catalog: create and update items (equipment, services) and packages."""

import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from eventssound.application.catalog_admin import CatalogAdmin
from eventssound.application.errors import CodeTaken, NotFound, RepositoryUnavailable
from eventssound.domain.catalog import EquipmentItem, PackageLine, ServicePackage
from eventssound.domain.errors import DomainError, UnknownCatalogEntry
from eventssound.domain.money import Money
from eventssound.domain.user import Principal, Role
from eventssound.entrypoints.api.auth_kit import refusal_response, require_role
from eventssound.entrypoints.api.schemas import (
    ItemCreateIn,
    ItemFieldsIn,
    PackageCreateIn,
    PackageFieldsIn,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/catalog", tags=["Admin"])

AdminOnly = Annotated[Principal, Depends(require_role(Role.ADMIN))]
ERRORS = {
    401: {"description": "not_authenticated"},
    403: {"description": "forbidden"},
    404: {"description": "not_found"},
    409: {"description": "code_taken"},
    422: {"description": "invalid_catalog_entry or unknown_item"},
    503: {"description": "storage_unavailable"},
}


def _admin(request: Request) -> CatalogAdmin:
    return request.app.state.catalog_admin


def _apply(action: Callable[[], None], status: int) -> JSONResponse:
    """Run one write and map its failures to fixed, coded bodies (no cause reaches the client)."""
    try:
        action()
    except CodeTaken:
        return refusal_response(409, "code_taken")
    except NotFound:
        return refusal_response(404, "not_found")
    except UnknownCatalogEntry:
        return refusal_response(422, "unknown_item")
    except DomainError:
        return refusal_response(422, "invalid_catalog_entry")
    except RepositoryUnavailable as error:
        logger.warning("catalog write unavailable error=%s", type(error).__name__)
        return refusal_response(503, "storage_unavailable")
    return JSONResponse(
        {"status": "saved"}, status_code=status, headers={"Cache-Control": "no-store"}
    )


def _item(code: str, body: ItemFieldsIn) -> EquipmentItem:
    return EquipmentItem(
        code=code,
        name=body.name,
        category=body.category,
        stock_quantity=body.stock_quantity,
        unit_price=Money(body.unit_price_cop),
    )


def _package(code: str, body: PackageFieldsIn) -> ServicePackage:
    return ServicePackage(
        code=code,
        name=body.name,
        lines=tuple(PackageLine(line.item_code, line.quantity) for line in body.lines),
        discount_bps=body.discount_bps,
    )


@router.post("/items", status_code=201, summary="Create an item", responses=ERRORS)
def create_item(request: Request, _who: AdminOnly, body: ItemCreateIn):
    return _guard(
        lambda: _item(body.code, body), lambda item: _admin(request).create_item(item), 201
    )


@router.put("/items/{code}", summary="Edit an item (the code never changes)", responses=ERRORS)
def update_item(request: Request, _who: AdminOnly, code: str, body: ItemFieldsIn):
    return _guard(lambda: _item(code, body), lambda item: _admin(request).update_item(item), 200)


@router.post("/packages", status_code=201, summary="Create a package", responses=ERRORS)
def create_package(request: Request, _who: AdminOnly, body: PackageCreateIn):
    return _guard(
        lambda: _package(body.code, body), lambda pkg: _admin(request).create_package(pkg), 201
    )


@router.put("/packages/{code}", summary="Edit a package (the code never changes)", responses=ERRORS)
def update_package(request: Request, _who: AdminOnly, code: str, body: PackageFieldsIn):
    return _guard(
        lambda: _package(code, body), lambda pkg: _admin(request).update_package(pkg), 200
    )


def _guard[T](build: Callable[[], T], run: Callable[[T], None], status: int) -> JSONResponse:
    """Build the domain object (rules are checked there), then store it."""
    try:
        entry = build()
    except DomainError:
        return refusal_response(422, "invalid_catalog_entry")
    return _apply(lambda: run(entry), status)
