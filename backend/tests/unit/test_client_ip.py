"""client_ip: which address is the rate-limit key, for every shape of X-Forwarded-For."""

import pytest
from starlette.requests import Request

from eventssound.entrypoints.api.client_ip import client_ip

PEER = "10.0.0.1"
V6 = "2001:db8:1:2::/64"


def make_request(lines, peer=PEER) -> Request:
    headers = [(b"x-forwarded-for", line.encode()) for line in lines]
    return Request({"type": "http", "headers": headers, "client": (peer, 5000)})


@pytest.mark.parametrize(
    ("hops", "lines", "expected"),
    [
        (0, ["1.1.1.1"], PEER),  # ignored by default
        (1, ["6.6.6.6, 1.1.1.1"], "1.1.1.1"),
        (2, ["6.6.6.6, 1.1.1.1, 10.0.0.9"], "1.1.1.1"),
        (3, ["1.1.1.1, 10.0.0.8, 10.0.0.9"], "1.1.1.1"),
        (1, ["6.6.6.6", "1.1.1.1"], "1.1.1.1"),  # several header lines form one chain
        (2, ["6.6.6.6,1.1.1.1", "10.0.0.9"], "1.1.1.1"),
        (1, ["2001:db8:1:2:aaaa::1"], V6),  # IPv6 groups by /64
        (1, ["2001:db8:1:2:bbbb::2"], V6),
        (1, ["::ffff:1.2.3.4"], "1.2.3.4"),  # mapped IPv6 is the IPv4 address
        (1, ["1.2.3.4:5678"], "1.2.3.4"),
        (1, ["[2001:db8:1:2::1]:443"], V6),
        (1, [""], PEER),
        (1, ["garbage"], PEER),
        (1, ["1.1.1.1, not-an-ip"], PEER),
        (3, ["6.6.6.6, 1.1.1.1"], PEER),  # more hops than the chain has
        (1, [], PEER),
        (0, [], PEER),
    ],
)
def test_client_key(hops, lines, expected) -> None:
    assert client_ip(make_request(lines), hops) == expected


def test_peer_is_normalized_too() -> None:
    assert client_ip(make_request([], "::ffff:9.9.9.9"), 0) == "9.9.9.9"
