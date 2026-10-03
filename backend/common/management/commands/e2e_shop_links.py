"""Print the seeded shop's screen addresses that need an id (JSON): its newest order, a product and
category from it, and its newest bill, so the Android app's screen tour (ADR-061) can open every
screen by link in any language. Dev only: refuses unless DEBUG is on."""

import json
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.billing.models import Invoice
from apps.orders.models import Order
from apps.platform.models import Tenant
from apps.retailers.models import Retailer
from common.management.commands.e2e_pay_link import PHONE
from common.tenancy import tenant_transaction


class Command(BaseCommand):
    help = "Print the seeded shop's order, product, category and bill addresses (JSON)."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("e2e_shop_links only runs with DEBUG=True")
        tenant = Tenant.objects.get(slug="sharma")
        with tenant_transaction(tenant.pk):
            shop = Retailer.objects.get(mobile=PHONE)
            order = Order.objects.filter(retailer=shop).order_by("-created_at").first()
            line = order.lines.select_related("product").first() if order else None
            bill = (
                Invoice.objects.filter(retailer=shop, status="ISSUED")
                .order_by("-invoice_date", "-created_at")
                .first()
            )
            links = {
                "order": f"/shop/orders/{order.pk}" if order else None,
                "product": f"/shop/products/{line.product_id}" if line else None,
                "category": (
                    f"/shop/catalog/{line.product.category_id}"
                    if line and line.product.category_id
                    else None
                ),
                "bill": f"/shop/invoices/{bill.pk}" if bill else None,
            }
        self.stdout.write(json.dumps(links))
