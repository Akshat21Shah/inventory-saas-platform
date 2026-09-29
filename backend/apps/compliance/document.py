"""The neutral e-invoice document (ADR-049 item 4): everything the portal needs about one invoice
or credit note, in our own words, built from the document's issued snapshots.

These are deliberately NOT the portal's field names. The real GSP adapter maps this document onto
the provider's request; mapping it here would be guessing.
TODO(verify): the e-invoice schema's field names, mandatory fields and validations (HSN digits by
turnover, unit codes, PIN code vs state, rounding tolerances between lines and totals), PROGRESS
pre-production items 14-17.
"""

from decimal import Decimal
from typing import Any

from apps.billing.models import CreditNote, CreditNoteLine, Invoice, InvoiceLine
from apps.compliance.models import DocumentType
from apps.platform.models import Tenant

VERSION = 1


def number_key(number: str) -> str:
    """Document numbers compare case-insensitively for duplicates (ADR-049 item 8)."""
    return number.strip().upper()


def _money(value: Decimal | int) -> str:
    return f"{Decimal(value):.2f}"


def _seller(doc: Invoice | CreditNote) -> dict[str, Any]:
    """Names and GSTIN from the document's snapshot; the structured address from the business
    (the snapshot keeps it as one printed line), read when the document is sent, just after
    issue."""
    tenant = Tenant.objects.get(pk=doc.tenant_id)
    snap = doc.seller
    return {
        "gstin": snap.get("gstin", ""),
        "legal_name": snap.get("legal_name", ""),
        "trade_name": snap.get("trade_name", ""),
        "address_line1": tenant.address_line1,
        "address_line2": tenant.address_line2,
        "city": tenant.city,
        "pincode": tenant.pincode,
        "state_code": snap.get("state_code", ""),
        "phone": snap.get("phone", ""),
        "email": snap.get("email", ""),
    }


def _address(address: dict[str, Any] | None) -> dict[str, Any] | None:
    if not address:
        return None
    return {
        "address_line1": address.get("line1", ""),
        "address_line2": address.get("line2", ""),
        "city": address.get("city", ""),
        "pincode": address.get("pincode", ""),
        "state_code": address.get("state_code", ""),
    }


def _buyer(doc: Invoice | CreditNote) -> dict[str, Any]:
    snap = doc.buyer
    billing = _address(snap.get("billing_address")) or {}
    return {
        "gstin": snap.get("gstin", ""),
        "legal_name": snap.get("name", ""),
        "trade_name": snap.get("name", ""),
        **billing,
        "state_code": billing.get("state_code") or snap.get("state_code", ""),
        "phone": snap.get("phone", ""),
    }


def _ship_to(doc: Invoice | CreditNote) -> dict[str, Any] | None:
    billing, shipping = doc.buyer.get("billing_address"), doc.buyer.get("shipping_address")
    if not shipping or (billing and shipping.get("id") == billing.get("id")):
        return None
    return _address(shipping)


def _common(doc: Invoice | CreditNote, kind: str, number: str, day: Any) -> dict[str, Any]:
    return {
        "version": VERSION,
        "document": {
            "type": kind,
            "number": number,
            "number_key": number_key(number),
            "date": day.isoformat(),
            "financial_year": doc.fy,
        },
        "supply": {
            "category": "B2B",
            "type": doc.supply_type,  # INTRA / INTER
            "reverse_charge": doc.reverse_charge,
            "place_of_supply": doc.place_of_supply_id,
        },
        "seller": _seller(doc),
        "buyer": _buyer(doc),
        "ship_to": _ship_to(doc),
        "totals": {
            "taxable_value": _money(doc.taxable_total),
            "cgst": _money(doc.cgst_total),
            "sgst": _money(doc.sgst_total),
            "igst": _money(doc.igst_total),
            "cess": _money(doc.cess_total),
            "round_off": _money(doc.round_off),
            "grand_total": _money(doc.grand_total),
        },
    }


def _invoice_line(line: InvoiceLine) -> dict[str, Any]:
    return {
        "line_no": line.line_no,
        "description": line.description,
        "product_code": line.product_code,
        "hsn_code": line.hsn_code,
        "is_service": False,
        "quantity": f"{line.quantity:.3f}",
        "unit_code": line.unit_code,  # our unit code; the GST unit code (UQC) is item 6
        "unit_price": _money(line.unit_price),
        "gross_amount": _money(line.gross_amount),
        "discount": _money(line.discount_amount),
        "taxable_value": _money(line.taxable_value),
        "gst_rate": f"{line.gst_rate:.2f}",
        "cgst_amount": _money(line.cgst_amount),
        "sgst_amount": _money(line.sgst_amount),
        "igst_amount": _money(line.igst_amount),
        "cess_rate": f"{line.cess_rate:.2f}",
        "cess_amount": _money(line.cess_amount),
        "line_total": _money(line.line_total),
    }


def invoice_document(invoice: Invoice) -> dict[str, Any]:
    document = _common(invoice, DocumentType.INVOICE, invoice.number, invoice.invoice_date)
    document["lines"] = [_invoice_line(line) for line in invoice.lines.order_by("line_no")]
    return document


def _credit_line(line: CreditNoteLine) -> dict[str, Any]:
    source = line.invoice_line
    return {
        **_invoice_line(source),
        "line_no": line.line_no,
        "quantity": f"{line.quantity:.3f}",
        "gross_amount": _money(line.taxable_value),
        "discount": _money(0),
        "taxable_value": _money(line.taxable_value),
        "cgst_amount": _money(line.cgst_amount),
        "sgst_amount": _money(line.sgst_amount),
        "igst_amount": _money(line.igst_amount),
        "cess_amount": _money(line.cess_amount),
        "line_total": _money(line.line_total),
    }


def credit_note_document(note: CreditNote) -> dict[str, Any]:
    document = _common(note, DocumentType.CREDIT_NOTE, note.number, note.note_date)
    lines = note.lines.select_related("invoice_line").order_by("line_no")
    document["lines"] = [_credit_line(line) for line in lines]
    document["original_invoice"] = {
        "number": note.invoice.number,
        "date": note.invoice.invoice_date.isoformat(),
    }
    return document
