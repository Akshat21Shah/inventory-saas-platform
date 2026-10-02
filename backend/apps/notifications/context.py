"""What a notification says about its event: the template variables, the shop it concerns, the
people it may go to, the pages it links (one for the shop, one for staff) and the document it
carries. Built from the outbox event's payload and the current rows (the tenant is set)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.utils import translation
from django.utils.translation import gettext as _

from apps.billing.templatetags.documents import day, indian_number, qty, rupees
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
    # Makes the values again in another language (ADR-060): the words inside a message
    # ("by vehicle …", "₹500 to pay", "Cash") follow its recipient.
    rebuild: Callable[[], "EventContext | None"] | None = None
    locale: str = "en"
    _by_locale: dict[str, dict[str, Any]] = field(default_factory=dict)

    def values_in(self, locale: str) -> dict[str, Any]:
        """The template values in ``locale`` (this context's own when it can't be remade)."""
        if locale == self.locale or self.rebuild is None:
            return self.values
        if locale not in self._by_locale:
            with translation.override(locale):
                again = self.rebuild()
            self._by_locale[locale] = again.values if again is not None else self.values
        return self._by_locale[locale]


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
    return _("%(shown)s and %(more)s more") % {"shown": shown, "more": more} if more > 0 else shown


def balance_text(retailer_id: UUID) -> str:
    """The shop's position in words: "₹5,000.00 to pay", "₹200.00 in credit", "nothing to pay"."""
    from apps.ledger.models import RetailerAccount

    balance = (
        RetailerAccount.objects.filter(retailer_id=retailer_id)
        .values_list("balance", flat=True)
        .first()
    ) or Decimal("0")
    if balance > 0:
        return _("%(amount)s to pay") % {"amount": rupees(balance)}
    if balance < 0:
        return _("%(amount)s in credit") % {"amount": rupees(-balance)}
    return _("nothing to pay")


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
            [
                _("%(product)s %(quantity)s short")
                % {"product": name(line["product"]), "quantity": qty(line["short"])}
                for line in p["lines"]
            ]
        )
    if "shipment" in p:
        values["shipment"] = p["shipment"]
        shipment = Fulfilment.objects.filter(order=order, number=p["shipment"]).first()
        if shipment is not None:
            # A phrase for "left the warehouse{{ vehicle }}": " by vehicle MH12AB1234" or nothing.
            number = shipment.vehicle_number
            values["vehicle"] = (_(" by vehicle %(number)s") % {"number": number}) if number else ""
            values["transporter"] = shipment.transporter_name
            values["lr_number"] = shipment.lr_number
            # ADR-057: the shop's delivery code, only while the shipment is on its way; only the
            # shop's texts use it.
            on_its_way = shipment.status == Fulfilment.Status.DISPATCHED
            values["delivery_code"] = (
                _(" Delivery code: %(code)s.") % {"code": shipment.delivery_code}
                if shipment.delivery_code and on_its_way
                else ""
            )
    if "product_id" in p or "product" in p:
        product = Product.objects.filter(pk=p["product_id"]).first() if "product_id" in p else None
        values["product"] = product.name if product else name(p.get("product", ""))
        values["quantity"] = qty(p["quantity"]) if p.get("quantity") else ""
    if p.get("price_increased"):
        values["price_increased"] = _(" The price has gone up since the order was placed.")
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
    if code == "invoice.cancelled":
        p = event.payload
        reissued = p.get("reissued_invoice_id")
        values["note"] = (
            _("Bill %(number)s replaces it.") % {"number": p["reissued_number"]}
            if reissued
            else _("The goods were taken back.")
        )
        if reissued:  # the message opens the new bill
            return _with_shop(
                EventContext(
                    code,
                    values,
                    shop_path=f"/shop/invoices/{reissued}",
                    staff_path=f"/manage/invoices/{reissued}",
                    document=("INVOICE", UUID(reissued)),
                ),
                invoice.retailer,
            )
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


def _return_request(event: OutboxEvent, code: str, base: dict[str, Any]) -> EventContext | None:
    from apps.billing.models import ReturnRequest

    request = (
        ReturnRequest.objects.select_related("retailer", "invoice", "credit_note")
        .prefetch_related("lines__invoice_line")
        .filter(pk=event.payload["return_request_id"])
        .first()
    )
    if request is None:
        return None
    reason = request.get_reason_display()
    if request.note:
        reason = f"{reason}: {request.note}"
    note = request.credit_note
    values = {
        **base,
        "number": request.number,
        "invoice_number": request.invoice.number,
        "items": listing(
            [
                f"{qty(line.quantity)} {line.invoice_line.description}"
                for line in request.lines.all()
            ]
        ),
        "reason": reason,
        "credit_note_number": note.number if note else "",
        "total": rupees(note.grand_total) if note else "",
        "decision": request.decision_note,
    }
    ctx = EventContext(
        code,
        values,
        shop_path=f"/shop/invoices/{request.invoice_id}",
        staff_path=f"/manage/invoices/returns/{request.pk}",
    )
    return _with_shop(ctx, request.retailer)


def _payment(event: OutboxEvent, code: str, base: dict[str, Any]) -> EventContext | None:
    from apps.payments.models import Payment

    payment = (
        Payment.objects.select_related("retailer", "bounce_charge")
        .filter(pk=event.payload["payment_id"])
        .first()
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
        # ADR-057 item 4: the charge added when the cheque bounced, if any.
        "bounce_charge": (
            _(" A cheque bounce charge of %(amount)s was added.")
            % {"amount": rupees(payment.bounce_charge.amount)}
            if payment.bounce_charge is not None
            else ""
        ),
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
    alert = str(StockAlert.Type(p["alert_type"]).label).lower()
    values = {
        **base,
        "product": product.name,
        "alert": alert,
        "quantity": qty(Decimal(p.get("available") or 0)),
    }
    return EventContext(code, values, staff_path="/manage/stock/alerts")


def _einvoice(event: OutboxEvent, code: str, base: dict[str, Any]) -> EventContext | None:
    p = event.payload
    retailer = Retailer.objects.filter(pk=p["retailer_id"]).first()
    if retailer is None:
        return None
    path = (
        f"/manage/invoices/{p['document_id']}"
        if p["document_type"] == "INVOICE"
        else f"/manage/invoices/credit-notes/{p['document_id']}"
    )
    values = {
        **base,
        "shop": retailer.shop_name,
        "document_number": p["document_number"],
        "error": p["error"],
    }
    return EventContext(code, values, retailer=retailer, staff_path=path)


def _ewaybill(event: OutboxEvent, code: str, base: dict[str, Any]) -> EventContext | None:
    p = event.payload
    retailer = Retailer.objects.filter(pk=p["retailer_id"]).first()
    if retailer is None:
        return None
    values = {
        **base,
        "shop": retailer.shop_name,
        "shipment": p["shipment_number"],
        "vehicle": p["vehicle_number"] or _("not given"),
        "invoice_number": p["invoice_number"],
        "error": p["error"],
    }
    return EventContext(
        code,
        values,
        retailer=retailer,
        staff_path=f"/manage/invoices/{p['invoice_id']}",
        extra={"dispatcher_id": p.get("dispatcher_id") or None},
    )


def _purchase_order(event: OutboxEvent, code: str, base: dict[str, Any]) -> EventContext | None:
    """The supplier's emails (ADR-053): sent and cancelled orders go to the supplier's address,
    never to a person."""
    from apps.purchasing.models import PurchaseOrder

    order = (
        PurchaseOrder.objects.select_related("supplier")
        .filter(pk=event.payload["purchase_order_id"])
        .first()
    )
    if order is None:
        return None
    revision = int(event.payload.get("revision") or order.revision)
    values = {
        **base,
        "supplier": order.supplier.name,
        "po_number": order.number,
        "revision": f" (revised {revision})" if revision > 1 else "",  # suppliers: English
        "expected_date": day(order.expected_date) if order.expected_date else "—",
        "reason": event.payload.get("reason") or order.closed_reason,
    }
    return EventContext(
        code,
        values,
        staff_path=f"/manage/purchasing/orders/{order.pk}",
        document=("PURCHASE_ORDER", order.pk),
        extra={"supplier": order.supplier},
    )


def _report(event: OutboxEvent, code: str, base: dict[str, Any]) -> EventContext | None:
    from apps.platform.selectors import get_platform_setting
    from apps.reports.models import ReportRun

    run = ReportRun.objects.filter(pk=event.payload["run_id"]).first()
    if run is None:
        return None
    from apps.reports.registry import REGISTRY

    report = REGISTRY.get(run.report_code)
    values = {
        **base,
        "report": str(report.title) if report is not None else run.title,
        "rows": indian_number(run.row_count or 0),
        "days": get_platform_setting("platform.report_link_days"),
        "error": run.error,
    }
    return EventContext(
        code,
        values,
        staff_path="/manage/reports/exports",
        extra={"requester_id": run.requested_by_id},
    )


BUILDERS = {
    "report": _report,
    "einvoice": _einvoice,
    "ewaybill": _ewaybill,
    "order": _order,
    "backorder": _order,
    "invoice": _invoice,
    "credit_note": _credit_note,
    "payment": _payment,
    "refund": _refund,
    "stock": _stock_alert,
    "purchase_order": _purchase_order,
    "return": _return_request,
}


def build(event: OutboxEvent, code: str, tenant: Tenant) -> EventContext | None:
    """None when the event's object is gone (nothing to say). Built in English; each
    recipient's language is made from it when needed (``EventContext.values_in``)."""
    builder = BUILDERS.get(event.event_type.split(".", 1)[0])
    if builder is None:
        return None
    base = {"distributor": distributor_name(tenant)}

    def make() -> EventContext | None:
        return builder(event, code, dict(base))

    with translation.override("en"):
        ctx = make()
    if ctx is not None:
        ctx.rebuild = make
    return ctx
