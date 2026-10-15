"""HS256 access tokens behind the `TokenIssuer` port (PyJWT).

The algorithm list is a constant, never a setting, so a token cannot choose its own (`none`).
`exp`, `iss` and `sub` are required. The role claim is trusted until expiry (no revocation).
"""

import time
from collections.abc import Callable

import jwt
from pydantic import SecretStr

from eventssound.application.auth import IssuedToken
from eventssound.domain.user import Principal, Role, User

ALGORITHMS = ["HS256"]
ISSUER = "eventsounddr"


class JwtTokenIssuer:
    def __init__(
        self, secret: SecretStr, ttl_minutes: int, clock: Callable[[], float] = time.time
    ) -> None:
        self._secret = secret
        self._ttl_seconds = ttl_minutes * 60
        self._clock = clock

    def issue(self, user: User) -> IssuedToken:
        now = int(self._clock())
        claims = {
            "sub": user.id,
            "role": user.role.value,
            "iat": now,
            "exp": now + self._ttl_seconds,
            "iss": ISSUER,
        }
        token = jwt.encode(claims, self._secret.get_secret_value(), algorithm=ALGORITHMS[0])
        return IssuedToken(token, self._ttl_seconds, user.role)

    def verify(self, token: str) -> Principal | None:
        try:
            claims = jwt.decode(
                token,
                self._secret.get_secret_value(),
                algorithms=ALGORITHMS,
                issuer=ISSUER,
                options={"require": ["exp", "iss", "sub"]},
            )
            return Principal(str(claims["sub"]), Role(claims["role"]))
        except (jwt.PyJWTError, KeyError, ValueError):
            return None
