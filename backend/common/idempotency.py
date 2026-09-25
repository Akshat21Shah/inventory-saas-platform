"""Idempotency-Key support for DRF views (ADR-005).

The record is inserted inside the request transaction with ``ON CONFLICT DO NOTHING``. A concurrent
duplicate blocks on the unique index until the first request commits, then replays the stored
response; if the first request rolled back, the duplicate simply executes. Failed requests (4xx
DomainErrors / 5xx) roll back and store nothing, so the client may retry with the same key.
"""

import hashlib
import json
import re
from collections.abc import Callable
from datetime import timedelta
from functools import wraps
from typing import Any

from celery import shared_task
from django.conf import settings
from django.db import connection
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from common.error_codes import ErrorCode
from common.errors import DomainError
from common.ids import uuid7
from common.models import IdempotencyRecord
from common.tenancy import get_current_tenant_id

HEADER = "Idempotency-Key"
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
REPLAY_HEADER = "Idempotent-Replayed"


def _request_hash(request: Request, view_kwargs: dict[str, Any]) -> str:
    body = json.dumps({"path": view_kwargs, "data": request.data}, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def idempotent(scope: str) -> Callable[[Callable[..., Response]], Callable[..., Response]]:
    """Decorate a DRF view method: ``@idempotent("orders.place")``."""

    def decorator(func: Callable[..., Response]) -> Callable[..., Response]:
        @wraps(func)
        def wrapper(view: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
            user_id = request.user.pk
            if user_id is None:
                raise NotAuthenticated()
            key = request.headers.get(HEADER, "")
            if not key:
                raise DomainError(
                    "An Idempotency-Key header is required.",
                    code=ErrorCode.IDEMPOTENCY_KEY_REQUIRED,
                )
            if not _KEY_RE.match(key):
                raise DomainError(
                    "Invalid Idempotency-Key.", code=ErrorCode.IDEMPOTENCY_KEY_INVALID
                )
            if not connection.in_atomic_block:
                raise RuntimeError("@idempotent views must run inside ATOMIC_REQUESTS")

            req_hash = _request_hash(request, kwargs)
            record_id = uuid7()
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {IdempotencyRecord._meta.db_table} "  # noqa: S608
                    "(id, tenant_id, user_id, scope, key, request_hash, expires_at, "
                    "created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, now(), now()) "
                    "ON CONFLICT (user_id, scope, key) DO NOTHING RETURNING id",
                    [
                        record_id,
                        get_current_tenant_id(),
                        user_id,
                        scope,
                        key,
                        req_hash,
                        timezone.now() + timedelta(seconds=settings.IDEMPOTENCY_TTL_SECONDS),
                    ],
                )
                inserted = cursor.fetchone() is not None

            if not inserted:
                existing = IdempotencyRecord.objects.get(user_id=user_id, scope=scope, key=key)
                if existing.request_hash != req_hash:
                    raise DomainError(
                        "This Idempotency-Key was already used for a different request.",
                        code=ErrorCode.IDEMPOTENCY_KEY_REUSED,
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    )
                replay = Response(existing.response_body, status=existing.response_status or 200)
                replay[REPLAY_HEADER] = "true"
                return replay

            response = func(view, request, *args, **kwargs)
            IdempotencyRecord.objects.filter(pk=record_id).update(
                response_status=response.status_code, response_body=response.data
            )
            return response

        return wrapper

    return decorator


@shared_task(name="common.idempotency.purge_expired")
def purge_expired() -> int:
    deleted, _ = IdempotencyRecord.objects.filter(expires_at__lt=timezone.now()).delete()
    return deleted
