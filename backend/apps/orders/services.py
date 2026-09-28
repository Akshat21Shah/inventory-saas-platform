"""Order write logic (spec 5.8, PLAN §4.1, §5.2, ADR-006/013/044).

Lock order (PLAN §5.1, a review blocker): shop account (L1) → order (L2) → stock levels (L3,
product order) → backorder lines (L4) → sequences (L6). Services may skip levels, never go back.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.tax import (
    ComponentRounding,
    RoundOffMethod,
    SupplyType,
    compute_document,
    compute_line,
    round2,
)
from apps.inventory import services as stock
from apps.inventory.availability import ShopStockRules
from apps.inventory.models import ReferenceType, StockLevel
from apps.orders import cart as carts
from apps.orders import credit
from apps.orders.models import (
    Cart,
    Order,
    OrderEvent,
    OrderLine,
    OrderLineDiscount,
    OrderStatus,
    OrderStatusHistory,
)
from apps.orders.quote import OrderRules, Problem, Quote, QuoteLine, build_quote
from apps.platform.registry import SnapshotOn
from apps.platform.selectors import get_setting, settings_snapshot
from apps.retailers.models import Retailer, RetailerAddress
from common import outbox
from common.dates import today_ist
from common.error_codes import ErrorCode
from common.errors import DomainError
from common.sequences import next_value
from common.tenancy import require_tenant_id

ZERO = Decimal("0")


class CartNotReady(DomainError):
    status_code = 422
    code = ErrorCode.CART_NOT_READY
    default_message = "Your cart needs a change before you can place the order."


class PriceChanged(DomainError):
    status_code = 409
    code = ErrorCode.PRICE_CHANGED
    default_message = "Some prices changed. Please check your cart and place the order again."


class CreditLimitExceeded(DomainError):
    status_code = 422
    code = ErrorCode.CREDIT_LIMIT_EXCEEDED
    default_message = "This order is over the credit limit."


class OverdueInvoices(DomainError):
    status_code = 422
    code = ErrorCode.OVERDUE_INVOICES
    default_message = "There are overdue invoices to pay first."


def credit_refusal(
    status: credit.CreditStatus, message: str | None = None, **details: Any
) -> DomainError:
    """The error for a breached credit check: over the limit, or overdue for too long."""
    if status.reason == credit.BreachReason.OVERDUE:
        return OverdueInvoices(message, details={"oldest_due": str(status.oldest_due), **details})
    return CreditLimitExceeded(
        message,
        details={"limit": str(status.limit), "exposure": str(status.exposure), **details},
    )


class NotEnoughStock(DomainError):
    status_code = 409
    code = ErrorCode.INSUFFICIENT_STOCK
    default_message = "There isn't enough stock for some products."


class RetailerOnHold(DomainError):
    status_code = 403
    code = ErrorCode.RETAILER_ON_HOLD
    default_message = "Your account is on hold. Please contact your distributor."


def _problems(found: list[Problem]) -> list[dict[str, Any]]:
    return [{"code": p.code, "details": p.details} for p in found]


def order_rules(snapshot: dict[str, Any], tenant_id: UUID) -> OrderRules:
    """Snapshot values where the key is snapshotted on orders, live values otherwise."""
    return OrderRules.from_settings(
        lambda key: snapshot[key] if key in snapshot else get_setting(key, tenant_id)
    )


def _address_json(address: RetailerAddress | None) -> dict[str, Any]:
    if address is None:
        return {}
    return {
        "id": str(address.pk),
        "label": address.label,
        "line1": address.line1,
        "line2": address.line2,
        "city": address.city,
        "district": address.district,
        "pincode": address.pincode,
        "state_code": address.state_id,
        "state": address.state.name,
    }


def record(
    order: Order,
    event: str,
    *,
    to: str,
    by: User | None,
    note: str = "",
    payload: dict[str, Any] | None = None,
    frm: str | None = None,
) -> None:
    """One timeline entry (append-only)."""
    actor_type = (
        OrderStatusHistory.ActorType.SYSTEM
        if by is None
        else OrderStatusHistory.ActorType.RETAILER
        if by.user_type == User.UserType.RETAILER
        else OrderStatusHistory.ActorType.STAFF
    )
    OrderStatusHistory.objects.create(
        order=order,
        from_status=order.status if frm is None else frm,
        to_status=to,
        event=event,
        actor=by,
        actor_type=actor_type,
        note=note[:500],
        payload=payload or {},
    )


def emit(event_type: str, order: Order, **payload: Any) -> None:
    outbox.emit(
        event_type,
        aggregate_type="Order",
        aggregate_id=order.pk,
        payload={
            "order_id": str(order.pk),
            "number": order.number,
            "retailer_id": str(order.retailer_id),
            "status": order.status,
            **payload,
        },
    )


def recompute_totals(order: Order, lines: list[OrderLine]) -> None:
    """The order's estimates for what stays open (ordered - cancelled), through billing/tax.py
    with the order's snapshot (supply type, price basis, rounding). Saves the order."""
    snap = order.settings_snapshot
    rounding = ComponentRounding(snap.get("tax.component_rounding", "HALF_UP"))
    taxes = []
    for line in lines:
        open_qty = line.qty_ordered - line.qty_cancelled
        if open_qty <= 0:
            continue
        taxes.append(
            compute_line(
                qty=open_qty,
                unit_price=line.unit_price,
                rate=line.gst_rate,
                supply_type=SupplyType(order.supply_type),
                discount_amount=round2(line.discount_amount * open_qty / line.qty_ordered),
                cess_rate=line.cess_rate,
                inclusive=order.prices_include_tax,
                rounding=rounding,
            )
        )
    totals = compute_document(
        taxes,
        round_to_rupee=bool(snap.get("invoicing.round_to_rupee", True)),
        round_off_method=RoundOffMethod(snap.get("invoicing.round_off_method", "NEAREST")),
    )
    order.gross_total = sum((x.gross for x in taxes), ZERO)
    order.discount_total = sum((x.discount for x in taxes), ZERO)
    order.taxable_total = totals.taxable
    order.tax_total = totals.cgst + totals.sgst + totals.igst + totals.cess
    order.round_off = totals.round_off
    order.grand_total = totals.grand_total
    order.save(
        update_fields=[
            "gross_total",
            "discount_total",
            "taxable_total",
            "tax_total",
            "round_off",
            "grand_total",
            "updated_at",
        ]
    )


def line_value(line: OrderLine, quantity: Decimal) -> Decimal:
    """Estimated value incl. GST of part of a line (its estimate is for the ordered quantity)."""
    if line.qty_ordered <= 0:
        return ZERO
    return round2(line.line_total * quantity / line.qty_ordered)


def staff_label(user: User) -> str:
    """ "Priya (Sales)": the staff member's name and role in this tenant."""
    from apps.accounts.models import Membership

    role = (
        Membership.objects.filter(user=user).values_list("role__name", flat=True).first() or "Staff"
    )
    return f"{user.full_name or user.email} ({role})"


# --- Placing an order ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Placement:
    retailer: Retailer
    placed_by: User
    via: str  # Order.PlacedVia
    items: list[tuple[UUID, Decimal]]
    expected_total: Decimal
    address_id: UUID | None = None
    note: str = ""
    cart: Cart | None = None  # cleared once the order is placed


def place_order(placement: Placement) -> Order:
    """Idempotency is the API's (Idempotency-Key, ADR-005): this runs inside that transaction.
    With automatic acceptance (snapshot), the order is accepted right after it commits."""
    from apps.orders.transitions import schedule_auto_accept

    with transaction.atomic():
        order = _place(placement)
        schedule_auto_accept(order)
        return order


def _place(p: Placement) -> Order:
    tenant_id = require_tenant_id()
    snapshot = settings_snapshot(SnapshotOn.ORDER, tenant_id)
    rules = order_rules(snapshot, tenant_id)
    credit.lock_account(p.retailer.pk)  # L1: this shop's orders and credit, one at a time
    retailer = Retailer.objects.get(pk=p.retailer.pk)
    if retailer.status == Retailer.Status.BLOCKED or retailer.deleted_at is not None:
        raise RetailerOnHold()
    if not p.items:
        raise CartNotReady(details={"problems": [{"code": "CART_EMPTY", "details": {}}]})
    quote = build_quote(
        retailer,
        p.items,
        rules=rules,
        stock_rules=ShopStockRules.for_tenant(tenant_id),
        address_id=p.address_id,
    )
    # Stock and credit problems are decided below, under the lock; the rest must be fixed first.
    stock_codes = {
        "NOT_ENOUGH_STOCK",
        "PARTLY_AVAILABLE",
        "CREDIT_LIMIT_EXCEEDED",
        "OVERDUE_INVOICES",
    }
    other = [x for x in quote.blocking if x.code not in stock_codes]
    if other:
        raise CartNotReady(details={"problems": _problems(other)})
    if quote.totals.grand_total != p.expected_total:
        raise PriceChanged(
            details={"expected": str(p.expected_total), "now": str(quote.totals.grand_total)}
        )

    lines = sorted(quote.lines, key=lambda line: line.product_id)
    levels = stock.lock_levels([line.product_id for line in lines], stock.default_warehouse())
    plan = _split_under_lock(lines, levels, rules)
    open_value = sum(
        (
            line_value_of(line, reserved + later)
            for line, (reserved, later, _cancelled) in zip(lines, plan, strict=True)
        ),
        ZERO,
    )
    check = credit.check(retailer, open_value, breach_action=rules.breach_action)
    status = OrderStatus.PLACED
    hold_without_stock = False
    if check.outcome == credit.CreditOutcome.BLOCKED:
        raise credit_refusal(check, order_total=str(open_value))
    if check.outcome == credit.CreditOutcome.NEEDS_APPROVAL:
        status = OrderStatus.ON_HOLD
        hold_without_stock = not bool(snapshot.get("credit.hold_reserves_stock", True))

    year = today_ist().year
    order: Order = Order.objects.create(
        number=f"ORD-{year}-{next_value('ORDER', str(year)):06d}",  # L6
        retailer=retailer,
        placed_by=p.placed_by,
        placed_via=p.via,
        placed_by_label=staff_label(p.placed_by) if p.via == Order.PlacedVia.STAFF else "",
        status=status,
        hold_reason=check.reason if status == OrderStatus.ON_HOLD else "",
        settings_snapshot=snapshot,
        shipping_address=_address_json(quote.address),
        billing_address=_address_json(
            RetailerAddress.objects.filter(retailer=retailer, kind="BILLING", is_default=True)
            .select_related("state")
            .first()
        ),
        place_of_supply_id=quote.place_of_supply_id,
        supply_type=quote.supply_type.value,
        prices_include_tax=quote.prices_include_gst,
        retailer_note=p.note.strip()[:500],
        placed_at=timezone.now(),
        created_by=p.placed_by,
        **_totals(quote),
    )
    ref_type = ReferenceType.ORDER_LINE
    for index, (line, (reserved, later, cancelled)) in enumerate(
        zip(lines, plan, strict=True), start=1
    ):
        row = _create_line(order, index, line, reserved, later, cancelled, hold_without_stock)
        level = levels[line.product_id]
        if row.qty_reserved:
            stock.reserve(
                level, row.qty_reserved, stock.Ref(ref_type, row.pk, order.number), by=p.placed_by
            )
        if row.qty_backordered:
            stock.change_backordered(level, row.qty_backordered)
    if any(cancelled for _, _, cancelled in plan):  # PLACE_AVAILABLE dropped some
        recompute_totals(order, list(order.lines.all()))
    record(
        order,
        OrderEvent.HOLD if status == OrderStatus.ON_HOLD else OrderEvent.PLACE,
        to=status,
        by=p.placed_by,
        frm="",
        payload={"placed_via": p.via},
    )
    emit("order.on_hold" if status == OrderStatus.ON_HOLD else "order.placed", order)
    if p.cart is not None:
        carts.clear(p.cart)
    return order


def line_value_of(line: QuoteLine, quantity: Decimal) -> Decimal:
    if line.tax is None or line.qty <= 0:
        return ZERO
    return round2(line.tax.line_total * quantity / line.qty)


def _split_under_lock(
    lines: list[QuoteLine], levels: dict[UUID, StockLevel], rules: OrderRules
) -> list[tuple[Decimal, Decimal, Decimal]]:
    """Per line, in order: (reserved, backordered, cancelled), with the stock rows locked."""
    plan: list[tuple[Decimal, Decimal, Decimal]] = []
    short: list[dict[str, str]] = []
    for line in lines:
        level = levels[line.product_id]
        available = max(level.quantity_on_hand - level.quantity_reserved, ZERO)
        reserved = min(line.qty, available)
        later = line.qty - reserved
        cancelled = ZERO
        if later > 0 and not rules.backorders_enabled:
            if rules.insufficient_stock_action == "FAIL":
                short.append({"product_id": str(line.product_id), "available": str(reserved)})
            else:  # PLACE_AVAILABLE: the rest is dropped now, and the shop was told in the cart
                cancelled, later = later, ZERO
        plan.append((reserved, later, cancelled))
    if short:
        raise NotEnoughStock(details={"lines": short})
    if all(reserved + later == 0 for reserved, later, _ in plan):
        raise NotEnoughStock(details={"lines": []})
    return plan


def _totals(quote: Quote) -> dict[str, Decimal]:
    taxed = [line.tax for line in quote.lines if line.tax is not None]
    t = quote.totals
    return {
        "gross_total": sum((x.gross for x in taxed), ZERO),
        "discount_total": sum((x.discount for x in taxed), ZERO),
        "taxable_total": t.taxable,
        "tax_total": t.cgst + t.sgst + t.igst + t.cess,
        "round_off": t.round_off,
        "grand_total": t.grand_total,
    }


def _create_line(
    order: Order,
    line_no: int,
    line: QuoteLine,
    reserved: Decimal,
    later: Decimal,
    cancelled: Decimal,
    hold_without_stock: bool,
) -> OrderLine:
    product, price, tax = line.product, line.price, line.tax
    assert product is not None and price is not None and tax is not None
    pending = ZERO
    if hold_without_stock:  # nothing touches stock until the hold is approved
        pending, reserved, later = reserved + later, ZERO, ZERO
    row: OrderLine = OrderLine.objects.create(
        order=order,
        line_no=line_no,
        product=product,
        product_code=product.code,
        product_name=product.name,
        hsn_code=product.hsn_code,
        unit_code=product.unit.code,
        base_price=price.base_price,
        unit_price=price.unit_price,
        price_source=price.price_source,
        discount_per_unit=price.discount_per_unit,
        gst_rate=price.gst_rate,
        cess_rate=price.cess_rate,
        qty_ordered=line.qty,
        qty_pending=pending,
        qty_reserved=reserved,
        qty_backordered=later,
        qty_cancelled=cancelled,
        gross_amount=tax.gross,  # on the order's price basis (incl. GST when prices include it)
        discount_amount=price.discount_total,
        taxable_amount=tax.taxable,
        tax_amount=tax.tax,
        line_total=tax.line_total,
        created_by=order.created_by,
    )
    OrderLineDiscount.objects.bulk_create(
        [
            OrderLineDiscount(
                tenant_id=order.tenant_id,
                order_line=row,
                position=position,
                rule_id=d.rule_id,
                rule_name=d.rule_name,
                discount_type=d.discount_type,
                value=d.value,
                amount=d.amount,
            )
            for position, d in enumerate(price.discounts, start=1)
        ]
    )
    return row
