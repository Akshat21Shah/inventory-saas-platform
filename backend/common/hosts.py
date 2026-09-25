"""Host classification (ADR-019/020): admin.<domain> | {slug}.<domain> | <domain>."""

import re
from dataclasses import dataclass
from enum import StrEnum

from django.conf import settings

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])$")
RESERVED_SUBDOMAINS = frozenset({"admin", "www", "api", "app", "static", "media", "mail"})


class HostKind(StrEnum):
    ADMIN = "ADMIN"
    TENANT = "TENANT"
    GENERIC = "GENERIC"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class HostContext:
    kind: HostKind
    tenant_slug: str | None = None


def classify_host(host: str, platform_domain: str | None = None) -> HostContext:
    domain = (platform_domain or settings.PLATFORM_DOMAIN).lower()
    hostname = host.split(":", 1)[0].lower().rstrip(".")
    if hostname in (domain, f"www.{domain}"):
        return HostContext(HostKind.GENERIC)
    if hostname == f"admin.{domain}":
        return HostContext(HostKind.ADMIN)
    suffix = f".{domain}"
    if hostname.endswith(suffix):
        label = hostname[: -len(suffix)]
        if "." not in label and label not in RESERVED_SUBDOMAINS and SLUG_RE.match(label):
            return HostContext(HostKind.TENANT, label)
    return HostContext(HostKind.UNKNOWN)
