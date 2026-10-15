"""Argon2 hashing and HS256 tokens: round trips plus every way a token can be bad."""

import time

import jwt
import pytest
from pydantic import SecretStr

from eventssound.adapters.auth.hasher import Argon2Hasher
from eventssound.adapters.auth.tokens import JwtTokenIssuer
from eventssound.domain.user import Principal, Role, User

SECRET = SecretStr("s" * 40)
USER = User("22222222-2222-4222-8222-222222222222", "ana@example.com", Role.ADMIN, "x")


def test_hash_verifies_only_the_right_password_and_never_the_plain_text() -> None:
    hasher = Argon2Hasher()
    stored = hasher.hash("correct horse battery")

    assert stored.startswith("$argon2id$") and "correct horse" not in stored
    assert hasher.verify(stored, "correct horse battery") is True
    assert hasher.verify(stored, "wrong") is False
    assert hasher.verify("not-a-hash", "anything") is False  # a corrupt row is a failed login


def issuer(ttl_minutes: int = 60, secret: SecretStr = SECRET) -> JwtTokenIssuer:
    return JwtTokenIssuer(secret, ttl_minutes)


def test_issued_token_round_trips_to_a_principal_with_its_ttl() -> None:
    issued = issuer(30).issue(USER)

    assert issued.expires_in == 30 * 60 and issued.role is Role.ADMIN
    assert issuer().verify(issued.token) == Principal(USER.id, Role.ADMIN)


def forge(**overrides: object) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": USER.id,
        "role": "admin",
        "iat": now,
        "exp": now + 600,
        "iss": "eventsounddr",
    }
    claims.update(overrides)
    return jwt.encode(
        {k: v for k, v in claims.items() if v is not None}, SECRET.get_secret_value(), "HS256"
    )


@pytest.mark.parametrize(
    "token",
    [
        forge(exp=int(time.time()) - 5),
        forge(exp=None),
        forge(iss="someone-else"),
        forge(role="superuser"),
        forge(sub=None),
        jwt.encode(
            {"sub": "x", "role": "admin", "exp": int(time.time()) + 60, "iss": "eventsounddr"},
            "",
            "none",
        ),
        jwt.encode(
            {"sub": USER.id, "role": "admin", "exp": int(time.time()) + 60, "iss": "eventsounddr"},
            "other" * 10,
            "HS256",
        ),
        forge() + "x",
        "",
        "garbage",
    ],
    ids=[
        "expired",
        "no-exp",
        "wrong-iss",
        "bad-role",
        "no-sub",
        "alg-none",
        "wrong-key",
        "tampered",
        "empty",
        "garbage",
    ],
)
def test_every_bad_token_verifies_to_none(token: str) -> None:
    assert issuer().verify(token) is None


def test_concurrent_verifications_are_capped_to_protect_the_small_instance() -> None:
    import threading
    from types import SimpleNamespace

    hasher = Argon2Hasher(max_concurrent=2)
    stored = hasher.hash("pw-for-the-cap-test")
    live = peak = 0
    lock = threading.Lock()
    real_verify = hasher._hasher.verify

    def spy(*args: object) -> bool:
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.05)
        with lock:
            live -= 1
        return real_verify(*args)  # type: ignore[arg-type]

    hasher._hasher = SimpleNamespace(verify=spy)  # type: ignore[assignment]
    threads = [threading.Thread(target=hasher.verify, args=(stored, "x")) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak <= 2
