"""What a notification says about its event: the template variables, the shop it concerns, the
people it may go to, the pages it links (one for the shop, one for staff) and the document it
carries. Built from the outbox event's payload and the current rows (the tenant is set)."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from apps.billing.templatetags.documents import day, qty, rupees
from apps.platform.models import Tenant
from apps.retailers.models import Retailer
from common.models import OutboxEvent
from common.tenancy import require_tenant_id

LIST_LIMIT = 5  # "A 2→3, B 1→0 and 3 more"


@dataclass
class EventContext:
    code: str
    values: dict[str, Any]
    retailer: Retailer | None = None
    salesperson_id: UUID | None = None
    collector_id: UUID | None = None
    shop_path: str = ""  # the page a shop login opens
    staff_path: str = ""  # the page staff open
    document: tuple[str, UUID] | None = None  # (DocumentLink.Kind, object id)
    extra: dict[str, Any] = field(default_factory=dict)


def distributor_name(tenant: Tenant) -> str:
    """The name the shop knows: the branding display name, else the trade name."""
    from apps.platform.selectors import public_branding

    brand = public_branding(tenant.slug) or {}
    return str(brand.get("display_name") or tenant.name)


def current_tenant() -> Tenant:
    return Tenant.objects.get(pk=require_tenant_id())


def listing(items: list[str]) -> str:
    shown = ", ".join(items[:LIST_LIMIT])
    more = len(items) - LIST_LIMIT
    return f"{shown} and {more} more" if more > 0 else shown


def balance_text(retailer_id: UUID) -> str:
    """The shop's position in words: "₹5,000.00 to pay", "₹200.00 in credit", "nothing to pay"."""
    from apps.ledger.models import RetailerAccount

    balance = (
        RetailerAccount.objects.filter(retailer_id=retailer_id)
        .values_list("balance", flat=True)
        .first()
    ) or Decimal("0")
    if balance > 0:
        return f"{rupees(balance)} to pay"
    if balance < 0:
        return f"{rupees(-balance)} in credit"
    return "nothing to pay"


def _with_shop(ctx: EventContext, retailer: Retailer) -> EventContext:
    ctx.retailer = retailer
    ctx.salesperson_id = retailer.salesperson_id
    ctx.values["shop"] = retailer.shop_name
    return ctx


def _order(event: OutboxEvent, code: str, base: dict[str, Any]) -> EventContext | None:
    from apps.catalog.models import Product
    from apps.orders.models import Fulfilment, Order

    p = event.payload
    order = Order.objects.select_related("retailer").filter(pk=p["order_id"]).first()
    if order is None:
        return None
    values = {
        **base,
        "order_number": order.number,
        "total": rupees(order.grand_total),
        "placed_by": order.placed_by_label,
        "hold_reason": order.get_hold_reason_display() if order.hold_reason else "",
        "reason": p.get("reason") or order.rejection_reason or order.cancellation_reason,
    }
    # Payloads carry product codes; people read names (the order's line snapshot names first).
    codes = {c["product"] for c in p.get("changes", [])} | {
        line["product"] for line in p.get("lines", [])
    }
    if p.get("product") and "product_id" not in p:
        codes.add(p["product"])
    names = dict(
        order.lines.filter(product_code__in=codes).values_list("product_code", "product_name")
    )

    def name(code: str) -> str:
        return str(names.get(code, code))

    if "changes" in p:
        values["changes"] = listing(
            [f"{name(c['product'])} {qty(c['from'])}→{qty(c['to'])}" for c in p["changes"]]
        )
    if "lines" in p:
        values["items"] = listing(
            [f"{name(line['product'])} {qty(line['short'])} short" for line in p["lines"]]
        )
    if "shipment" in p:
        values["shipment"] = p["shipment"]
        shipment = Fulfilment.objects.filter(order=order, number=p["shipment"]).first()
        if shipment is not None:
            values["vehicle"] = shipment.vehicle_number
            values["transporter"] = shipment.transporter_name
            values["lr_number"] = shipment.lr_number
    if "product_id" in p or "product" in p:
        product = Product.objects.filter(pk=p["product_id"]).first() if "product_id" in p else None
        values["product"] = product.name if product else name(p.get("product", ""))
        values["quantity"] = qty(p["quantity"]) if p.get("quantity") else ""
    if p.get("price_increased"):
        values["price_increased"] = " The price has gone up since you ordered."
    ctx = EventContext(
        code,
        values,
        shop_path=f"/shop/orders/{order.pk}",
        staff_path=f"/manage/orders/{order.pk}",
    )
    if code == "backorder.proposed" and "product_id" in p:
        ctx.staff_path = f"/manage/backorders/{p['product_id']}"
    if code == "order.accepted":
        from apps.billing.models import OrderConfirmation

        confirmation = OrderConfirmation.objects.filter(order=order).first()
        if confirmation is not None:
            ctx.document = ("ORDER_CONFIRMATION", confirmation.pk)
    return _with_shop(ctx, order.retailer)


def _invoice(event: OutboxEvent, code: str, base: dict[str, Any]) -> EventContext | None:
    from apps.billing.models import Invoice

    invoice = (
        Invoice.objects.select_related("retailer", "order")
        .filter(pk=event.payload["invoice_id"])
        .first()
    )
    if invoice is None:
        return None
    values = {
        **base,
        "invoice_number": invoice.number,
        "total": rupees(invoice.grand_total),
        "due_date": day(invoice.due_date),
        "order_number": invoice.order.number,
    }
    ctx = EventContext(
        code,
        values,
        shop_path=f"/shop/invoices/{invoice.pk}",
        staff_path=f"/manage/invoices/{invoice.pk}",
        document=("INVOICE", invoice.pk),
    )
    return _with_shop(ctx, invoice.retailer)


def _credit_note(event: OutboxEvent, code: str, base: dict[str, Any]) -> EventContext | None:
    from apps.billing.models import CreditNote

    note = (
        CreditNote.objects.select_related("retailer", "invoice")
        .filter(pk=event.payload["credit_note_id"])
        .first()
    )
    if note is None:
        return None
    reason = note.get_kind_display()
    if note.reason_note:
        reason = f"{reason}: {note.reason_note}"
    values = {
        **base,
        "credit_note_number": note.number,
        "total": rupees(note.grand_total),
        "invoice_number": note.invoice.number,
        "reason": reason,
    }
    ctx = EventContext(
        code,
        values,
        shop_path=f"/shop/invoices/{note.invoice_id}",
        staff_path=f"/manage/invoices/credit-notes/{note.pk}",
        document=("CREDIT_NOTE", note.pk),
    )
    return _with_shop(ctx, note.retailer)


def _payment(event: OutboxEvent, code: str, base: dict[str, Any]) -> EventContext | None:
    from apps.payments.models import Payment

    payment = (
        Payment.objects.select_related("retailer").filter(pk=event.payload["payment_id"]).first()
    )
    if payment is None:
        return None
    values = {
        **base,
        "receipt_number": payment.number,
        "amount": rupees(payment.amount),
        "mode": payment.get_mode_display(),
        "cheque_number": payment.cheque_number,
        "reason": event.payload.get("reason") or payment.reversal_reason,
        "cheque_date": day(payment.cheque_date or payment.payment_date),
        "balance": balance_text(payment.retailer_id),
    }
    ctx = EventContext(
        code,
        values,
        collector_id=payment.collected_by_id,
        shop_path="/shop/payments",
        staff_path=f"/manage/payments/{payment.pk}",
    )
    if code in ("payment.received", "payment.bounced"):
        ctx.document = ("RECEIPT", payment.pk)  # the bounced one is printed "Cheque bounced"
    return _with_shop(ctx, payment.retailer)


def _refund(event: OutboxEvent, code: str, base: dict[str, Any]) -> EventContext | None:
    from apps.payments.models import Refund

    refund = Refund.objects.select_related("retailer").filter(pk=event.payload["refund_id"]).first()
    if refund is None:
        return None
    values = {
        **base,
        "refund_number": refund.number,
        "amount": rupees(refund.amount),
        "mode": refund.get_mode_display(),
        "reason": refund.reversal_reason,
    }
    ctx = EventContext(
        code,
        values,
        shop_path="/shop/payments",
        staff_path=f"/manage/payments/refunds/{refund.pk}",
    )
    if code == "refund.recorded":
        ctx.document = ("REFUND_VOUCHER", refund.pk)
    return _with_shop(ctx, refund.retailer)


def _stock_alert(event: OutboxEvent, code: str, base: dict[str, Any]) -> EventContext | None:
    from apps.catalog.models import Product
    from apps.inventory.models import StockAlert

    p = event.payload
    product = Product.objects.filter(pk=p["product_id"]).first()
    if product is None:
        return None
    alert = StockAlert.Type(p["alert_type"]).label.lower()
    values = {
        **base,
        "product": product.name,
        "alert": alert,
        "quantity": qty(Decimal(p.get("available") or 0)),
    }
    return EventContext(code, values, staff_path="/manage/stock/alerts")


BUILDERS = {
    "order": _order,
    "backorder": _order,
    "invoice": _invoice,
    "credit_note": _credit_note,
    "payment": _payment,
    "refund": _refund,
    "stock": _stock_alert,
}


def build(event: OutboxEvent, code: str, tenant: Tenant) -> EventContext | None:
    """None when the event's object is gone (nothing to say)."""
    builder = BUILDERS.get(event.event_type.split(".", 1)[0])
    if builder is None:
        return None
    return builder(event, code, {"distributor": distributor_name(tenant)})
