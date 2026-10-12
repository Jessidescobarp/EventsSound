from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from eventssound.application.catalog import list_catalog
from eventssound.application.errors import RepositoryUnavailable
from eventssound.entrypoints.api.schemas import (
    ErrorOut,
    ItemsResponse,
    PackagesResponse,
)

router = APIRouter(prefix="/catalog", tags=["Catalog"])

UNAVAILABLE = {503: {"model": ErrorOut, "description": "The catalog storage is not reachable."}}


def _unavailable() -> JSONResponse:
    return JSONResponse({"detail": "catalog_unavailable"}, status_code=503)


@router.get(
    "/items",
    response_model=ItemsResponse,
    summary="List rentable equipment",
    description=(
        "Every piece of equipment the company rents out, ordered by code, with the units in "
        "stock and the daily rental price in Colombian pesos. All data is synthetic."
    ),
    responses=UNAVAILABLE,
)
def get_items(request: Request) -> ItemsResponse | JSONResponse:
    try:
        return ItemsResponse.from_domain(list_catalog(request.app.state.catalog_repository))
    except RepositoryUnavailable:
        return _unavailable()


@router.get(
    "/packages",
    response_model=PackagesResponse,
    summary="List equipment packages",
    description=(
        "Ready-made bundles of equipment, ordered by code. Each one lists its items, its "
        "discount and the daily base price before that discount. All data is synthetic."
    ),
    responses=UNAVAILABLE,
)
def get_packages(request: Request) -> PackagesResponse | JSONResponse:
    try:
        return PackagesResponse.from_domain(list_catalog(request.app.state.catalog_repository))
    except RepositoryUnavailable:
        return _unavailable()
