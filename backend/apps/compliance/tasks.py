"""E-invoicing background work (thin: calls the services)."""

from uuid import UUID

from celery import shared_task

from common.task_base import TenantTask


@shared_task(name="compliance.verify_credentials", base=TenantTask, atomic=False)
def verify_credentials(*, tenant_id: str) -> str:
    """Sign in with the GST provider; no transaction is held while it answers."""
    from apps.compliance import credentials

    return credentials.verify(UUID(tenant_id))
