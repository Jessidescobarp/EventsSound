"""The autouse guard in conftest.py makes any non-loopback connection fail loudly."""

import socket

import httpx
import pytest


@pytest.mark.parametrize("host", ["192.0.2.1", "203.0.113.9", "2001:db8::1", "example.com"])
def test_connecting_to_a_non_loopback_host_is_blocked(host: str) -> None:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with (
        socket.socket(family, socket.SOCK_STREAM) as sock,
        pytest.raises(RuntimeError, match="network disabled"),
    ):
        sock.connect((host, 80))


def test_connect_ex_is_blocked_too() -> None:
    with socket.socket() as sock, pytest.raises(RuntimeError, match="network disabled"):
        sock.connect_ex(("192.0.2.1", 80))


def test_a_real_httpx_client_cannot_reach_the_network() -> None:
    with httpx.Client() as client, pytest.raises(RuntimeError, match="network disabled"):
        client.get("https://192.0.2.1/")


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_is_allowed_through_to_the_real_socket(host: str) -> None:
    # Port 9 (discard) is closed locally: the real socket answers, so the guard did not block.
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        with pytest.raises(OSError) as exc:
            sock.connect((host, 9))
    assert "network disabled" not in str(exc.value)


@pytest.mark.parametrize(
    "host",
    ["example.com", "openrouter.ai", "192.0.2.1", "0.0.0.0", "10.0.0.5", "2001:db8::1", "::"],
)
def test_resolving_a_non_loopback_name_is_blocked(host: str) -> None:
    with pytest.raises(RuntimeError, match="network disabled"):
        socket.getaddrinfo(host, 443)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.2"])
def test_resolving_loopback_names_still_works(host: str) -> None:
    assert socket.getaddrinfo(host, 5432)


def test_getaddrinfo_without_a_host_is_not_blocked() -> None:
    # host=None means the wildcard/loopback of the local machine (used by servers, not clients).
    assert socket.getaddrinfo(None, 0, socket.AF_INET, socket.SOCK_STREAM)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("localhost", True),
        ("127.0.0.1", True),
        ("127.1.2.3", True),
        ("::1", True),
        ("::ffff:127.0.0.1", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.168.1.10", False),
        ("localhost.evil.example", False),
        ("LOCALHOST", True),
        ("127.0.0.1.example.com", False),
        ("", False),
        (None, False),
        (b"127.0.0.1", False),
        (127, False),
    ],
)
def test_loopback_classification(host: object, expected: bool) -> None:
    from network_guard import is_loopback

    assert is_loopback(host) is expected


def test_the_guard_is_installed_by_the_autouse_fixture_and_restored_after() -> None:
    from network_guard import GUARDED

    assert socket.socket.connect.__name__ == "guarded"  # wrapper from network_guard.install
    assert socket.getaddrinfo.__name__ == "guarded_getaddrinfo"
    assert GUARDED == ("connect", "connect_ex", "getaddrinfo")
