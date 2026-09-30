"""Payment background work (thin: calls the services)."""

from uuid import UUID

from celery import shared_task

from common.task_base import TenantTask


@shared_task(name="payments.verify_gateway", base=TenantTask, atomic=False)
def verify_gateway(*, tenant_id: str) -> str:
    """Sign in with the payment gateway; no transaction is held while it answers."""
    from apps.payments import gateway_config

    return gateway_config.verify(UUID(tenant_id))


@shared_task(name="payments.reconcile_for_tenant", base=TenantTask, atomic=False)
def reconcile_for_tenant(*, tenant_id: str) -> dict[str, int]:
    from apps.payments import online

    return online.reconcile(UUID(tenant_id))


@shared_task(name="payments.reconcile")
def reconcile() -> int:
    """Every 15 minutes: each tenant with online payments on asks the gateway about checkouts
    that weren't confirmed, records missed captures and expires stale checkouts."""
    from apps.platform.models import Tenant
    from apps.platform.selectors import is_feature_enabled

    tenants = [
        pk
        for pk in Tenant.objects.exclude(status=Tenant.Status.SUSPENDED).values_list(
            "pk", flat=True
        )
        if is_feature_enabled("payments", pk)
    ]
    for pk in tenants:
        reconcile_for_tenant.apply_async(kwargs={"tenant_id": str(pk)})
    return len(tenants)
