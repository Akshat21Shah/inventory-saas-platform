"""Tenant-isolation coverage harness (CLAUDE.md §4: every API endpoint has an isolation test).

Endpoint tests register the route names they cover with ``@covers("route-name", ...)``. A single
test (``test_every_api_endpoint_has_isolation_coverage``) walks the URL conf and fails if any
``/api/v1/`` route is neither covered nor explicitly exempted (public, tenant-less endpoints).
"""

from collections.abc import Callable, Iterable
from typing import Any, TypeVar

from django.urls import URLPattern, URLResolver, get_resolver

F = TypeVar("F", bound=Callable[..., Any])

COVERED: set[str] = set()
EXEMPT: dict[str, str] = {
    "schema": "OpenAPI schema document; contains no tenant data",
    "docs": "Swagger UI shell; contains no tenant data",
    "meta": "public platform metadata (version, domain); contains no tenant data",
}


def covers(*route_names: str) -> Callable[[F], F]:
    COVERED.update(route_names)

    def decorator(func: F) -> F:
        return func

    return decorator


def _walk(
    patterns: Iterable[Any], prefix: str = "", namespace: str = ""
) -> Iterable[tuple[str, str | None]]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            ns = f"{namespace}{pattern.namespace}:" if pattern.namespace else namespace
            yield from _walk(pattern.url_patterns, prefix + str(pattern.pattern), ns)
        elif isinstance(pattern, URLPattern):
            name = f"{namespace}{pattern.name}" if pattern.name else None
            yield prefix + str(pattern.pattern), name


def api_routes() -> list[tuple[str, str | None]]:
    return [
        (route, name)
        for route, name in _walk(get_resolver().url_patterns)
        if route.startswith("api/v1/")
    ]
