import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from eventssound.application.auth import InvalidCredentials, normalize_email
from eventssound.application.errors import RepositoryUnavailable
from eventssound.application.quote_chat import RateLimited
from eventssound.entrypoints.api.auth_kit import AuthKit, refusal_response
from eventssound.entrypoints.api.client_ip import client_ip
from eventssound.entrypoints.api.schemas import LoginIn, LoginOut

router = APIRouter(prefix="/auth", tags=["Auth"])

logger = logging.getLogger(__name__)


@router.post(
    "/login",
    response_model=LoginOut,
    summary="Iniciar sesion",
    description=(
        "Exchange an email and password for a bearer token (HS256, 60 minutes, no refresh). "
        "Wrong credentials and unknown emails answer the same 401. Attempts are rate limited "
        "per address and per email. All accounts are synthetic."
    ),
    responses={
        401: {"description": "invalid_credentials"},
        429: {"description": "rate_limited (see Retry-After)"},
        503: {"description": "auth_not_configured or auth_unavailable"},
    },
)
def login(body: LoginIn, request: Request) -> JSONResponse:
    kit: AuthKit | None = request.app.state.auth
    if kit is None:
        return refusal_response(503, "auth_not_configured")
    email = normalize_email(body.email)
    try:
        decisions = (
            kit.ip_limiter.hit(client_ip(request, request.app.state.settings.trusted_proxy_hops)),
            kit.email_limiter.hit(email),
        )
    except RateLimited as exc:  # a failing limiter refuses, like a denied one
        return refusal_response(
            429, "rate_limited", **{"Retry-After": str(exc.retry_after_seconds)}
        )
    denied = [d for d in decisions if not d.allowed]
    if denied:
        retry = max(1, max(d.retry_after_seconds for d in denied))
        return refusal_response(429, "rate_limited", **{"Retry-After": str(retry)})
    try:
        issued = kit.service.login(email, body.password)
    except InvalidCredentials:
        return refusal_response(401, "invalid_credentials")
    except RepositoryUnavailable:
        logger.warning("login storage unavailable")
        return refusal_response(503, "auth_unavailable")
    payload = LoginOut(
        access_token=issued.token, expires_in=issued.expires_in, role=issued.role.value
    )
    return JSONResponse(payload.model_dump(), headers={"Cache-Control": "no-store"})
