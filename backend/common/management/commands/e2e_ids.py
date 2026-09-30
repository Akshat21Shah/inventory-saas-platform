"""Print the ids of seeded Sharma records as JSON, so the responsive E2E check can open detail
pages (a product, a shop, a price list, a discount rule, goods receipts, an adjustment, orders,
a shipment, a product on backorder, billing records, an invoice with an e-way bill). Dev only:
refuses unless DEBUG is on."""

import json
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.billing.models import CreditNote, Invoice
from apps.catalog.models import Product
from apps.compliance.models import EWayBill
from apps.dataio.models import ImportJob
from apps.inventory.models import StockAdjustment, StockInward
from apps.orders.models import Fulfilment, Order, OrderLine
from apps.payments.models import Payment, PaymentIntent, Refund
from apps.platform.models import Tenant
from apps.pricing.models import DiscountRule, PriceList
from apps.retailers.models import Retailer
from common.tenancy import tenant_transaction


def _first(qs: Any) -> str | None:
    pk = qs.order_by("created_at").values_list("pk", flat=True).first()
    return str(pk) if pk else None


class Command(BaseCommand):
    help = "Print seeded record ids (JSON) for the responsive E2E check."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("e2e_ids only runs with DEBUG=True")
        tenant = Tenant.objects.get(slug="sharma")
        with tenant_transaction(tenant.pk):
            job = ImportJob.objects.order_by("-created_at").first()
            ids = {
                "tenant": str(tenant.pk),
                "retailer": str(Retailer.objects.order_by("code").values_list("pk", flat=True)[0]),
                "product": str(
                    Product.objects.filter(deleted_at__isnull=True)
                    .order_by("code")
                    .values_list("pk", flat=True)[0]
                ),
                "price_list": str(
                    PriceList.objects.order_by("name").values_list("pk", flat=True)[0]
                ),
                "rule": str(DiscountRule.objects.order_by("name").values_list("pk", flat=True)[0]),
                "import_job": str(job.pk) if job else None,
                "receipt": _first(StockInward.objects.filter(status="POSTED")),
                "draft_receipt": _first(StockInward.objects.filter(status="DRAFT")),
                "adjustment": _first(StockAdjustment.objects.all()),
                # Orders (Phase 4): the E2E shop's own order, and staff detail pages.
                "shop_order": _first(Order.objects.filter(retailer__mobile="+919876500001")),
                "order": _first(Order.objects.filter(backorder_state="OPEN")),
                "fulfilment": _first(Fulfilment.objects.all()),
                "backorder_product": (
                    str(product_id)
                    if (
                        product_id := OrderLine.objects.filter(qty_backordered__gt=0)
                        .order_by("created_at")
                        .values_list("product_id", flat=True)
                        .first()
                    )
                    else None
                ),
                # Billing (Phase 5): an invoice with a credit note, and that credit note.
                "invoice": _first(Invoice.objects.filter(credit_notes__isnull=False)),
                "credit_note": _first(CreditNote.objects.all()),
                "payment": _first(Payment.objects.filter(handover_status="WITH_SALESMAN")),
                "refund": _first(Refund.objects.all()),
                "shop_invoice": _first(Invoice.objects.filter(retailer__mobile="+919876500001")),
                # Phase 7: an invoice with an e-way bill (Sharma has the modules on).
                "ewaybill_invoice": _first(
                    Invoice.objects.filter(pk__in=EWayBill.objects.values("invoice_id"))
                ),
                "shop_checkout": _first(
                    PaymentIntent.objects.filter(retailer__mobile="+919876500001")
                ),
            }
        self.stdout.write(json.dumps(ids))
