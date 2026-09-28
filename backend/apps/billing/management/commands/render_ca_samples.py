"""Print the sample documents for the Chartered Accountant's review (docs/CA_REVIEW.md).

The figures come from the tax engine and the pages from the real templates. Nothing is written to
the database: the documents are built in memory from CA_REVIEW Example 5 (four lines at 18%, 5%,
0% and 12%, one with a 7.5% discount) and its credit note CN 1 (3 of line 1's 10 returned).

Needs WeasyPrint's system libraries (run it in the backend container):

    docker compose -f infra/docker-compose.yml run --rm --no-deps backend \\
        python manage.py render_ca_samples --out ca-samples
"""

from datetime import date
from decimal import Decimal as D
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.template.loader import render_to_string

from apps.billing import documents
from apps.billing.credit_notes import line_tax
from apps.billing.models import CreditNote, CreditNoteLine, Invoice, InvoiceLine
from apps.billing.pdf import WeasyPrintRenderer
from apps.billing.tax import (
    Components,
    RoundOffMethod,
    SupplyType,
    amount_in_words,
    compute_document,
    compute_line,
    credit_for_quantity,
    credit_note_totals,
)

SELLER: dict[str, Any] = {
    "legal_name": "Sample Distributors Private Limited",
    "trade_name": "Sample Distributors",
    "gstin": "27ABCDE1234F1Z5",
    "pan": "ABCDE1234F",
    "address": "Shop 4, Market Yard Road, Gultekdi, Pune - 411037",
    "state_code": "27",
    "state": "Maharashtra",
    "phone": "+91 20 1234 5678",
    "email": "accounts@example.com",
    "bank": {
        "account_name": "Sample Distributors Private Limited",
        "account_number": "001234567890",
        "ifsc": "HDFC0000123",
        "bank_name": "HDFC Bank",
        "branch": "Market Yard, Pune",
        "upi_id": "sampledistributors@hdfcbank",
    },
    "terms": "Payment within 30 days of the invoice date.\nGoods once sold are taken back only "
    "against a credit note.",
    "footer": "Subject to Pune jurisdiction.",
    "signatory": "A. Sample",
    "signatory_image": "",
}
ADDRESS = {
    "id": "sample-address",
    "label": "Shop",
    "line1": "12, Station Road",
    "line2": "Near Bus Stand",
    "city": "Baramati",
    "district": "Pune",
    "pincode": "413102",
    "state_code": "27",
    "state": "Maharashtra",
}
BUYER: dict[str, Any] = {
    "name": "Sample Kirana Stores",
    "code": "R-00042",
    "contact": "R. Sample",
    "phone": "+91 98765 43210",
    "gstin": "27AAAPS1234A1Z5",
    "state_code": "27",
    "billing_address": ADDRESS,
    "shipping_address": ADDRESS,
}
ROUNDING = {
    "tax.component_rounding": "HALF_UP",
    "invoicing.round_to_rupee": True,
    "invoicing.round_off_method": "NEAREST",
}
INVOICE_DATE = date(2026, 9, 23)
PLACE = "Maharashtra (27)"

# CA_REVIEW Example 5: (code, description, HSN, unit, qty, unit price, rate, discount)
LINES = (
    ("TEA-250", "Assam tea 250 g", "0902", "PCS", D("10"), D("123.45"), D("18"), None),
    ("BIS-100", "Glucose biscuits 100 g", "1905", "PCS", D("24"), D("57.50"), D("5"), D("103.50")),
    ("RIC-KG", "Basmati rice (loose)", "1006", "KG", D("2.750"), D("180.00"), D("0"), None),
    ("SOA-4P", "Bath soap, pack of 4", "3401", "PCS", D("5"), D("999.99"), D("12"), None),
)


def sample_invoice() -> tuple[Invoice, list[InvoiceLine]]:
    taxes = [
        compute_line(
            qty=qty,
            unit_price=price,
            rate=rate,
            supply_type=SupplyType.INTRA,
            discount_amount=discount,
        )
        for _, _, _, _, qty, price, rate, discount in LINES
    ]
    totals = compute_document(taxes, round_to_rupee=True, round_off_method=RoundOffMethod.NEAREST)
    invoice = Invoice(
        number="INV/26-27/000123",
        fy="2026-27",
        seller=SELLER,
        buyer=BUYER,
        place_of_supply_id="27",
        supply_type="INTRA",
        settings_snapshot=ROUNDING,
        gross_total=sum((t.gross_excl for t in taxes), D("0")),
        discount_total=sum((t.discount_excl for t in taxes), D("0")),
        taxable_total=totals.taxable,
        cgst_total=totals.cgst,
        sgst_total=totals.sgst,
        igst_total=totals.igst,
        cess_total=totals.cess,
        round_off=totals.round_off,
        grand_total=totals.grand_total,
        amount_in_words=amount_in_words(totals.grand_total),
        invoice_date=INVOICE_DATE,
        due_date=date(2026, 10, 23),
        balance_due=totals.grand_total,
    )
    lines = [
        InvoiceLine(
            line_no=index,
            description=name,
            product_code=code,
            hsn_code=hsn,
            unit_code=unit,
            quantity=qty,
            unit_price=price,
            gross_amount=tax.gross_excl,
            discount_amount=tax.discount_excl,
            taxable_value=tax.taxable,
            gst_rate=rate,
            cgst_rate=tax.cgst_rate,
            cgst_amount=tax.cgst,
            sgst_rate=tax.sgst_rate,
            sgst_amount=tax.sgst,
            igst_rate=tax.igst_rate,
            igst_amount=tax.igst,
            cess_rate=D("0"),
            cess_amount=tax.cess,
            line_total=tax.line_total,
            order_rate=rate,
        )
        for index, ((code, name, hsn, unit, qty, price, rate, _), tax) in enumerate(
            zip(LINES, taxes, strict=True), 1
        )
    ]
    return invoice, lines


def sample_credit_note(invoice: Invoice, line: InvoiceLine) -> tuple[CreditNote, CreditNoteLine]:
    """CN 1: 3 of the tea line's 10 come back damaged (to stock)."""
    tax = line_tax(line)
    credit = credit_for_quantity(
        D("3"),
        invoiced_qty=line.quantity,
        remaining_qty=line.quantity,
        line=tax,
        remaining=Components.of(tax),
    )
    totals = credit_note_totals(
        [credit], round_to_rupee=True, round_off_method=RoundOffMethod.NEAREST
    )
    note = CreditNote(
        number="CN/26-27/000007",
        fy="2026-27",
        seller=SELLER,
        buyer=BUYER,
        place_of_supply_id="27",
        supply_type="INTRA",
        settings_snapshot=ROUNDING,
        gross_total=totals.taxable,
        taxable_total=totals.taxable,
        cgst_total=totals.cgst,
        sgst_total=totals.sgst,
        igst_total=totals.igst,
        cess_total=totals.cess,
        round_off=totals.round_off,
        grand_total=totals.grand_total,
        amount_in_words=amount_in_words(totals.grand_total),
        note_date=date(2026, 10, 1),
        invoice=invoice,
        kind=CreditNote.Kind.RETURN,
        return_reason=CreditNote.ReturnReason.DAMAGED,
        reason_note="Cartons crushed in transit",
    )
    note_line = CreditNoteLine(
        line_no=1,
        invoice_line=line,
        quantity=D("3"),
        disposition=CreditNoteLine.Disposition.DAMAGED,
        taxable_value=credit.taxable,
        cgst_amount=credit.cgst,
        sgst_amount=credit.sgst,
        igst_amount=credit.igst,
        cess_amount=credit.cess,
        line_total=credit.total,
    )
    return note, note_line


class Command(BaseCommand):
    help = "Print the sample invoice and credit note for the CA review (no database writes)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--out", default="ca-samples", help="Folder for the PDFs.")

    def handle(self, *args: Any, **options: Any) -> None:
        out = Path(options["out"])
        out.mkdir(parents=True, exist_ok=True)
        renderer = WeasyPrintRenderer()
        invoice, lines = sample_invoice()
        for name, copies in (
            ("sample-invoice.pdf", documents.COPIES[:1]),
            ("sample-invoice-copies.pdf", documents.COPIES),
        ):
            context = documents.invoice_context(
                invoice, copies, lines=lines, order_number="ORD-2026-000456", place=PLACE
            )
            html = render_to_string("billing/invoice.html", context)
            (out / name).write_bytes(renderer.render(html))
        note, note_line = sample_credit_note(invoice, lines[0])
        html = render_to_string(
            "billing/credit_note.html",
            documents.credit_note_context(note, lines=[note_line], place=PLACE),
        )
        (out / "sample-credit-note.pdf").write_bytes(renderer.render(html))
        self.stdout.write(
            f"Invoice {invoice.grand_total} (round-off {invoice.round_off}); "
            f"credit note {note.grand_total} (round-off {note.round_off}) -> {out}/"
        )
