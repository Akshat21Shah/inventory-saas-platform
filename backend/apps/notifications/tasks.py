"""Notification background work (thin: calls the consumer and delivery services)."""

from uuid import UUID

from celery import shared_task

from common.task_base import TenantTask


@shared_task(name="notifications.dispatch_event", base=TenantTask)
def dispatch_event(*, event_id: str, tenant_id: str) -> int:
    """Outbox handler: the event's notification rows (idempotent on the event id)."""
    from apps.notifications import consumer

    return consumer.handle(UUID(event_id))
