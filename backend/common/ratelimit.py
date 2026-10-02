"""Fixed-window rate limits in the shared cache (Redis), keyed by what is being protected.

Limits come from platform settings (ADR-030): per-IP limits are generous because many Indian mobile
users share an IP (CGNAT); per-account limits (email, phone) do the real protection.
"""

import fnmatch
import hashlib
import math
import time
from collections.abc import Iterable
from typing import Any

from django.core.cache import cache, caches
from django.core.cache.backends.locmem import LocMemCache
from django.core.cache.backends.redis import RedisCache
from django.utils.translation import gettext_lazy

from common.error_codes import ErrorCode
from common.errors import DomainError


class RateLimited(DomainError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED
    default_message = gettext_lazy("Too many attempts. Please wait a moment and try again.")

    def __init__(self, retry_after: int) -> None:
        super().__init__(details={"retry_after": retry_after})
        self.headers = {"Retry-After": str(retry_after)}


def _digest(identifier: str) -> str:
    return hashlib.sha256(identifier.lower().encode()).hexdigest()[:32]


def _key(bucket: str, identifier: str, window: int, now: float) -> str:
    return f"rl:{bucket}:{_digest(identifier)}:{int(now // window)}"


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


def clear(identifiers: Iterable[str] = (), *, ip_buckets: bool = False) -> int:
    """Delete every counter for these identifiers (emails, phones, user ids) in any bucket, and
    optionally every per-IP counter. For support tooling and E2E set-up only: it scans keys, so it
    must never run on a request path. Returns the number of counters removed."""
    patterns = [f"rl:*:{_digest(identifier)}:*" for identifier in identifiers]
    if ip_buckets:
        patterns.append("rl:*:ip:*")
    if not patterns:
        return 0
    backend = caches["default"]
    full = [backend.make_key(pattern) for pattern in patterns]
    # Private backend APIs are used on purpose: this is tooling, not a request path.
    if isinstance(backend, RedisCache):
        client: Any = backend._cache.get_client(None, write=True)
        keys = {key for pattern in full for key in client.scan_iter(match=pattern)}
        return int(client.delete(*keys)) if keys else 0
    if isinstance(backend, LocMemCache):
        local: Any = backend
        with local._lock:
            keys = {k for k in list(local._cache) if any(fnmatch.fnmatch(k, p) for p in full)}
            for key in keys:
                local._delete(key)
        return len(keys)
    raise NotImplementedError(f"clearing rate limits is not supported for {type(backend)}")
