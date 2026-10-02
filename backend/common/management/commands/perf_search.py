"""The Phase 9a speed check (ADR-053, 9a.8): global search (p95 < 200 ms at 40,000 orders) for an
owner and for a salesperson limited to their own shops, the super admin's search, and the new
purchasing and stock planning pages (p95 < 300 ms), timed through the whole API in-process as in
``perf_reports``. ``make perf``, after ``make seed-volume``. Phase 9b (ADR-056, 9b.6) adds the shop
activity pages, the free-goods schemes and a 40-line cart with schemes (made for the run and
removed after).

The searches use the distributor's own records (a product, a shop and its mobile and GSTIN, an
order, an invoice, a receipt, a goods receipt and a purchase order, with and without their
padding) and the worst cases: two letters, a two-digit number, and a common word.
"""

import statistics
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.tokens import issue_tokens
from apps.billing.models import Invoice
from apps.catalog.models import Product
from apps.inventory.models import StockInward
from apps.orders.models import Cart, CartLine, Order
from apps.payments.models import Payment
from apps.platform.models import Tenant
from apps.platform.selectors import is_feature_enabled
from apps.pricing.models import FreeGoodsScheme
from apps.purchasing.models import PurchaseOrder, Supplier
from apps.retailers.models import Retailer
from common.tenancy import tenant_transaction

API = "/api/v1"


def unpadded(number: str) -> str:
    head, _, tail = number.rpartition("/" if "/" in number else "-")
    return f"{head}{'/' if '/' in number else '-'}{int(tail)}"


class Command(BaseCommand):
    help = "Time global search and the purchasing and planning pages against their p95 targets."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", default="vol-a")
        parser.add_argument("--runs", type=int, default=20)
        parser.add_argument("--search-target-ms", type=float, default=200.0)
        parser.add_argument("--target-ms", type=float, default=300.0)

    def _client(self, user: User, tenant: Tenant | None) -> APIClient:
        host = f"{tenant.slug if tenant else 'admin'}.{settings.PLATFORM_DOMAIN}"
        client = APIClient(HTTP_HOST=host, HTTP_X_FORWARDED_HOST=host)
        token = issue_tokens(user, tenant.pk if tenant else None).access
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def _time(self, client: APIClient, url: str, runs: int) -> tuple[float, float, float, Any]:
        first = client.get(url)  # warms caches, as a second visit would
        if first.status_code != 200:
            raise CommandError(f"{url} answered {first.status_code}: {first.content[:300]!r}")
        timings = []
        for _ in range(runs):
            started = time.perf_counter()
            client.get(url)
            timings.append((time.perf_counter() - started) * 1000)
        p95 = statistics.quantiles(timings, n=20, method="inclusive")[-1]
        return statistics.median(timings), p95, max(timings), first.json()

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = Tenant.objects.filter(slug=options["tenant"]).first()
        if tenant is None:
            raise CommandError(f"no distributor {options['tenant']}: run make seed-volume first")
        owner = User.objects.filter(email=f"owner@{tenant.slug}.example.com").first()
        sales = User.objects.filter(email=f"sales1@{tenant.slug}.example.com").first()
        if owner is None or sales is None:
            raise CommandError("the volume distributor's staff are missing")
        with tenant_transaction(tenant.pk):  # RLS: the runtime role sees the tenant's rows
            product = Product.objects.order_by("code").first()
            shop = Retailer.objects.exclude(gstin__isnull=True).order_by("code").first()
            shop = shop or Retailer.objects.order_by("code").first()
            order = Order.objects.order_by("-placed_at").first()
            invoice = Invoice.objects.order_by("-invoice_date", "-number").first()
            payment = Payment.objects.order_by("-payment_date").first()
            receipt = StockInward.objects.exclude(number=None).order_by("-posted_at").first()
            po = PurchaseOrder.objects.order_by("-created_at").first()
            supplier = Supplier.objects.order_by("code").first()
            orders = Order.objects.count()
        if not all((product, shop, order, invoice, payment, receipt, po, supplier)):
            raise CommandError("the volume distributor has no purchasing data: make seed-volume")
        assert product and shop and order and invoice and payment and receipt and po and supplier
        word = product.name.split()[0]
        searches = [
            ("product name", word),
            ("product code", product.code),
            ("shop name", shop.shop_name.split()[0]),
            ("shop mobile", shop.mobile.removeprefix("+91")),
            ("shop GSTIN", shop.gstin or shop.code),
            ("order number", order.number),
            ("order unpadded", unpadded(order.number)),
            ("invoice unpadded", unpadded(invoice.number).lower()),
            ("receipt number", payment.number),
            ("GRN number", receipt.number or ""),
            ("PO unpadded", unpadded(po.number)),
            ("supplier name", supplier.name.split()[0]),
            ("two letters", "sa"),
            ("two digits", "12"),
        ]
        runs = options["runs"]
        search_target, target = options["search_target_ms"], options["target_ms"]
        self.stdout.write(
            f"{tenant.slug} ({orders:,} orders), {runs} runs each; "
            f"search p95 < {search_target:.0f} ms, pages p95 < {target:.0f} ms"
        )
        self.stdout.write(f"{'request':<34}{'p50':>8}{'p95':>8}{'max':>8}  found")
        slow: list[str] = []

        def measure(
            name: str, client: APIClient, url: str, limit: float, found: Callable[[Any], str]
        ) -> None:
            p50, p95, worst, body = self._time(client, url, runs)
            flag = "  SLOW" if p95 > limit else ""
            self.stdout.write(f"{name:<34}{p50:>8.0f}{p95:>8.0f}{worst:>8.0f}  {found(body)}{flag}")
            if p95 > limit:
                slow.append(f"{name} ({p95:.0f} ms)")

        def hits(body: Any) -> str:
            jump = "jump " if body.get("jump") else ""
            return jump + ", ".join(f"{g['type']} {len(g['hits'])}" for g in body["groups"])

        for who, user in (("owner", owner), ("sales1", sales)):
            client = self._client(user, tenant)
            for name, text in searches:
                url = f"{API}/search/?{urlencode({'q': text})}"
                measure(f"search ({who}): {name}", client, url, search_target, hits)

        admin = User.objects.filter(user_type=User.UserType.PLATFORM, is_active=True).first()
        if admin is not None:
            client = self._client(admin, None)
            for name, text in (("distributor", tenant.name.split()[0]), ("GSTIN", tenant.gstin)):
                url = f"{API}/platform/search/?{urlencode({'q': text})}"
                measure(f"platform search: {name}", client, url, search_target, hits)

        client = self._client(owner, tenant)

        def count(body: Any) -> str:
            if isinstance(body, dict) and "results" in body:
                return str(len(body["results"]))
            return str(len(body)) if isinstance(body, list) else ""

        pages = [
            ("suppliers", f"{API}/suppliers/"),
            ("suppliers: search", f"{API}/suppliers/?search={supplier.name.split()[0]}"),
            ("supplier's products", f"{API}/suppliers/{supplier.pk}/products/"),
            ("purchase orders", f"{API}/purchase-orders/"),
            ("purchase orders: late", f"{API}/purchase-orders/?late=true"),
            ("purchase order", f"{API}/purchase-orders/{po.pk}/"),
            ("reorder suggestions", f"{API}/reorder-suggestions/"),
            ("product stats", f"{API}/products/{product.pk}/stats/"),
            ("product on order", f"{API}/products/{product.pk}/on-order/"),
            ("product suppliers", f"{API}/products/{product.pk}/suppliers/"),
            ("suppliers from receipts", f"{API}/suppliers/from-receipts/"),
            ("dashboard (with tiles)", f"{API}/dashboard/"),
            ("shop activity", f"{API}/shop-activity/"),
            ("shop activity: win back", f"{API}/shop-activity/?win_back=true"),
            ("shop activity: slowing", f"{API}/shop-activity/?segment=SLOWING"),
            ("a shop's activity", f"{API}/retailers/{shop.pk}/activity/"),
        ]
        if is_feature_enabled("free_goods", tenant.pk):  # seed_volume switches it on
            pages.append(("free-goods schemes", f"{API}/free-goods-schemes/"))
        for name, url in pages:
            measure(name, client, url, target, count)
        self._measure_cart(tenant, owner, shop, measure, client, target)
        if slow:
            raise CommandError("over the target: " + ", ".join(slow))
        self.stdout.write(self.style.SUCCESS("every p95 is under its target"))

    def _measure_cart(
        self,
        tenant: Tenant,
        owner: User,
        shop: Retailer,
        measure: Callable[..., None],
        client: APIClient,
        target: float,
    ) -> None:
        """A staff member's 40-line cart for a shop, half of it on free-goods schemes: the quote
        with its free lines. The cart is made for the run and removed after."""
        from decimal import Decimal

        with tenant_transaction(tenant.pk):
            on_scheme = list(
                FreeGoodsScheme.objects.values_list("buy_product_id", flat=True).order_by()[:20]
            )
            others = list(
                Product.objects.exclude(pk__in=on_scheme)
                .order_by("code")
                .values_list("pk", flat=True)[: 40 - len(on_scheme)]
            )
            cart, _ = Cart.objects.get_or_create(retailer=shop, user=owner)
            CartLine.objects.filter(cart=cart).delete()
            CartLine.objects.bulk_create(
                [
                    CartLine(tenant_id=tenant.pk, cart=cart, product_id=pk, quantity=Decimal("24"))
                    for pk in [*on_scheme, *others]
                ]
            )

        def lines(body: Any) -> str:
            free = sum(1 for line in body["lines"] if line["is_free"])
            return f"{len(body['lines'])} lines, {free} free"

        try:
            url = f"{API}/retailers/{shop.pk}/cart/"
            measure("cart: 40 lines with schemes", client, url, target, lines)
        finally:
            with tenant_transaction(tenant.pk):
                Cart.objects.filter(pk=cart.pk).delete()
