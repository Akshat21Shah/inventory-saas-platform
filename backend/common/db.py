"""Database helpers: deadlock/serialization retry for top-level services (ADR-004)."""

import logging
import random
import time
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from django.db import OperationalError, transaction
from psycopg import errors as pg_errors

logger = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R")

RETRYABLE = (pg_errors.DeadlockDetected, pg_errors.SerializationFailure)


def is_retryable(exc: BaseException) -> bool:
    cause = exc.__cause__ or exc.__context__
    return isinstance(exc, RETRYABLE) or isinstance(cause, RETRYABLE)


def retry_on_deadlock(
    attempts: int = 3, base_delay: float = 0.05
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry the whole transactional unit on deadlock. Only valid at the outermost transaction."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if transaction.get_connection().in_atomic_block:
                # Inside an outer transaction a retry cannot re-run the unit; let it propagate.
                return func(*args, **kwargs)
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except OperationalError as exc:
                    if attempt == attempts or not is_retryable(exc):
                        raise
                    delay = base_delay * (2 ** (attempt - 1)) * (1 + random.random())  # noqa: S311
                    logger.warning(
                        "deadlock in %s; retry %s/%s in %.3fs",
                        func.__qualname__,
                        attempt,
                        attempts,
                        delay,
                    )
                    time.sleep(delay)
            raise AssertionError("unreachable")

        return wrapper

    return decorator
