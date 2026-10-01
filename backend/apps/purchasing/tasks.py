"""Purchasing background work (thin: calls the services)."""

from typing import Any
from uuid import UUID

from celery import shared_task

from common.task_base import TenantTask


@shared_task(
    name="purchasing.render_order",
    base=TenantTask,
    bind=True,
    atomic=False,  # no DB transaction is held while the PDF is rendered and uploaded
    max_retries=5,
)
def render_order(self: Any, *, order_id: str, tenant_id: str) -> None:
    """Print a purchase order's copies; retried with backoff, then marked failed."""
    from apps.purchasing import documents

    try:
        documents.render_order(UUID(order_id))
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            documents.mark_failed(UUID(order_id))
            raise
        raise self.retry(exc=exc, countdown=min(600, 10 * 2**self.request.retries)) from exc
