"""Fixed-window rate limits in the shared cache (Redis), keyed by what is being protected.

Limits come from platform settings (ADR-030): per-IP limits are generous because many Indian mobile
users share an IP (CGNAT); per-account limits (email, phone) do the real protection.
"""

import hashlib
import math
import time

from django.core.cache import cache

from common.error_codes import ErrorCode
from common.errors import DomainError


class RateLimited(DomainError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED
    default_message = "Too many attempts. Please wait a moment and try again."

    def __init__(self, retry_after: int) -> None:
        super().__init__(details={"retry_after": retry_after})
        self.headers = {"Retry-After": str(retry_after)}


def _key(bucket: str, identifier: str, window: int, now: float) -> str:
    digest = hashlib.sha256(identifier.lower().encode()).hexdigest()[:32]
    return f"rl:{bucket}:{digest}:{int(now // window)}"


def hit(bucket: str, identifier: str | None, limit: int, window_seconds: int) -> None:
    """Count one attempt; raise ``RateLimited`` once ``limit`` attempts are exceeded in the window.

    A missing identifier (e.g. no client IP) is not limited by this bucket.
    """
    if not identifier:
        return
    now = time.time()
    key = _key(bucket, identifier, window_seconds, now)
    if cache.add(key, 1, timeout=window_seconds + 1):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:  # expired between add() and incr()
            cache.set(key, 1, timeout=window_seconds + 1)
            count = 1
    if count > limit:
        retry_after = max(1, math.ceil(window_seconds - (now % window_seconds)))
        raise RateLimited(retry_after)


def reset(bucket: str, identifier: str, window_seconds: int) -> None:
    """Clear the current window (tests and support tooling)."""
    cache.delete(_key(bucket, identifier, window_seconds, time.time()))
