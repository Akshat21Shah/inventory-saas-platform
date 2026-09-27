"""Phase 4 demo orders for ``manage.py seed``: every tab of the order board has something in it.

Per distributor, through the normal services: new orders (one placed by the salesperson for a
shop, one with a delivery note), a credit hold, a rejected and a cancelled order, orders packed,
dispatched and completed, accepted orders with items waiting on backorder, and a backorder
proposal to confirm (goods arrived for an older order). Only for a tenant with no orders yet, so
re-running the seed never adds them twice.
"""

from decimal import ROUND_CEILING, Decimal
from typing import Any

from django.db.models import QuerySet

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.inventory import receipts
from apps.inventory.availability import ShopStockRules
from apps.inventory.receipts import LineInput, ReceiptInput
from apps.orders import fulfilment, transitions
from apps.orders.cart import live_rules
from apps.orders.models import Fulfilment, Order
from apps.orders.quote import build_quote
from apps.orders.services import Placement, place_order
from apps.platform.models import Tenant
from apps.retailers.models import Retailer, RetailerUser
from apps.retailers.services import update_credit
from apps.shop.selectors import visible_products

Line = tuple[Product, Decimal]


def _qty(product: Product, times: int) -> Decimal:
    """A quantity the product can be ordered in: its minimum, rounded up to its multiple."""
    step = product.order_multiple or Decimal("1")
    base = (Decimal(product.min_order_qty) / step).to_integral_value(ROUND_CEILING) * step
    return Decimal(max(base, step) * times)


def _login(shop: Retailer) -> User:
    user: User = RetailerUser.objects.select_related("user").get(retailer=shop).user
    return user


def _place(
    tenant: Tenant, shop: Retailer, lines: list[Line], *, by: User | None = None, note: str = ""
) -> Order | None:
    items = [(product.pk, qty) for product, qty in lines]
    quote = build_quote(
        shop, items, rules=live_rules(tenant.pk), stock_rules=ShopStockRules.for_tenant(tenant.pk)
    )
    if not quote.can_place:
        return None
    return place_order(
        Placement(
            retailer=shop,
            placed_by=by or _login(shop),
            via=Order.PlacedVia.STAFF if by else Order.PlacedVia.RETAILER_APP,
            items=items,
            expected_total=quote.totals.grand_total,
            note=note,
        )
    )


def seed_orders(tenant: Tenant, owner: User) -> int:
    """Run inside ``tenant_context(tenant.id)`` after the catalog and stock. Returns the count."""
    if Order.objects.exists():
        return 0
    sales = User.objects.get(email=f"sales@{tenant.slug}.example.com")
    warehouse = User.objects.get(email=f"warehouse@{tenant.slug}.example.com")
    shops = list(
        Retailer.objects.filter(status=Retailer.Status.ACTIVE, deleted_at__isnull=True)
        .filter(logins__isnull=False)
        .order_by("code")
    )
    if len(shops) < 11:
        return 0
    # Annotated with the stock the shop may order (stock_available).
    visible: QuerySet[Any] = visible_products(shops[0]).order_by("code")
    in_stock = list(visible.filter(stock_available__gte=40)[:30])
    waiting = list(visible.filter(stock_available__lte=0)[:2])
    if len(in_stock) < 12 or len(waiting) < 2:
        return 0

    def lines(start: int, count: int, times: int = 2) -> list[Line]:
        return [(p, _qty(p, times)) for p in in_stock[start : start + count]]

    made: list[Order | None] = []

    def accept(order: Order | None) -> Fulfilment | None:
        if order is None:
            return None
        transitions.accept_order(order.pk, by=owner)
        return Fulfilment.objects.filter(order=order).order_by("created_at").first()

    # Oldest first: the goods receipt at the end serves the oldest waiting order.
    proposal_order = _place(tenant, shops[4], [(waiting[0], _qty(waiting[0], 6))])
    accept(proposal_order)
    completed = accept(_place(tenant, shops[0], lines(0, 3)))
    if completed is not None:
        fulfilment.pack(completed.pk, {}, by=warehouse)
        fulfilment.dispatch(
            completed.pk,
            fulfilment.Transport("MH12AB1234", "Speed Logistics", "LR-1001"),
            by=warehouse,
        )
        fulfilment.deliver(completed.pk, by=warehouse)
    dispatched = accept(_place(tenant, shops[1], lines(3, 2)))
    if dispatched is not None:
        fulfilment.pack(dispatched.pk, {}, by=warehouse)
        fulfilment.dispatch(dispatched.pk, fulfilment.Transport("MH14CD5678", "", ""), by=warehouse)
    packed = accept(_place(tenant, shops[2], lines(5, 2)))
    if packed is not None:
        fulfilment.pack(packed.pk, {}, by=warehouse)
    accept(_place(tenant, shops[3], [*lines(7, 2), (waiting[1], _qty(waiting[1], 3))]))
    rejected = _place(tenant, shops[5], lines(9, 1))
    if rejected is not None:
        transitions.reject_order(rejected.pk, reason="Outside our delivery area", by=owner)
    cancelled = _place(tenant, shops[6], lines(10, 1))
    if cancelled is not None:
        transitions.cancel_order(
            cancelled.pk, by=_login(shops[6]), reason="Ordered twice", retailer_id=shops[6].pk
        )
    # A shop near its credit limit: the order waits for approval.
    update_credit(shops[7].pk, credit_limit=Decimal("500"), payment_terms_days=15, by=owner)
    made.append(_place(tenant, shops[7], lines(11, 1, times=10)))
    made.append(_place(tenant, shops[8], lines(0, 2)))
    made.append(_place(tenant, shops[9], lines(2, 3), by=sales))
    made.append(
        _place(tenant, shops[10], lines(5, 1), note="Deliver before 11 am; shop opposite the bank")
    )
    receipts.create_and_post(
        ReceiptInput(
            lines=[LineInput(waiting[0].pk, _qty(waiting[0], 4))],
            supplier_name="Demo Wholesale Pvt Ltd",
            bill_number="DW/2026/0431",
        ),
        by=warehouse,
    )
    return Order.objects.count()
