"""Dev only (ADR-046 item 3): invoice the shipments that Phase 4 dispatched before invoices
existed. Each is invoiced today, at today's tax rate, in number order, marked "After dispatch
(Phase 4 data)", with its ledger debit. Refuses unless DEBUG; never run by migrations."""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.billing import invoicing
from apps.orders.models import Fulfilment
from apps.orders.transitions import lock_order
from apps.platform.models import Tenant
from common.tenancy import tenant_context

SHIPPED = (Fulfilment.Status.DISPATCHED, Fulfilment.Status.DELIVERED)


def invoice_tenant(tenant_id: Any) -> int:
    """The shipments of one tenant (in a tenant context); returns how many were invoiced."""
    done = 0
    pending = (
        Fulfilment.objects.filter(status__in=SHIPPED, invoice__isnull=True)
        .order_by("dispatched_at", "created_at")
        .values_list("pk", "order_id")
    )
    for shipment_id, order_id in pending:
        with transaction.atomic():
            lock_order(order_id)  # L1, L2
            shipment = Fulfilment.objects.select_for_update().get(pk=shipment_id)
            if invoicing.issue_invoice_for_fulfilment(shipment, trigger="AFTER_DISPATCH", by=None):
                done += 1
    return done


class Command(BaseCommand):
    help = "Dev only: invoice Phase 4 shipments dispatched without an invoice (dated today)."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("invoice_phase4_shipments only runs with DEBUG=True")
        for tenant in Tenant.objects.order_by("slug"):
            with tenant_context(tenant.pk):
                count = invoice_tenant(tenant.pk)
            if count:
                self.stdout.write(f"{tenant.slug}: {count} shipments invoiced")
        self.stdout.write(self.style.SUCCESS("done"))
