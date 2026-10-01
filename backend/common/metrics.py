"""Requests and server errors per hour (ADR-050 item 12): the super admin dashboard's error
rate. Counted in the cache for two days; Sentry keeps the details of every error. Counting must
never break a request, so cache problems are ignored."""

from datetime import datetime, timedelta

from django.core.cache import cache
from django.utils import timezone

KEEP_SECONDS = 2 * 24 * 3600
SKIPPED = ("/health",)  # load balancer and container checks would drown the real traffic


def _key(kind: str, hour: datetime) -> str:
    return f"metrics:{kind}:{hour:%Y%m%d%H}"


def record(path: str, status: int) -> None:
    if path.startswith(SKIPPED):
        return
    now = timezone.now()
    kinds = ("requests", "errors") if status >= 500 else ("requests",)
    for kind in kinds:
        key = _key(kind, now)
        try:
            cache.add(key, 0, timeout=KEEP_SECONDS)
            cache.incr(key)
        except Exception:  # noqa: S110 - metrics are best effort
            pass


def last_hours(hours: int = 24) -> dict[str, int]:
    now = timezone.now()
    keys = {
        kind: [_key(kind, now - timedelta(hours=i)) for i in range(hours)]
        for kind in ("requests", "errors")
    }
    try:
        found = cache.get_many([k for group in keys.values() for k in group])
    except Exception:
        found = {}
    return {kind: sum(int(found.get(k) or 0) for k in group) for kind, group in keys.items()}
