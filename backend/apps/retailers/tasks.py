"""Retailer background work (thin: calls services)."""

from celery import shared_task

from common.task_base import TenantTask


@shared_task(
    name="retailers.send_welcome",
    base=TenantTask,
    atomic=False,  # no transaction held while the message goes out
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=1800,
    retry_jitter=True,
    max_retries=8,
)
def send_retailer_welcome(*, retailer_id: str, tenant_id: str) -> None:
    from apps.retailers import services

    services.send_welcome(retailer_id)
