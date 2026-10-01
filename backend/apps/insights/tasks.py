"""Shop activity background work (thin: calls the services)."""

from celery import shared_task

from common.task_base import TenantTask


@shared_task(name="insights.refresh_for_tenant", base=TenantTask)
def refresh_for_tenant(*, tenant_id: str) -> int:
    """One distributor's shop activity. Returns how many shops."""
    from apps.insights import services

    return services.refresh_activity()


@shared_task(name="insights.refresh_all")
def refresh_all() -> int:
    """Nightly, 01:45 IST: every distributor that isn't suspended."""
    from apps.platform.models import Tenant

    tenants = list(
        Tenant.objects.exclude(status=Tenant.Status.SUSPENDED).values_list("pk", flat=True)
    )
    for tenant_id in tenants:
        refresh_for_tenant.apply_async(kwargs={"tenant_id": str(tenant_id)})
    return len(tenants)
