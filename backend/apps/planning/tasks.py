"""Stock planning background work (thin: calls the services)."""

from celery import shared_task

from common.task_base import TenantTask


@shared_task(name="planning.refresh_for_tenant", base=TenantTask)
def refresh_for_tenant(*, tenant_id: str) -> int:
    """One distributor's product stats, when stock planning is on for it."""
    from apps.planning import services
    from apps.platform.selectors import is_feature_enabled

    if not is_feature_enabled("stock_planning"):
        return 0
    return services.refresh_stats()


@shared_task(name="planning.refresh_all")
def refresh_all() -> int:
    """Nightly, 01:30 IST: every distributor that isn't suspended."""
    from apps.platform.models import Tenant

    tenants = list(
        Tenant.objects.exclude(status=Tenant.Status.SUSPENDED).values_list("pk", flat=True)
    )
    for tenant_id in tenants:
        refresh_for_tenant.apply_async(kwargs={"tenant_id": str(tenant_id)})
    return len(tenants)
