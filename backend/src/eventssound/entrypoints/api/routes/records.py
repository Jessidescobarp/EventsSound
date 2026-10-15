"""Read APIs over saved quotes and bookings: `/me/quotes` (any user) and `/admin/*` (admin)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from eventssound.application.errors import RepositoryUnavailable
from eventssound.application.quotes import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from eventssound.domain.user import Principal, Role
from eventssound.entrypoints.api.auth_kit import refusal_response, require_role
from eventssound.entrypoints.api.schemas import (
    BookingOut,
    BookingPageOut,
    QuotePageOut,
    QuoteRecordOut,
)

logger = logging.getLogger(__name__)

me_router = APIRouter(prefix="/me", tags=["Quotes"])
admin_router = APIRouter(prefix="/admin", tags=["Admin"])

Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Page size, 1 to 100.")]
Offset = Annotated[int, Query(ge=0, le=100_000, description="Rows to skip.")]
AnyUser = Annotated[Principal, Depends(require_role(Role.CLIENT, Role.ADMIN))]
AdminOnly = Annotated[Principal, Depends(require_role(Role.ADMIN))]
ERRORS = {
    401: {"description": "not_authenticated"},
    403: {"description": "forbidden"},
    503: {"description": "storage_unavailable"},
}


def _unavailable(error: RepositoryUnavailable) -> JSONResponse:
    logger.warning("records unavailable error=%s", type(error).__name__)
    return refusal_response(503, "storage_unavailable")


def _quotes(request: Request, user_id: str | None, limit: int, offset: int):
    try:
        page = request.app.state.quote_store.page(user_id, limit, offset)
    except RepositoryUnavailable as error:
        return _unavailable(error)
    items = [
        QuoteRecordOut(
            id=q.id,
            created_at=q.created_at.isoformat(),
            registered=q.registered,
            owner_email=q.owner_email,
            event_type=q.event_type,
            event_start=q.event_start.isoformat(),
            event_end=q.event_end.isoformat(),
            guest_count=q.guest_count,
            total_cop=q.total_cop,
            available=q.available,
            quote=q.quote,
            event_request=q.event_request,
        )
        for q in page.items
    ]
    return QuotePageOut(items=items, total=page.total, limit=page.limit, offset=page.offset)


@me_router.get(
    "/quotes",
    response_model=QuotePageOut,
    summary="Mis cotizaciones",
    description="Quotes made while logged in as the caller, newest first.",
    responses=ERRORS,
)
def my_quotes(request: Request, who: AnyUser, limit: Limit = DEFAULT_PAGE_SIZE, offset: Offset = 0):
    return _quotes(request, who.user_id, limit, offset)


@admin_router.get(
    "/quotes",
    response_model=QuotePageOut,
    summary="Todas las cotizaciones",
    description="Every saved quote, newest first. Admin only.",
    responses=ERRORS,
)
def admin_quotes(
    request: Request, who: AdminOnly, limit: Limit = DEFAULT_PAGE_SIZE, offset: Offset = 0
):
    return _quotes(request, None, limit, offset)


@admin_router.get(
    "/bookings",
    response_model=BookingPageOut,
    summary="Todas las reservas",
    description="Equipment bookings, newest first. Admin only.",
    responses=ERRORS,
)
def admin_bookings(
    request: Request, who: AdminOnly, limit: Limit = DEFAULT_PAGE_SIZE, offset: Offset = 0
):
    try:
        page = request.app.state.booking_lister.page(limit, offset)
    except RepositoryUnavailable as error:
        return _unavailable(error)
    items = [
        BookingOut(
            booking_code=b.booking_code,
            item_code=b.item_code,
            quantity=b.quantity,
            starts_at=b.starts_at.isoformat(),
            ends_at=b.ends_at.isoformat(),
            status=b.status,
            created_at=b.created_at.isoformat(),
        )
        for b in page.items
    ]
    return BookingPageOut(items=items, total=page.total, limit=page.limit, offset=page.offset)
