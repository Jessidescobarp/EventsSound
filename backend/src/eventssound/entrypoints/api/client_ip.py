"""Safe client address for rate limiting (D32).

`X-Forwarded-For` is `client, proxy1, proxy2, ...`: every proxy appends the address it saw on
the right, while the client controls everything on the left. With `hops` trusted proxies, the
client is the entry `hops` places from the right. By default (0) the header is ignored.
"""

import ipaddress

from fastapi import Request

UNKNOWN = "unknown"


def _normalize(value: str) -> str | None:
    """Canonical text of an IP address; IPv6 collapses to its /64 (one subscriber owns it all)."""
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address):
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def client_ip(request: Request, trusted_hops: int) -> str:
    peer = request.client.host if request.client else UNKNOWN
    if trusted_hops > 0:
        parts = request.headers.get("x-forwarded-for", "").split(",")
        if len(parts) >= trusted_hops:
            forwarded = _normalize(parts[-trusted_hops])
            if forwarded is not None:
                return forwarded
    return _normalize(peer) or peer
