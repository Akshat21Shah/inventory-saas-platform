"""Shared by the e-invoice tests: a tenant with e-invoicing on, working credentials, a B2B shop in
another state (WhatsApp agreed) and a local B2C shop (the ``world`` fixture in ``conftest``)."""

import json
from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.billing.models import Invoice
from apps.billing.tests.helpers import ship_invoice
from apps.compliance import tasks
from apps.compliance.models import EInvoiceRecord, GstCredential
from apps.notifications.adapters.whatsapp import MockWhatsAppClient
from common.tenancy import tenant_context


def credentials(tenant: Any, status: str = GstCredential.Status.VERIFIED) -> None:
    with tenant_context(tenant.pk):
        GstCredential.objects.update_or_create(
            provider="mock",
            defaults={
                "gstin": tenant.gstin,
                "credentials": json.dumps({"username": "u", "password": "p"}),
                "status": status,
            },
        )


def sell(world: dict[str, Any], shop: str = "b2b", qty: str = "1") -> Invoice:
    with world["run"]():
        invoice = ship_invoice(world["t"], world[shop], world["owner"], (world["product"], qty))
    with tenant_context(world["t"].pk):
        invoice.refresh_from_db()
    return invoice


def bills_sent() -> int:
    return sum(m.message.template == "b2b_invoice_issued" for m in MockWhatsAppClient.outbox)


def record_of(world: dict[str, Any], invoice: Invoice) -> EInvoiceRecord:
    with tenant_context(world["t"].pk):
        found: EInvoiceRecord = EInvoiceRecord.objects.get(invoice=invoice)
        return found


def sweep(world: dict[str, Any], *, minutes: int = 0) -> None:
    """The every-minute job, ``minutes`` from now (retries that are due)."""
    with tenant_context(world["t"].pk):
        EInvoiceRecord.objects.filter(next_retry_at__isnull=False).update(
            next_retry_at=timezone.now() - timedelta(minutes=minutes or 1)
        )
    with world["run"]():
        tasks.retry_due_for_tenant.apply(kwargs={"tenant_id": str(world["t"].pk)})
