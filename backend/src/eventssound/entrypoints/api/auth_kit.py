"""Everything the auth routes need, built once at startup, plus the `require_role` dependency.

`require_role` is a deliberate exception to "routes read `app.state`": a FastAPI dependency is
the idiomatic place for authorization, and it is confined to this module.
"""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse

from eventssound.application.auth import AuthService, TokenIssuer
from eventssound.application.messages_es_auth import AUTH_ERRORS
from eventssound.application.usage import RateLimiter
from eventssound.domain.user import Principal, Role


@dataclass(frozen=True, slots=True)
class AuthKit:
    service: AuthService
    tokens: TokenIssuer
    ip_limiter: RateLimiter
    email_limiter: RateLimiter


class AuthRefusal(Exception):
    """An auth dependency refused the request; `refusal_handler` renders the public body."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def refusal_response(status: int, code: str, **headers: str) -> JSONResponse:
    headers = {"Cache-Control": "no-store", **headers}
    return JSONResponse(
        {"detail": code, "message": AUTH_ERRORS[code]}, status_code=status, headers=headers
    )


def refusal_handler(_: Request, exc: AuthRefusal) -> JSONResponse:
    extra = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else {}
    return refusal_response(exc.status, exc.code, **extra)


def optional_principal(request: Request) -> Principal | None:
    """Who the bearer token says is calling; None for no token, a bad one, or auth disabled."""
    kit: AuthKit | None = request.app.state.auth
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if kit is None or scheme.lower() != "bearer":
        return None
    return kit.tokens.verify(token.strip())


def require_role(*roles: Role) -> Callable[[Request], Principal]:
    """Dependency: a valid bearer token whose role is one of `roles`, else 401 or 403."""

    def dependency(request: Request) -> Principal:
        kit: AuthKit | None = request.app.state.auth
        if kit is None:
            raise AuthRefusal(503, "auth_not_configured")
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        principal = kit.tokens.verify(token.strip()) if scheme.lower() == "bearer" else None
        if principal is None:
            raise AuthRefusal(401, "not_authenticated")
        if principal.role not in roles:
            raise AuthRefusal(403, "forbidden")
        return principal

    return dependency
