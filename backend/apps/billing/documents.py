"""Printed documents (PLAN §4.4, spec 5.10-5.12, ADR-046 items 2, 7, 11, 12).

- Tax invoice: the shop's original, and one PDF with three labelled copies for staff (original for
  recipient, duplicate for transporter, triplicate for supplier). An IRN and QR block only when
  the invoice has an IRN (Phase 7).
- Credit note (with the invoice it corrects), payment receipt, Order Confirmation ("This is not a
  tax invoice.").

Rendering runs in background tasks, after the document is saved: the HTML is built in a short
transaction, rendered and stored with none held, and the result recorded in another. Files are
private (``tenants/<id>/documents/...``) and downloaded through short-lived signed links.
"""

from typing import Any
from uuid import UUID

from django.template.loader import render_to_string
from django.utils import timezone

from apps.billing.credit_notes import line_tax
from apps.billing.invoicing import buyer_snapshot, seller_snapshot
from apps.billing.models import (
    CreditNote,
    CreditNoteLine,
    Invoice,
    InvoiceLine,
    OrderConfirmation,
    PdfStatus,
)
from apps.billing.pdf import get_renderer
from apps.billing.tax import amount_in_words, hsn_summary
from apps.ledger.allocation import live_allocations
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.platform.models import Tenant
from common.storage import get_storage
from common.tenancy import require_tenant_id, tenant_transaction

COPIES = ("Original for recipient", "Duplicate for transporter", "Triplicate for supplier")
LINK_SECONDS = 300
PDF = "application/pdf"


def document_key(tenant_id: Any, folder: str, number: str, suffix: str = "") -> str:
    safe = number.replace("/", "-")
    return f"tenants/{tenant_id}/documents/{folder}/{safe}{suffix}.pdf"


def download_url(key: str) -> str | None:
    """A short-lived signed link, or None while the PDF is being prepared."""
    return get_storage().presigned_get(key, LINK_SECONDS) if key else None


def _render(template: str, context: dict[str, Any]) -> bytes:
    return get_renderer().render(render_to_string(template, context))


# --- Invoices ---------------------------------------------------------------------------------


def invoice_context(
    invoice: Invoice,
    copies: tuple[str, ...],
    *,
    lines: list[InvoiceLine] | None = None,
    order_number: str | None = None,
    place: str | None = None,
) -> dict[str, Any]:
    """``lines``, ``order_number`` and ``place`` are read from the database unless given (the CA
    samples print unsaved documents)."""
    if lines is None:
        lines = list(invoice.lines.order_by("line_no"))
    return {
        "doc": invoice,
        "seller": invoice.seller,
        "buyer": invoice.buyer,
        "copies": copies,
        "lines": lines,
        "hsn": hsn_summary([(line.hsn_code, line.gst_rate, line_tax(line)) for line in lines]),
        "intra": invoice.supply_type == "INTRA",
        "place": place or f"{invoice.place_of_supply.name} ({invoice.place_of_supply_id})",
        "order_number": order_number or invoice.order.number,
        "has_cess": any(line.cess_amount for line in lines),
        "has_discount": any(line.discount_amount for line in lines),
        "payment_details": True,  # bank details and terms: on invoices only
    }


def render_invoice(invoice_id: UUID) -> None:
    tenant_id = require_tenant_id()
    with tenant_transaction(tenant_id):
        invoice = Invoice.objects.select_related("order", "place_of_supply").get(pk=invoice_id)
        original = render_to_string("billing/invoice.html", invoice_context(invoice, COPIES[:1]))
        copies = render_to_string("billing/invoice.html", invoice_context(invoice, COPIES))
        key = document_key(tenant_id, "invoices", invoice.number)
        copies_key = document_key(tenant_id, "invoices", invoice.number, "-copies")
    renderer, storage = get_renderer(), get_storage()
    storage.put(key, renderer.render(original), PDF)
    storage.put(copies_key, renderer.render(copies), PDF)
    with tenant_transaction(tenant_id):
        Invoice.objects.filter(pk=invoice_id).update(
            pdf_key=key, copies_pdf_key=copies_key, pdf_status=PdfStatus.READY
        )


# --- Credit notes -----------------------------------------------------------------------------


def credit_note_context(
    note: CreditNote,
    *,
    lines: list[CreditNoteLine] | None = None,
    place: str | None = None,
) -> dict[str, Any]:
    if lines is None:
        lines = list(note.lines.select_related("invoice_line").order_by("line_no"))
    return {
        "doc": note,
        "seller": note.seller,
        "buyer": note.buyer,
        "lines": lines,
        "invoice": note.invoice,
        "intra": note.supply_type == "INTRA",
        "place": place or f"{note.place_of_supply.name} ({note.place_of_supply_id})",
        "has_cess": any(line.cess_amount for line in lines),
    }


def render_credit_note(note_id: UUID) -> None:
    tenant_id = require_tenant_id()
    with tenant_transaction(tenant_id):
        note = CreditNote.objects.select_related("invoice", "place_of_supply").get(pk=note_id)
        html = render_to_string("billing/credit_note.html", credit_note_context(note))
        key = document_key(tenant_id, "credit-notes", note.number)
    get_storage().put(key, get_renderer().render(html), PDF)
    with tenant_transaction(tenant_id):
        CreditNote.objects.filter(pk=note_id).update(pdf_key=key, pdf_status=PdfStatus.READY)


# --- Receipts ---------------------------------------------------------------------------------


def receipt_context(payment: Payment) -> dict[str, Any]:
    tenant = Tenant.objects.select_related("state").get(pk=payment.tenant_id)
    applied: list[tuple[str, Any]] = []
    for row in live_allocations(payment=payment):
        if row.invoice is not None:
            applied.append((row.invoice.number, row.amount))
        elif row.debit_adjustment is not None:
            applied.append((row.debit_adjustment.get_kind_display(), row.amount))
    return {
        "doc": payment,
        "seller": seller_snapshot(tenant),
        "shop": payment.retailer,
        "words": amount_in_words(payment.amount),
        "applied": applied,
        "subject_to_clearance": payment.mode == Payment.Mode.CHEQUE
        and payment.status in (Payment.Status.RECEIVED, Payment.Status.PENDING_CLEARANCE),
        "printed_at": timezone.now(),
    }


def render_receipt(payment_id: UUID) -> None:
    tenant_id = require_tenant_id()
    with tenant_transaction(tenant_id):
        payment = Payment.objects.select_related("retailer").get(pk=payment_id)
        html = render_to_string("billing/receipt.html", receipt_context(payment))
        key = document_key(tenant_id, "receipts", payment.number)
    get_storage().put(key, get_renderer().render(html), PDF)
    with tenant_transaction(tenant_id):
        Payment.objects.filter(pk=payment_id).update(
            receipt_pdf_key=key, receipt_pdf_status=PdfStatus.READY
        )


# --- Order Confirmation -----------------------------------------------------------------------


def confirmation_content(order: Order) -> dict[str, Any]:
    """A snapshot of what was accepted: later changes to the order don't alter the document."""
    tenant = Tenant.objects.select_related("state").get(pk=order.tenant_id)
    return {
        "order_number": order.number,
        "placed_at": order.placed_at.isoformat(),
        "accepted_at": (order.accepted_at or timezone.now()).isoformat(),
        "seller": seller_snapshot(tenant),
        "buyer": buyer_snapshot(order),
        "supply_type": order.supply_type,
        "prices_include_tax": order.prices_include_tax,
        "lines": [
            {
                "code": line.product_code,
                "name": line.product_name,
                "hsn": line.hsn_code,
                "unit": line.unit_code,
                "quantity": str(line.qty_ordered - line.qty_cancelled),
                "later": str(line.qty_backordered),
                "unit_price": str(line.unit_price),
                "discount": str(line.discount_amount),
                "taxable": str(line.taxable_amount),
                "gst_rate": str(line.gst_rate),
                "tax": str(line.tax_amount),
                "total": str(line.line_total),
            }
            for line in order.lines.order_by("line_no")
        ],
        "totals": {
            "gross": str(order.gross_total),
            "discount": str(order.discount_total),
            "taxable": str(order.taxable_total),
            "tax": str(order.tax_total),
            "round_off": str(order.round_off),
            "grand_total": str(order.grand_total),
        },
    }


def create_confirmation(order: Order) -> OrderConfirmation:
    """At acceptance when the order's ⚙ orders.send_confirmation_on_accept is on (idempotent)."""
    from common import outbox

    existing: OrderConfirmation | None = OrderConfirmation.objects.filter(order=order).first()
    if existing is not None:
        return existing
    confirmation: OrderConfirmation = OrderConfirmation.objects.create(
        order=order, content=confirmation_content(order)
    )
    outbox.emit(
        "order_confirmation.created",
        aggregate_type="OrderConfirmation",
        aggregate_id=confirmation.pk,
        payload={
            "confirmation_id": str(confirmation.pk),
            "order_id": str(order.pk),
            "order_number": order.number,
            "retailer_id": str(order.retailer_id),
        },
    )
    return confirmation


def render_confirmation(confirmation_id: UUID) -> None:
    tenant_id = require_tenant_id()
    with tenant_transaction(tenant_id):
        confirmation = OrderConfirmation.objects.get(pk=confirmation_id)
        html = render_to_string("billing/order_confirmation.html", {"doc": confirmation.content})
        key = document_key(tenant_id, "order-confirmations", confirmation.content["order_number"])
    get_storage().put(key, get_renderer().render(html), PDF)
    with tenant_transaction(tenant_id):
        OrderConfirmation.objects.filter(pk=confirmation_id).update(
            pdf_key=key, pdf_status=PdfStatus.READY
        )


# --- Failures and regeneration ----------------------------------------------------------------

RENDERERS = {
    "invoice": render_invoice,
    "credit_note": render_credit_note,
    "receipt": render_receipt,
    "order_confirmation": render_confirmation,
}


def mark_failed(kind: str, object_id: UUID) -> None:
    with tenant_transaction(require_tenant_id()):
        if kind == "invoice":
            Invoice.objects.filter(pk=object_id).update(pdf_status=PdfStatus.FAILED)
        elif kind == "credit_note":
            CreditNote.objects.filter(pk=object_id).update(pdf_status=PdfStatus.FAILED)
        elif kind == "receipt":
            Payment.objects.filter(pk=object_id).update(receipt_pdf_status=PdfStatus.FAILED)
        else:
            OrderConfirmation.objects.filter(pk=object_id).update(pdf_status=PdfStatus.FAILED)
