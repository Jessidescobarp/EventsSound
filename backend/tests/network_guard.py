"""Test-only network guard: refuse non-loopback connections and name resolution.

Covered: Python-level `socket.socket.connect/connect_ex` (what httpx, httpcore and urllib use)
and `socket.getaddrinfo`. NOT covered: UDP `sendto` on an unconnected socket, sockets opened by
C code such as libpq (psycopg), and code that grabs `_socket` directly. The guard is a safety
net against accidental live calls, not a sandbox.
"""

import ipaddress
import socket
from collections.abc import Callable

import pytest

GUARDED = ("connect", "connect_ex", "getaddrinfo")


def is_loopback(host: object) -> bool:
    """True only for `localhost` and loopback IP literals. `0.0.0.0` and `::` are not loopback."""
    if not isinstance(host, str):
        return False
    if host.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def _blocked() -> RuntimeError:
    return RuntimeError("network disabled in tests: non-loopback access blocked")


def install(monkeypatch: pytest.MonkeyPatch) -> None:
    def wrap(real: Callable[..., object]) -> Callable[..., object]:
        def guarded(self: socket.socket, address: object, *args: object) -> object:
            if self.family in (socket.AF_INET, socket.AF_INET6) and not is_loopback(
                address[0]  # type: ignore[index]
            ):
                raise _blocked()
            return real(self, address, *args)

        return guarded

    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        if host is not None and not is_loopback(host):
            raise _blocked()
        return real_getaddrinfo(host, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", wrap(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", wrap(socket.socket.connect_ex))
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
