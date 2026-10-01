"""Liveness and readiness endpoints (no auth, no tenant), answered by ``HealthCheckMiddleware``
before anything else so any probe gets them: load balancers and orchestrators call a container
by its address over plain HTTP, which host validation (``ALLOWED_HOSTS``) would refuse with 400
and the production HTTPS redirect answer with 301, and Docker's own check calls ``localhost``,
which LAN mode in development doesn't allow."""

import logging
from collections.abc import Callable

from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def live(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@require_GET
def ready(request: HttpRequest) -> JsonResponse:
    checks: dict[str, str] = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        logger.exception("readiness: database check failed")
        checks["database"] = "error"
    try:
        cache.set("health:ping", "1", timeout=5)
        checks["cache"] = "ok" if cache.get("health:ping") == "1" else "error"
    except Exception:
        logger.exception("readiness: cache check failed")
        checks["cache"] = "error"
    healthy = all(value == "ok" for value in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "error", "checks": checks}, status=200 if healthy else 503
    )


PATHS: dict[str, Callable[[HttpRequest], JsonResponse]] = {
    "/health/live": live,
    "/health/ready": ready,
}


class HealthCheckMiddleware:
    """First in ``MIDDLEWARE``: GET ``/health/live`` and ``/health/ready`` are answered here, for
    any host and over plain HTTP. They only say whether the app is up; every other request goes
    through host validation and the HTTPS redirect as usual."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        view = PATHS.get(request.path_info)
        if view is not None and request.method == "GET":
            return view(request)
        return self.get_response(request)
