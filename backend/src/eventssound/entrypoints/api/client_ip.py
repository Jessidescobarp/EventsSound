"""Safe client address for rate limiting (D32).

`X-Forwarded-For` is `client, proxy1, proxy2, ...`: every proxy appends the address it saw on
the right, while the client controls everything on the left. With `trusted_hops` proxies in
front, the client is the entry that many places from the right. By default (0) the header is
ignored. `TRUSTED_PROXY_HOPS` must be verified on the real platform (see deploy.md): too high
lets a client pick its own key, too low groups everyone behind the proxy address.
"""

import ipaddress

from fastapi import Request

UNKNOWN = "unknown"


def _parse(value: str) -> str | None:
    """Canonical text of an address, tolerating `ip:port`, `[v6]:port` and zone ids.

    IPv4-mapped IPv6 becomes IPv4; other IPv6 collapses to its /64 (one subscriber owns it).
    """
    text = value.strip().strip('"')
    if text.startswith("["):
        text = text[1:].partition("]")[0]
    elif text.count(":") == 1:
        text = text.partition(":")[0]
    try:
        address = ipaddress.ip_address(text.partition("%")[0])
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def client_ip(request: Request, trusted_hops: int) -> str:
    peer = request.client.host if request.client else UNKNOWN
    if trusted_hops > 0:
        # A client may send the header several times: they count as one comma-joined chain.
        chain = ",".join(request.headers.getlist("x-forwarded-for")).split(",")
        if len(chain) >= trusted_hops:
            forwarded = _parse(chain[-trusted_hops])
            if forwarded is not None:
                return forwarded
    return _parse(peer) or peer
