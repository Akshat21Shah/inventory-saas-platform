"""Client network details, trusting forwarded headers only from configured proxies.

``TRUSTED_PROXIES`` lists the addresses (IPs or CIDRs) of the reverse proxies allowed to set
``X-Forwarded-*`` headers: in every environment that is the Next.js server, which discards any
client-supplied forwarded headers and sets its own. ``TrustedProxyMiddleware`` (first in the chain)
removes forwarded headers from every other peer, so nothing downstream can be fooled by them.
Per-IP rate limits (ADR-030) and audit IPs depend on this.
"""

import ipaddress
from collections.abc import Callable
from functools import lru_cache

from django.conf import settings
from django.http import HttpRequest, HttpResponse

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

_FORWARDED_META = ("HTTP_FORWARDED", "HTTP_X_REAL_IP")


def _parse_ip(value: str) -> IPAddress | None:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


@lru_cache(maxsize=8)
def _networks(entries: tuple[str, ...]) -> tuple[IPNetwork, ...]:
    return tuple(ipaddress.ip_network(e.strip(), strict=False) for e in entries if e.strip())


def is_trusted_proxy(address: str | None) -> bool:
    ip = _parse_ip(address or "")
    if ip is None:
        return False
    return any(ip in net for net in _networks(tuple(settings.TRUSTED_PROXIES)))


def client_ip(request: HttpRequest) -> str | None:
    """The client's IP: from ``X-Forwarded-For`` only when a trusted proxy sent the request (the
    rightmost address that is not itself a trusted proxy), otherwise the socket address."""
    remote = _parse_ip(request.META.get("REMOTE_ADDR", ""))
    if remote is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if not forwarded or not is_trusted_proxy(str(remote)):
        return str(remote)
    for entry in reversed(forwarded.split(",")):
        ip = _parse_ip(entry)
        if ip is not None and not is_trusted_proxy(str(ip)):
            return str(ip)
    return str(remote)


class TrustedProxyMiddleware:
    """Drop every forwarded header unless the peer is a trusted proxy. Must run first (before
    SecurityMiddleware, which reads X-Forwarded-Proto via SECURE_PROXY_SSL_HEADER)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not is_trusted_proxy(request.META.get("REMOTE_ADDR")):
            for key in [k for k in request.META if k.startswith("HTTP_X_FORWARDED_")]:
                del request.META[key]
            for key in _FORWARDED_META:
                request.META.pop(key, None)
            request.__dict__.pop("headers", None)  # drop a cached request.headers, if any
        return self.get_response(request)
