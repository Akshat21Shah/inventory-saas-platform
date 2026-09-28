"""Billing background work (thin: calls services): printing documents after they are saved."""

from typing import Any
from uuid import UUID

from celery import shared_task

from common.models import OutboxEvent
from common.task_base import TenantTask
from common.tenancy import tenant_transaction

# event type -> (document kind, payload field with its id)
PDF_EVENTS: dict[str, tuple[str, str]] = {
    "invoice.issued": ("invoice", "invoice_id"),
    "credit_note.issued": ("credit_note", "credit_note_id"),
    "payment.received": ("receipt", "payment_id"),
    "order_confirmation.created": ("order_confirmation", "confirmation_id"),
}


@shared_task(
    name="billing.render_document",
    base=TenantTask,
    bind=True,
    atomic=False,  # no DB transaction is held while the PDF is rendered and uploaded
    max_retries=5,
)
def render_document(self: Any, *, kind: str, object_id: str, tenant_id: str) -> None:
    """Storage or renderer hiccups are retried with backoff; after the last try the document shows
    "PDF failed" and staff can regenerate it."""
    from apps.billing import documents

    try:
        documents.RENDERERS[kind](UUID(object_id))
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            documents.mark_failed(kind, UUID(object_id))
            raise
        raise self.retry(exc=exc, countdown=min(600, 10 * 2**self.request.retries)) from exc


@shared_task(name="billing.render_for_event", base=TenantTask, atomic=False)
def render_for_event(*, event_id: str, tenant_id: str) -> None:
    """Outbox handler: queue the document's rendering (idempotent: rendering again rewrites the
    same file)."""
    with tenant_transaction(UUID(tenant_id)):
        event = OutboxEvent.objects.get(pk=event_id)
    kind, field = PDF_EVENTS[event.event_type]
    render_document.apply_async(
        kwargs={"kind": kind, "object_id": event.payload[field], "tenant_id": tenant_id}
    )


def regenerate(kind: str, object_id: UUID, tenant_id: UUID) -> None:
    """Staff asked for a document to be printed again (``invoices.manage``)."""
    render_document.apply_async(
        kwargs={"kind": kind, "object_id": str(object_id), "tenant_id": str(tenant_id)}
    )
