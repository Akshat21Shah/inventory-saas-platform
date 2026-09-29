"""Payment background work (thin: calls the services)."""

from uuid import UUID

from celery import shared_task

from common.task_base import TenantTask


@shared_task(name="payments.verify_gateway", base=TenantTask, atomic=False)
def verify_gateway(*, tenant_id: str) -> str:
    """Sign in with the payment gateway; no transaction is held while it answers."""
    from apps.payments import gateway_config

    return gateway_config.verify(UUID(tenant_id))
