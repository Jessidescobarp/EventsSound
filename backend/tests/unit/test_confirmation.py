"""Confirmation tokens: bound to user, base version and change; expiring; single use."""

import pytest

from eventssound.application.confirmation import (
    ConfirmationError,
    ConfirmationTokens,
    derive_confirmation_key,
    hash_change,
)

KEY = derive_confirmation_key("a-long-enough-secret-for-the-tests-0123456789")
DIFF = {"tone": ["neutral", "formal"]}
DIGEST = hash_change("save", DIFF)


class Clock:
    now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def make(clock: Clock | None = None) -> ConfirmationTokens:
    return ConfirmationTokens(KEY, clock=clock or Clock(), ttl_seconds=300)


def test_a_fresh_token_verifies_and_is_spent_once() -> None:
    tokens = make()
    token, expires_at = tokens.issue("u1", 3, DIGEST)

    claims = tokens.check(token, "u1", 3, DIGEST)
    tokens.consume(claims)

    assert expires_at == 1_000_300
    for retry in (tokens.check, lambda *a: tokens.consume(tokens.check(*a))):
        with pytest.raises(ConfirmationError) as error:
            retry(token, "u1", 3, DIGEST)
        assert error.value.code == "token_used"


def test_the_hash_depends_on_the_action_and_every_field_value() -> None:
    assert (
        len({DIGEST, hash_change("rollback", DIFF), hash_change("save", {"tone": ["a", "b"]})}) == 3
    )


@pytest.mark.parametrize(
    ("user", "base", "digest", "code"),
    [
        ("u2", 3, DIGEST, "token_mismatch"),  # another admin
        ("u1", 4, DIGEST, "token_mismatch"),  # another version
        ("u1", 3, hash_change("save", {"tone": ["neutral", "cercano"]}), "token_mismatch"),
    ],
)
def test_a_token_only_works_for_the_exact_user_version_and_change(
    user: str, base: int, digest: str, code: str
) -> None:
    tokens = make()
    token, _ = tokens.issue("u1", 3, DIGEST)

    with pytest.raises(ConfirmationError) as error:
        tokens.check(token, user, base, digest)
    assert error.value.code == code


def test_an_expired_token_is_refused() -> None:
    clock = Clock()
    tokens = make(clock)
    token, _ = tokens.issue("u1", 3, DIGEST)
    clock.now += 300

    with pytest.raises(ConfirmationError) as error:
        tokens.check(token, "u1", 3, DIGEST)
    assert error.value.code == "token_expired"


def test_forged_tampered_and_foreign_key_tokens_are_invalid() -> None:
    tokens = make()
    token, _ = tokens.issue("u1", 3, DIGEST)
    body, _, signature = token.partition(".")
    forged_body = body[:-2] + ("AA" if body[-2:] != "AA" else "BB")
    other_key = ConfirmationTokens(
        derive_confirmation_key("another-secret-of-sufficient-length-99")
    )
    foreign, _ = other_key.issue("u1", 3, DIGEST)

    for bad in ("", "x", "a.b", f"{forged_body}.{signature}", f"{body}.", foreign, f".{signature}"):
        with pytest.raises(ConfirmationError) as error:
            tokens.check(bad, "u1", 3, DIGEST)
        assert error.value.code == "token_invalid"


def test_spent_nonces_are_dropped_once_expired() -> None:
    clock = Clock()
    tokens = make(clock)
    first, _ = tokens.issue("u1", 3, DIGEST)
    tokens.consume(tokens.check(first, "u1", 3, DIGEST))
    clock.now += 301
    second, _ = tokens.issue("u1", 3, DIGEST)
    tokens.consume(tokens.check(second, "u1", 3, DIGEST))

    assert len(tokens._used) == 1  # noqa: SLF001
