"""A shipment on its way to Ganesh Kirana at Sharma Distributors, for the delivery E2E (ADR-057):
an order of one unit of an in-stock product, placed, accepted, packed and dispatched through the
services. ``--with-code`` dispatches it with a delivery code (the setting is restored after).
Prints JSON: the order, the shipment and its code. Dev only: refuses unless DEBUG is on."""

import json
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.accounts.models import User
from apps.inventory.availability import ShopStockRules
from apps.inventory.models import StockLevel
from apps.orders import fulfilment, transitions
from apps.orders.cart import live_rules
from apps.orders.models import Fulfilment, Order, OrderStatus
from apps.orders.quote import build_quote
from apps.orders.services import Placement, place_order
from apps.platform.models import Tenant
from apps.platform.selectors import get_setting, invalidate_tenant_settings
from apps.platform.services import set_tenant_settings
from apps.retailers.models import Retailer
from common.tenancy import tenant_transaction

SHOP_PHONE = "+919876500001"


class Command(BaseCommand):
    help = "Dispatch a one-item order to the demo shop (for the delivery E2E)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--with-code", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("e2e_dispatch only runs with DEBUG=True")
        tenant = Tenant.objects.get(slug="sharma")
        with tenant_transaction(tenant.pk):
            shop = Retailer.objects.get(mobile=SHOP_PHONE)
            login = User.objects.get(tenant=tenant, phone=SHOP_PHONE)
            owner = User.objects.get(email="owner@sharma.example.com")
            level = (
                StockLevel.objects.filter(
                    product__is_active=True,
                    product__show_in_shop=True,
                    product__min_order_qty=1,
                    product__order_multiple=1,
                )
                .exclude(product__deleted_at__isnull=False)
                .order_by("-quantity_on_hand", "product__code")
                .select_related("product")
                .first()
            )
            if level is None or level.quantity_on_hand - level.quantity_reserved < 1:
                raise CommandError("no product in stock to send")
            items = [(level.product_id, Decimal("1"))]
            quote = build_quote(
                shop,
                items,
                rules=live_rules(tenant.pk),
                stock_rules=ShopStockRules.for_tenant(tenant.pk),
            )
            order: Order = place_order(
                Placement(
                    retailer=shop,
                    placed_by=login,
                    via=Order.PlacedVia.RETAILER_APP,
                    items=items,
                    expected_total=quote.totals.grand_total,
                )
            )
            if order.status == OrderStatus.PLACED:
                transitions.accept_order(order.pk, by=owner)
            shipment = Fulfilment.objects.filter(order=order).order_by("created_at").first()
            if shipment is None:
                raise CommandError("the order made no shipment")
            fulfilment.pack(shipment.pk, {}, by=owner)
        # The setting is read when dispatching; it is changed (and put back) in transactions of
        # its own so the settings cache follows.
        before = bool(get_setting("orders.delivery_code", tenant.pk))
        if options["with_code"] != before:
            with tenant_transaction(tenant.pk):
                set_tenant_settings({"orders.delivery_code": options["with_code"]}, user=None)
            invalidate_tenant_settings(tenant.pk)  # also when an outer transaction holds commits
        try:
            with tenant_transaction(tenant.pk):
                fulfilment.dispatch(shipment.pk, fulfilment.Transport("", "", ""), by=owner)
        finally:
            if options["with_code"] != before:
                with tenant_transaction(tenant.pk):
                    set_tenant_settings({"orders.delivery_code": before}, user=None)
                invalidate_tenant_settings(tenant.pk)
        with tenant_transaction(tenant.pk):
            shipment.refresh_from_db()
            self.stdout.write(
                json.dumps(
                    {
                        "order": str(order.pk),
                        "number": order.number,
                        "shipment": str(shipment.pk),
                        "code": shipment.delivery_code,
                    }
                )
            )
