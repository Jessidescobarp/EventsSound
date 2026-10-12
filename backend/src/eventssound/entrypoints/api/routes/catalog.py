import logging
from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from eventssound.application.catalog import list_catalog
from eventssound.application.errors import InvalidStoredData, RepositoryUnavailable
from eventssound.domain.catalog import Catalog
from eventssound.entrypoints.api.schemas import (
    ErrorOut,
    ItemsResponse,
    PackagesResponse,
)

router = APIRouter(prefix="/catalog", tags=["Catalog"])

logger = logging.getLogger(__name__)

ERRORS = {
    503: {"model": ErrorOut, "description": "The catalog storage is not reachable."},
    500: {"model": ErrorOut, "description": "A stored catalog row is invalid."},
}


def _serve[T](request: Request, build: Callable[[Catalog], T]) -> T | JSONResponse:
    """Read the catalog and map storage failures to fixed bodies (no detail reaches the client)."""
    try:
        return build(list_catalog(request.app.state.catalog_repository))
    except RepositoryUnavailable as exc:
        logger.warning("catalog unavailable: %s", exc)
        return JSONResponse({"detail": "catalog_unavailable"}, status_code=503)
    except InvalidStoredData as exc:
        logger.error("catalog invalid: %s", exc)
        return JSONResponse({"detail": "catalog_invalid"}, status_code=500)


@router.get(
    "/items",
    response_model=ItemsResponse,
    summary="List rentable equipment",
    description=(
        "Every piece of equipment the company rents out, ordered by code, with the units in "
        "stock and the daily rental price in Colombian pesos. All data is synthetic."
    ),
    responses=ERRORS,
)
def get_items(request: Request) -> ItemsResponse | JSONResponse:
    return _serve(request, ItemsResponse.from_domain)


@router.get(
    "/packages",
    response_model=PackagesResponse,
    summary="List equipment packages",
    description=(
        "Ready-made bundles of equipment, ordered by code. Each one lists its items, its "
        "discount and the daily base price before that discount. All data is synthetic."
    ),
    responses=ERRORS,
)
def get_packages(request: Request) -> PackagesResponse | JSONResponse:
    return _serve(request, PackagesResponse.from_domain)
