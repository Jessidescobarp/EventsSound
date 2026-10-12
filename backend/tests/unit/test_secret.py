"""The API key wrapper never exposes its value except through get_secret_value()."""

import copy
import pickle

import pytest

from eventssound.adapters.secret import Secret, SecretError

KEY = "sk-test-SENTINEL-123"


def test_value_is_only_available_through_get_secret_value() -> None:
    assert Secret(KEY).get_secret_value() == KEY


@pytest.mark.parametrize("render", [repr, str, "{}".format, lambda s: f"{s!r}|{s}|{s:>40}"])
def test_every_rendering_is_masked(render) -> None:  # type: ignore[no-untyped-def]
    rendered = render(Secret(KEY))

    assert KEY not in rendered
    assert "SENTINEL" not in rendered
    assert "*" in rendered


def test_secret_inside_containers_and_exceptions_stays_masked() -> None:
    secret = Secret(KEY)

    assert KEY not in repr({"k": secret, "t": (secret,)})
    assert KEY not in str(ValueError(secret))


def test_equality_compares_values_and_hash_is_consistent() -> None:
    assert Secret(KEY) == Secret(KEY)
    assert Secret(KEY) != Secret("sk-other-key")
    assert Secret(KEY) != KEY
    assert hash(Secret(KEY)) == hash(Secret(KEY))


@pytest.mark.parametrize("dump", [pickle.dumps, copy.copy, copy.deepcopy])
def test_secret_cannot_be_serialised_or_copied(dump) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(TypeError):
        dump(Secret(KEY))


def test_wrap_accepts_plain_strings_secrets_and_secretstr_like_objects() -> None:
    class SecretStrLike:
        def get_secret_value(self) -> str:
            return KEY

    assert Secret.wrap(KEY) == Secret(KEY)
    assert Secret.wrap(Secret(KEY)) == Secret(KEY)
    assert Secret.wrap(SecretStrLike()) == Secret(KEY)


@pytest.mark.parametrize(
    "bad",
    [None, 3, b"sk-bytes-key", "", "has space", "tab\tkey", "new\nline", "nonascii-ñ", "x" * 513],
    ids=["none", "int", "bytes", "empty", "space", "tab", "newline", "non-ascii", "too-long"],
)
def test_invalid_keys_are_rejected_without_echoing_them(bad: object) -> None:
    with pytest.raises(SecretError) as exc:
        Secret.wrap(bad)

    message = str(exc.value)
    assert "printable" in message
    if isinstance(bad, str) and bad:
        assert bad not in message


def test_secretstr_like_returning_a_non_string_is_rejected() -> None:
    class Broken:
        def get_secret_value(self) -> int:
            return 3

    with pytest.raises(SecretError):
        Secret.wrap(Broken())
