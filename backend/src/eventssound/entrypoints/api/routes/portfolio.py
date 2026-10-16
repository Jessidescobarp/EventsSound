"""Portfolio events: the public list and the admin edits (create, edit, hide)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse

from eventssound.application.errors import InvalidStoredData, NotFound, RepositoryUnavailable
from eventssound.application.portfolio import StoredPortfolioEvent
from eventssound.domain.errors import DomainError
from eventssound.domain.portfolio import PortfolioEvent
from eventssound.domain.user import Principal, Role
from eventssound.entrypoints.api.auth_kit import refusal_response, require_role
from eventssound.entrypoints.api.schemas import PortfolioEventIn, PortfolioEventOut, PortfolioOut

logger = logging.getLogger(__name__)

public_router = APIRouter(prefix="/portfolio", tags=["Portfolio"])
admin_router = APIRouter(prefix="/admin/portfolio", tags=["Admin"])

AdminOnly = Annotated[Principal, Depends(require_role(Role.ADMIN))]
ERRORS = {
    401: {"description": "not_authenticated"},
    403: {"description": "forbidden"},
    404: {"description": "not_found"},
    422: {"description": "invalid_portfolio_event"},
    503: {"description": "storage_unavailable"},
}


def _out(stored: StoredPortfolioEvent) -> PortfolioEventOut:
    event = stored.event
    return PortfolioEventOut(
        id=stored.id,
        title=event.title,
        kind=event.kind,
        description=event.description,
        equipment=list(event.equipment),
        visible=event.visible,
    )


def _list(request: Request, visible_only: bool):
    try:
        events = request.app.state.portfolio_store.list_events(visible_only)
    except RepositoryUnavailable as error:
        logger.warning("portfolio unavailable error=%s", type(error).__name__)
        return refusal_response(503, "storage_unavailable")
    except InvalidStoredData:
        logger.error("portfolio row invalid")
        return refusal_response(503, "storage_unavailable")
    return PortfolioOut(events=[_out(e) for e in events])


def _event(body: PortfolioEventIn) -> PortfolioEvent:
    return PortfolioEvent(
        body.title, body.kind, body.description, tuple(body.equipment), body.visible
    )


@public_router.get(
    "",
    response_model=PortfolioOut,
    summary="Portfolio of past events",
    responses={503: ERRORS[503]},
)
def get_portfolio(request: Request):
    return _list(request, visible_only=True)


@admin_router.get(
    "", response_model=PortfolioOut, summary="All events, hidden too", responses=ERRORS
)
def get_all(request: Request, _who: AdminOnly):
    return _list(request, visible_only=False)


@admin_router.post("", status_code=201, summary="Create an event", responses=ERRORS)
def create_event(request: Request, _who: AdminOnly, body: PortfolioEventIn):
    try:
        event_id = request.app.state.portfolio_store.add(_event(body))
    except DomainError:
        return refusal_response(422, "invalid_portfolio_event")
    except RepositoryUnavailable:
        return refusal_response(503, "storage_unavailable")
    logger.info("portfolio event created id=%s", event_id)
    return JSONResponse({"id": event_id}, status_code=201, headers={"Cache-Control": "no-store"})


@admin_router.put("/{event_id}", summary="Edit or hide an event", responses=ERRORS)
def update_event(
    request: Request,
    _who: AdminOnly,
    event_id: Annotated[int, Path(ge=1, le=2**62)],
    body: PortfolioEventIn,
):
    try:
        request.app.state.portfolio_store.update(event_id, _event(body))
    except DomainError:
        return refusal_response(422, "invalid_portfolio_event")
    except NotFound:
        return refusal_response(404, "not_found")
    except RepositoryUnavailable:
        return refusal_response(503, "storage_unavailable")
    logger.info("portfolio event updated id=%s visible=%s", event_id, body.visible)
    return JSONResponse({"id": event_id}, headers={"Cache-Control": "no-store"})
