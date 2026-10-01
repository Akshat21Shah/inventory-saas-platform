"""Notification background work (thin: calls the consumer and delivery services)."""

from typing import Any
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
    from apps.notifications import announcements, delivery

    announcements.publish_due()
    ids = delivery.due()
    delivery.enqueue(ids)
    return len(ids)


@shared_task(name="notifications.send_due")
def send_due() -> int:
    """Every minute: each active tenant sends its retries, held and lost messages."""
    return _each_tenant(send_due_for_tenant)


# --- Daily jobs (the beat runs them in UTC; the times are IST) -----------------------------------


def _each_tenant(task: Any) -> int:
    from apps.platform.models import Tenant

    tenants = list(
        Tenant.objects.exclude(status=Tenant.Status.SUSPENDED).values_list("pk", flat=True)
    )
    for tenant_id in tenants:
        task.apply_async(kwargs={"tenant_id": str(tenant_id)})
    return len(tenants)


@shared_task(name="notifications.payment_reminders_for_tenant", base=TenantTask)
def payment_reminders_for_tenant(*, tenant_id: str) -> int:
    from apps.notifications import jobs
    from common.dates import today_ist

    return jobs.payment_reminders(today_ist())


@shared_task(name="notifications.handover_reminders_for_tenant", base=TenantTask)
def handover_reminders_for_tenant(*, tenant_id: str) -> int:
    from apps.notifications import jobs
    from common.dates import today_ist

    return jobs.handover_reminders(today_ist())


@shared_task(name="notifications.rate_change_warnings_for_tenant", base=TenantTask)
def rate_change_warnings_for_tenant(*, tenant_id: str) -> int:
    from apps.notifications import jobs
    from common.dates import today_ist

    return jobs.rate_change_warnings(today_ist())


@shared_task(name="notifications.payment_reminders")
def payment_reminders() -> int:
    """Daily 10:00 IST."""
    return _each_tenant(payment_reminders_for_tenant)


@shared_task(name="notifications.handover_reminders")
def handover_reminders() -> int:
    """Daily 09:00 IST."""
    return _each_tenant(handover_reminders_for_tenant)


@shared_task(name="notifications.rate_change_warnings")
def rate_change_warnings() -> int:
    """Daily 08:30 IST."""
    return _each_tenant(rate_change_warnings_for_tenant)


@shared_task(name="notifications.daily_summaries_for_tenant", base=TenantTask)
def daily_summaries_for_tenant(*, tenant_id: str) -> int:
    from django.utils import timezone

    from apps.notifications import jobs

    return jobs.daily_summaries(timezone.now())


@shared_task(name="notifications.daily_summaries")
def daily_summaries() -> int:
    """Every 15 minutes: each distributor whose summary time has passed sends it, once a day."""
    return _each_tenant(daily_summaries_for_tenant)
