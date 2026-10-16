"""Admin read API over security events (abuse signals)."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from eventssound.application.errors import RepositoryUnavailable
from eventssound.application.quotes import DEFAULT_PAGE_SIZE
from eventssound.domain.user import Principal, Role
from eventssound.entrypoints.api.auth_kit import refusal_response, require_role
from eventssound.entrypoints.api.routes.records import ERRORS, Limit, Offset
from eventssound.entrypoints.api.schemas import SecurityEventOut, SecurityPageOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

AdminOnly = Annotated[Principal, Depends(require_role(Role.ADMIN))]


@router.get(
    "/security",
    response_model=SecurityPageOut,
    summary="Eventos de seguridad",
    description=(
        "Abuse signals (refused chat messages, rate limits, failed logins, blocked requests), "
        "newest first, with per-kind counts for the last 24 hours. Clients appear as salted "
        "hashes. Admin only."
    ),
    responses=ERRORS,
)
def admin_security(
    request: Request, who: AdminOnly, limit: Limit = DEFAULT_PAGE_SIZE, offset: Offset = 0
) -> SecurityPageOut | JSONResponse:
    log = request.app.state.security_log
    try:
        page = log.page(limit, offset)
        recent = log.summary(datetime.now(UTC) - timedelta(hours=24))
    except RepositoryUnavailable as error:
        logger.warning("security events unavailable error=%s", type(error).__name__)
        return refusal_response(503, "storage_unavailable")
    items = [
        SecurityEventOut(id=e.id, at=e.at.isoformat(), kind=e.kind, client=e.client)
        for e in page.items
    ]
    return SecurityPageOut(
        items=items, total=page.total, limit=page.limit, offset=page.offset, last_24h=recent
    )
