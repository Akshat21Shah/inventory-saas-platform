"""Notification background work (thin: calls the consumer and delivery services)."""

from uuid import UUID

from celery import shared_task

from common.task_base import TenantTask


@shared_task(name="notifications.dispatch_event", base=TenantTask)
def dispatch_event(*, event_id: str, tenant_id: str) -> int:
    """Outbox handler: the event's notification rows (idempotent on the event id), then their
    delivery once this transaction commits."""
    from apps.notifications import consumer, delivery

    created = consumer.handle(UUID(event_id))
    delivery.after_fan_out(UUID(event_id))
    return created


@shared_task(name="notifications.deliver", base=TenantTask, atomic=False)
def deliver(*, notification_id: str, tenant_id: str) -> str:
    """One try; the next one (if any) is scheduled on the row and sent by ``send_due``."""
    from apps.notifications import delivery

    return delivery.deliver(UUID(notification_id))


@shared_task(name="notifications.send_due_for_tenant", base=TenantTask)
def send_due_for_tenant(*, tenant_id: str) -> int:
    from apps.notifications import delivery

    ids = delivery.due()
    delivery.enqueue(ids)
    return len(ids)


@shared_task(name="notifications.send_due")
def send_due() -> int:
    """Every minute: each active tenant sends its retries, held and lost messages."""
    from apps.platform.models import Tenant

    tenants = Tenant.objects.exclude(status=Tenant.Status.SUSPENDED).values_list("pk", flat=True)
    for tenant_id in tenants:
        send_due_for_tenant.apply_async(kwargs={"tenant_id": str(tenant_id)})
    return len(tenants)
