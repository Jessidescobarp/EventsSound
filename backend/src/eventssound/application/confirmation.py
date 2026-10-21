"""Short-lived, single-use confirmation tokens for admin changes (stateless HMAC plus a used set).

A token binds the user, the version the change starts from and a hash of the exact change, so it
cannot be replayed with different changes, by another user or against a newer version. It expires
after `ttl_seconds` and is accepted once. The used-nonce set lives in this process only: with
several instances a token could be spent once per instance, and the optimistic `base_version`
check in the repository is the cross-instance backstop (only one writer can win a version).
"""

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_TTL_SECONDS = 300


class ConfirmationError(Exception):
    """A token was refused; `code` is a stable machine code, never a cause."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Claims:
    user_id: str
    base_version: int
    diff_hash: str
    expires_at: int
    nonce: str


def derive_confirmation_key(secret: str) -> bytes:
    """A key bound to this purpose, so the JWT secret itself is never used to sign these."""
    return hmac.new(secret.encode(), b"agent-config-confirm", hashlib.sha256).digest()


def hash_change(action: str, diff: dict) -> str:
    """SHA-256 of the canonical JSON of the action and the field-by-field diff."""
    canonical = json.dumps({"action": action, "diff": diff}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class ConfirmationTokens:
    def __init__(
        self,
        key: bytes,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._key = key
        self._clock = clock
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._used: dict[str, int] = {}  # nonce -> expiry, dropped once expired

    def _sign(self, body: str) -> str:
        return _b64(hmac.new(self._key, body.encode(), hashlib.sha256).digest())

    def issue(self, user_id: str, base_version: int, diff_hash: str) -> tuple[str, int]:
        """The token and its expiry (epoch seconds)."""
        expires_at = int(self._clock()) + self._ttl
        claims = [user_id, base_version, diff_hash, expires_at, secrets.token_urlsafe(12)]
        body = _b64(json.dumps(claims).encode())
        return f"{body}.{self._sign(body)}", expires_at

    def check(self, token: str, user_id: str, base_version: int, diff_hash: str) -> Claims:
        """The claims of a valid token for exactly this user and change, else ConfirmationError."""
        body, _, signature = token.partition(".")
        if not hmac.compare_digest(self._sign(body).encode(), signature.encode()):
            raise ConfirmationError("token_invalid")
        try:
            user, version, digest, expires_at, nonce = json.loads(_unb64(body))
            claims = Claims(str(user), int(version), str(digest), int(expires_at), str(nonce))
        except (ValueError, TypeError):
            raise ConfirmationError("token_invalid") from None
        if self._clock() >= claims.expires_at:
            raise ConfirmationError("token_expired")
        same = (
            hmac.compare_digest(claims.user_id.encode(), user_id.encode())
            & hmac.compare_digest(claims.diff_hash.encode(), diff_hash.encode())
            & (claims.base_version == base_version)
        )
        if not same:
            raise ConfirmationError("token_mismatch")
        if claims.nonce in self._used:
            raise ConfirmationError("token_used")
        return claims

    def consume(self, claims: Claims) -> None:
        """Mark the token spent; atomic, so two concurrent requests cannot both use it."""
        now = self._clock()
        with self._lock:
            self._used = {n: e for n, e in self._used.items() if e > now}
            if claims.nonce in self._used:
                raise ConfirmationError("token_used")
            self._used[claims.nonce] = claims.expires_at
