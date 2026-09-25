"""Client network details behind trusted reverse proxies."""

import ipaddress

from django.conf import settings
from django.http import HttpRequest


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: HttpRequest) -> str | None:
    """The client's IP address, trusting exactly ``TRUSTED_PROXY_HOPS`` proxies.

    Each trusted proxy appends the address it received the request from to ``X-Forwarded-For``, so
    the client is the Nth entry from the right. Entries further left are client-controlled and are
    never trusted. Rate limits (ADR-030) and the audit log depend on this being right.
    """
    # TODO(verify): production proxy topology and TRUSTED_PROXY_HOPS (PROGRESS pre-production #3).
    hops: int = settings.TRUSTED_PROXY_HOPS
    remote = _valid_ip(request.META.get("REMOTE_ADDR", ""))
    if hops <= 0:
        return remote
    forwarded = [p for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
    if len(forwarded) >= hops:
        return _valid_ip(forwarded[-hops]) or remote
    return remote
