"""What a set of products and quantities costs a shop right now (spec 5.8, PLAN §5.3), shared by
the cart and order placement so both give the same answer:

- prices from ``resolve_prices`` (every discount rule applied, ADR-038), line tax and document
  totals from ``billing/tax.py``;
- the split between what can be sent now and what goes on backorder (an estimate: final at
  placement, where the stock rows are locked);
- problems the shop has to fix (minimums, multiples, unavailable products, not enough stock with
  backorders off, minimum order value) and the credit outcome.

Nothing here writes to the database.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from apps.billing.tax import (
    ComponentRounding,
    DocumentTotals,
    LineTax,
    RoundOffMethod,
    SupplyType,
    compute_document,
    compute_line,
)
from apps.catalog.models import Product
from apps.inventory.availability import Availability, ShopStockRules, availability
from apps.orders import credit
from apps.platform.models import Tenant
from apps.pricing.resolve import PriceResult, resolve_prices
from apps.retailers.models import Retailer, RetailerAddress
from apps.shop.selectors import visible_products
from common.dates import today_ist

ZERO = Decimal("0")


@dataclass(frozen=True)
class Problem:
    """Machine code (translated by the app) with the numbers it needs."""

    code: str
    details: dict[str, Any] = field(default_factory=dict)
    blocking: bool = True


@dataclass(frozen=True)
class OrderRules:
    """The settings an order depends on: live for a cart, the snapshot for an order."""

    backorders_enabled: bool = True
    insufficient_stock_action: str = "FAIL"  # FAIL | PLACE_AVAILABLE
    min_order_value: Decimal | None = None
    min_order_value_basis: str = "INCL_GST"
    breach_action: str = "REQUIRE_APPROVAL"
    component_rounding: str = "HALF_UP"
    round_to_rupee: bool = True
    round_off_method: str = "NEAREST"

    @classmethod
    def from_settings(cls, get: Callable[[str], Any]) -> "OrderRules":
        minimum = get("orders.min_order_value")
        return cls(
            backorders_enabled=bool(get("backorders.enabled")),
            insufficient_stock_action=str(get("orders.insufficient_stock_action")),
            min_order_value=None if minimum in (None, "") else Decimal(str(minimum)),
            min_order_value_basis=str(get("orders.min_order_value_basis")),
            breach_action=str(get("credit.breach_action")),
            component_rounding=str(get("tax.component_rounding")),
            round_to_rupee=bool(get("invoicing.round_to_rupee")),
            round_off_method=str(get("invoicing.round_off_method")),
        )


@dataclass
class QuoteLine:
    product_id: UUID
    qty: Decimal
    product: Product | None  # None: the product no longer exists for this shop
    price: PriceResult | None = None
    tax: LineTax | None = None
    available: Decimal = ZERO  # on hand - reserved (never shown unless the tenant allows)
    ready_qty: Decimal = ZERO
    later_qty: Decimal = ZERO  # backordered, or dropped with backorders off (see problems)
    stock: Availability | None = None
    problems: list[Problem] = field(default_factory=list)

    @property
    def orderable(self) -> bool:
        return self.price is not None and self.tax is not None


@dataclass
class Quote:
    lines: list[QuoteLine]
    totals: DocumentTotals
    supply_type: SupplyType
    place_of_supply_id: str
    address: RetailerAddress | None
    prices_include_gst: bool
    rules: OrderRules
    credit: credit.CreditStatus
    problems: list[Problem] = field(default_factory=list)

    @property
    def blocking(self) -> list[Problem]:
        found = [p for p in self.problems if p.blocking]
        for line in self.lines:
            found += [p for p in line.problems if p.blocking]
        return found

    @property
    def can_place(self) -> bool:
        return bool(self.lines) and not self.blocking

    @property
    def item_count(self) -> int:
        return len(self.lines)


def delivery_address(retailer: Retailer, address_id: UUID | None) -> RetailerAddress | None:
    """The chosen saved address, else the default shipping one, else the default billing one."""
    addresses = RetailerAddress.objects.filter(retailer=retailer)
    if address_id is not None:
        chosen: RetailerAddress | None = addresses.filter(pk=address_id).first()
        return chosen
    found: RetailerAddress | None = (
        addresses.filter(is_default=True).order_by("-kind").first()  # SHIPPING before BILLING
    )
    return found


def supply_type_for(tenant_state: str, place_of_supply: str) -> SupplyType:
    """ADR-010: same state → CGST + SGST; otherwise IGST."""
    return SupplyType.INTRA if tenant_state == place_of_supply else SupplyType.INTER


def build_quote(
    retailer: Retailer,
    items: Sequence[tuple[UUID, Decimal]],
    *,
    rules: OrderRules,
    stock_rules: ShopStockRules,
    address_id: UUID | None = None,
    on: date | None = None,
) -> Quote:
    day = on or today_ist()
    ids = [product_id for product_id, _ in items]
    visible = {
        p.pk: p
        for p in visible_products(retailer, day)
        .filter(pk__in=ids)
        .select_related("unit", "pack_unit", "brand")
    }
    lines = [QuoteLine(product_id=pid, qty=qty, product=visible.get(pid)) for pid, qty in items]
    missing = [line.product_id for line in lines if line.product is None]
    if missing:  # still show what it was, marked unavailable
        known = {p.pk: p for p in Product.objects.filter(pk__in=missing).select_related("unit")}
        for line in lines:
            if line.product is None:
                line.product = known.get(line.product_id)
                line.problems.append(Problem("PRODUCT_UNAVAILABLE"))

    address = delivery_address(retailer, address_id)
    place = address.state_id if address else retailer.state_id
    tenants = Tenant.objects.filter(pk=retailer.tenant_id)
    tenant_state = str(tenants.values_list("state_id", flat=True).get())
    supply = supply_type_for(tenant_state, place)
    rounding = ComponentRounding(rules.component_rounding)

    priced = [line for line in lines if not line.problems and line.product is not None]
    wanted: list[tuple[Product, Decimal]] = [
        (product, line.qty) for line in priced if (product := line.product) is not None
    ]
    results = resolve_prices(retailer, wanted, on=day)
    include_gst = False
    for line, price in zip(priced, results, strict=True):
        product = line.product
        assert product is not None
        if not price.valid:
            line.problems.append(Problem("PRODUCT_UNAVAILABLE"))
            continue
        include_gst = price.prices_include_gst
        line.price = price
        line.tax = compute_line(
            qty=line.qty,
            unit_price=price.unit_price,
            rate=price.gst_rate,
            supply_type=supply,
            discount_amount=price.discount_total,
            cess_rate=price.cess_rate,
            inclusive=price.prices_include_gst,
            rounding=rounding,
        )
        _check_quantity(line, product)
        _split(line, product, rules, stock_rules)

    taxes = [line.tax for line in lines if line.tax is not None]
    totals = compute_document(
        taxes,
        round_to_rupee=rules.round_to_rupee,
        round_off_method=RoundOffMethod(rules.round_off_method),
    )
    problems: list[Problem] = []
    if retailer.status == Retailer.Status.BLOCKED:
        problems.append(Problem("RETAILER_ON_HOLD"))
    if rules.min_order_value is not None and taxes:
        basis = totals.grand_total if rules.min_order_value_basis == "INCL_GST" else totals.taxable
        if basis < rules.min_order_value:
            problems.append(
                Problem(
                    "MIN_ORDER_VALUE",
                    {"minimum": str(rules.min_order_value), "basis": rules.min_order_value_basis},
                )
            )
    status = credit.check(retailer, totals.grand_total, breach_action=rules.breach_action)
    overdue = status.reason == credit.BreachReason.OVERDUE
    if status.outcome == credit.CreditOutcome.BLOCKED and overdue:
        problems.append(Problem("OVERDUE_INVOICES", {"oldest_due": str(status.oldest_due)}))
    elif status.outcome == credit.CreditOutcome.BLOCKED:
        problems.append(
            Problem(
                "CREDIT_LIMIT_EXCEEDED",
                {"limit": str(status.limit), "available": str(status.available)},
            )
        )
    elif status.outcome == credit.CreditOutcome.NEEDS_APPROVAL:
        problems.append(
            Problem("CREDIT_APPROVAL_NEEDED", {"reason": status.reason}, blocking=False)
        )
    return Quote(
        lines=lines,
        totals=totals,
        supply_type=supply,
        place_of_supply_id=place,
        address=address,
        prices_include_gst=include_gst,
        rules=rules,
        credit=status,
        problems=problems,
    )


def _check_quantity(line: QuoteLine, product: Product) -> None:
    if line.qty < product.min_order_qty:
        line.problems.append(Problem("QTY_BELOW_MINIMUM", {"minimum": str(product.min_order_qty)}))
    elif product.order_multiple and (line.qty / product.order_multiple) % 1:
        line.problems.append(Problem("QTY_NOT_MULTIPLE", {"step": str(product.order_multiple)}))


def _split(line: QuoteLine, product: Product, rules: OrderRules, stock: ShopStockRules) -> None:
    available = max(Decimal(getattr(product, "stock_available", ZERO)), ZERO)
    line.available = available
    line.ready_qty = min(line.qty, available)
    line.later_qty = line.qty - line.ready_qty
    line.stock = availability(available, product.reorder_level, stock)
    if line.later_qty > 0 and not rules.backorders_enabled:
        details = {"available": str(line.ready_qty)}
        if rules.insufficient_stock_action == "FAIL":
            line.problems.append(Problem("NOT_ENOUGH_STOCK", details))
        else:  # PLACE_AVAILABLE: the rest is dropped at placement, so tell the shop now
            line.problems.append(Problem("PARTLY_AVAILABLE", details, blocking=False))
