"""Liveness and readiness endpoints (no auth, no tenant)."""

import logging

from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, JsonResponse
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
