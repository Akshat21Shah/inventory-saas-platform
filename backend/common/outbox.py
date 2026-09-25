"""Transactional outbox (ADR-003).

Services call ``emit()`` inside their transaction. After commit the event is dispatched to its
registered handler tasks; a periodic sweeper re-dispatches anything left behind (e.g. broker down).
Delivery is at-least-once: handlers must be idempotent on ``event_id``.
"""

import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any
from uuid import UUID

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.models import OutboxEvent
from common.tenancy import get_current_tenant_id

logger = logging.getLogger(__name__)

# event_type -> Celery task names. Handler tasks receive (event_id=..., tenant_id=...).
_HANDLERS: dict[str, list[str]] = defaultdict(list)


def register_handler(event_type: str, task_name: str) -> None:
    if task_name not in _HANDLERS[event_type]:
        _HANDLERS[event_type].append(task_name)


def handlers_for(event_type: str) -> list[str]:
    return list(_HANDLERS.get(event_type, []))


def emit(
    event_type: str,
    *,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any] | None = None,
    tenant_id: UUID | None = None,
) -> OutboxEvent:
    """Record a domain event in the caller's transaction and dispatch it after commit."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("emit() must be called inside the business transaction")
    event = OutboxEvent.objects.create(
        tenant_id=tenant_id or get_current_tenant_id(),
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload or {},
    )
    event_id = str(event.id)
    transaction.on_commit(lambda: _safe_enqueue(event_id))
    return event


def _safe_enqueue(event_id: str) -> None:
    try:
        dispatch_event.delay(event_id)
    except Exception:  # broker unavailable: the sweeper will pick it up
        logger.warning(
            "outbox: could not enqueue event %s; sweeper will retry", event_id, exc_info=True
        )


@shared_task(name="common.outbox.dispatch_event")
def dispatch_event(event_id: str) -> bool:
    """Fan the event out to its handler tasks exactly once per successful dispatch."""
    from celery import current_app

    with transaction.atomic():
        event = (
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(pk=event_id, dispatched_at__isnull=True)
            .first()
        )
        if event is None:
            return False  # already dispatched or being dispatched by another worker
        event.attempts += 1
        try:
            for task_name in handlers_for(event.event_type):
                current_app.send_task(
                    task_name,
                    kwargs={
                        "event_id": str(event.id),
                        "tenant_id": str(event.tenant_id) if event.tenant_id else None,
                    },
                )
        except Exception as exc:
            event.last_error = repr(exc)[:2000]
            event.save(update_fields=["attempts", "last_error", "updated_at"])
            logger.warning("outbox: dispatch failed for %s", event_id, exc_info=True)
            return False
        event.dispatched_at = timezone.now()
        event.save(update_fields=["attempts", "dispatched_at", "updated_at"])
        return True


@shared_task(name="common.outbox.sweep_outbox")
def sweep_outbox(batch_size: int = 500) -> int:
    """Re-dispatch events still pending after OUTBOX_SWEEP_AFTER_SECONDS."""
    cutoff = timezone.now() - timedelta(seconds=settings.OUTBOX_SWEEP_AFTER_SECONDS)
    pending = list(
        OutboxEvent.objects.filter(dispatched_at__isnull=True, created_at__lt=cutoff)
        .order_by("created_at")
        .values_list("id", flat=True)[:batch_size]
    )
    return sum(1 for event_id in pending if dispatch_event(str(event_id)))
