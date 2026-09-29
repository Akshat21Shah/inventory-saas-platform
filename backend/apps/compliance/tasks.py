"""E-invoicing background work (thin: calls the services)."""

from uuid import UUID

from celery import shared_task

from common.task_base import TenantTask


@shared_task(name="compliance.verify_credentials", base=TenantTask, atomic=False)
def verify_credentials(*, tenant_id: str) -> str:
    """Sign in with the GST provider; no transaction is held while it answers."""
    from apps.compliance import credentials

    return credentials.verify(UUID(tenant_id))


@shared_task(name="compliance.generate_irn", base=TenantTask, atomic=False)
def generate_irn(*, record_id: str, tenant_id: str) -> str:
    """One try at the IRN; the next (if any) is scheduled on the record and sent by
    ``retry_due``."""
    from apps.compliance import einvoice

    return einvoice.generate(UUID(record_id), UUID(tenant_id))


@shared_task(name="compliance.retry_due_for_tenant", base=TenantTask)
def retry_due_for_tenant(*, tenant_id: str) -> int:
    from apps.compliance import cancellation, einvoice

    ids, cancels = einvoice.due(), cancellation.due()
    for pk in ids:
        generate_irn.apply_async(kwargs={"record_id": str(pk), "tenant_id": tenant_id})
    for pk in cancels:
        cancel_irn.apply_async(kwargs={"record_id": str(pk), "tenant_id": tenant_id})
    return len(ids) + len(cancels)


@shared_task(name="compliance.retry_due")
def retry_due() -> int:
    """Every minute: each tenant with e-invoicing on sends its retries and lost sends."""
    from apps.platform.models import Tenant
    from apps.platform.selectors import is_feature_enabled

    tenants = [
        pk
        for pk in Tenant.objects.exclude(status=Tenant.Status.SUSPENDED).values_list(
            "pk", flat=True
        )
        if is_feature_enabled("einvoice", pk)
    ]
    for pk in tenants:
        retry_due_for_tenant.apply_async(kwargs={"tenant_id": str(pk)})
    return len(tenants)


@shared_task(name="compliance.cancel_irn", base=TenantTask, atomic=False)
def cancel_irn(*, record_id: str, tenant_id: str) -> str:
    """Ask the portal to cancel an IRN, then apply it (a retry is queued with a delay)."""
    from apps.compliance import cancellation

    return cancellation.cancel(UUID(record_id), UUID(tenant_id))
