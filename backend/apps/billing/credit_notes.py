"""Credit notes (PLAN §4.4, §6.5, spec 5.10, ADR-009/011/046 items 4-5).

The only way to correct an issued invoice. Kinds:
- RETURN (staff, ``invoices.manage``): lines and quantities with what happened to the goods: back
  to stock (a RETURN movement, then backorder allocation after commit), received damaged (RETURN
  then DAMAGE), or not physically returned. A reason is required.
- PRICE_ADJUSTMENT (staff): value only, with a reason.
- SHORT_SUPPLY / CANCELLATION (automatic, ⚙ invoicing.timing ON_ACCEPTANCE): goods invoiced but
  not supplied; the quantity is open again on the order (``qty_invoiced`` goes down).

Tax is prorated at the invoice line's rates; the credit that uses up a line takes the exact
remainder, and the credit note that uses up the invoice lands its balance on zero. The credit
reduces what the invoice still owes; anything beyond that is credit for the shop, used for its
next dues (oldest money first). Callers hold the shop's account (L1); the series is taken last.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import F, Sum

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing import numbering
from apps.billing.invoicing import rounding_snapshot
from apps.billing.models import CreditNote, CreditNoteLine, DocumentType, Invoice, InvoiceLine
from apps.billing.tax import (
    ComponentRounding,
    Components,
    LineTax,
    RoundOffMethod,
    amount_in_words,
    credit_for_quantity,
    credit_for_taxable,
    credit_note_totals,
)
from apps.inventory import services as stock
from apps.inventory.models import MovementType, ReferenceType
from apps.ledger import allocation
from apps.ledger import services as ledger
from apps.ledger.models import EntryType
from apps.orders.models import OrderLine
from common import outbox
from common.dates import today_ist
from common.db import retry_on_deadlock
from common.errors import InvalidFields, NotFound
from common.tenancy import require_tenant_id

ZERO = Decimal("0.00")
QTY_ZERO = Decimal("0")
Kind = CreditNote.Kind
Disposition = CreditNoteLine.Disposition


@dataclass(frozen=True)
class ReturnLine:
    invoice_line_id: UUID
    quantity: Decimal
    disposition: str = Disposition.RETURN_TO_STOCK


def line_tax(line: InvoiceLine) -> LineTax:
    """The invoice line's rates and amounts, as the tax engine's line."""
    return LineTax(
        gross=line.gross_amount,
        discount=line.discount_amount,
        gross_excl=line.gross_amount,
        discount_excl=line.discount_amount,
        taxable=line.taxable_value,
        cgst=line.cgst_amount,
        sgst=line.sgst_amount,
        igst=line.igst_amount,
        cess=line.cess_amount,
        line_total=line.line_total,
        cgst_rate=line.cgst_rate,
        sgst_rate=line.sgst_rate,
        igst_rate=line.igst_rate,
        cess_rate=line.cess_rate,
    )


def _credited(line: InvoiceLine) -> tuple[Decimal, Components]:
    """Quantity and amounts already credited on an invoice line."""
    totals = CreditNoteLine.objects.filter(invoice_line=line).aggregate(
        qty=Sum("quantity"),
        taxable=Sum("taxable_value"),
        cgst=Sum("cgst_amount"),
        sgst=Sum("sgst_amount"),
        igst=Sum("igst_amount"),
        cess=Sum("cess_amount"),
    )
    return Decimal(totals["qty"] or 0), Components(
        taxable=Decimal(totals["taxable"] or 0),
        cgst=Decimal(totals["cgst"] or 0),
        sgst=Decimal(totals["sgst"] or 0),
        igst=Decimal(totals["igst"] or 0),
        cess=Decimal(totals["cess"] or 0),
    )


@dataclass
class _Part:
    line: InvoiceLine
    quantity: Decimal
    credit: Components
    disposition: str = ""


def _issue(
    invoice: Invoice,
    kind: str,
    parts: list[_Part],
    *,
    by: User | None,
    automatic: bool = False,
    return_reason: str = "",
    reason_note: str = "",
) -> CreditNote:
    """Write the credit note, post it and apply it (the shop's account is locked)."""
    account = ledger.lock_account(invoice.retailer_id)  # L1
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)  # L5
    tenant_id = require_tenant_id()
    snapshot = rounding_snapshot(tenant_id)
    note_date = today_ist()
    # Does this credit note use up everything the invoice still has?
    exhausts = all(
        (
            _credited(line)[1].total
            + sum((p.credit.total for p in parts if p.line.pk == line.pk), ZERO)
        )
        == line.line_total
        for line in invoice.lines.all()
    )
    earlier = Decimal(
        CreditNote.objects.filter(invoice=invoice).aggregate(total=Sum("grand_total"))["total"] or 0
    )
    totals = credit_note_totals(
        [p.credit for p in parts],
        round_to_rupee=bool(snapshot["invoicing.round_to_rupee"]),
        round_off_method=RoundOffMethod(snapshot["invoicing.round_off_method"]),
        invoice_left=invoice.grand_total - earlier if exhausts else None,
    )
    if totals.grand_total <= 0:
        raise InvalidFields({"lines": ["There is nothing left to credit on this invoice."]})
    applied = min(totals.grand_total, invoice.balance_due)
    series, number = numbering.next_number(DocumentType.CREDIT_NOTE, note_date)  # L6
    note: CreditNote = CreditNote.objects.create(
        number=number,
        series=series,
        fy=series.fy,
        retailer_id=invoice.retailer_id,
        seller=invoice.seller,
        buyer=invoice.buyer,
        place_of_supply_id=invoice.place_of_supply_id,
        supply_type=invoice.supply_type,
        prices_include_tax=invoice.prices_include_tax,
        settings_snapshot=snapshot,
        gross_total=totals.taxable,
        taxable_total=totals.taxable,
        cgst_total=totals.cgst,
        sgst_total=totals.sgst,
        igst_total=totals.igst,
        cess_total=totals.cess,
        round_off=totals.round_off,
        grand_total=totals.grand_total,
        amount_in_words=amount_in_words(totals.grand_total),
        issued_by=by,
        note_date=note_date,
        invoice=invoice,
        kind=kind,
        return_reason=return_reason,
        reason_note=reason_note[:500],
        issued_automatically=automatic,
        applied_to_invoice=applied,
        unapplied_amount=totals.grand_total,
    )
    CreditNoteLine.objects.bulk_create(
        [
            CreditNoteLine(
                tenant_id=tenant_id,
                credit_note=note,
                line_no=index,
                invoice_line=p.line,
                quantity=p.quantity,
                disposition=p.disposition,
                taxable_value=p.credit.taxable,
                cgst_amount=p.credit.cgst,
                sgst_amount=p.credit.sgst,
                igst_amount=p.credit.igst,
                cess_amount=p.credit.cess,
                line_total=p.credit.total,
            )
            for index, p in enumerate(parts, 1)
        ]
    )
    ledger.post(
        account,
        EntryType.CREDIT_NOTE,
        credit=note.grand_total,
        entry_date=note_date,
        ref=ledger.Reference("CREDIT_NOTE", note.pk, number),
        narration=f"Credit note against {invoice.number}",
        by=by,
    )
    ledger.add_unapplied(account, note.grand_total)
    if applied > 0:
        allocation.apply(account, note, invoice, applied, automatic=True, by=by)
    allocation.settle(account, by=by)  # anything beyond the invoice: the shop's next dues
    from apps.compliance.einvoice import on_issued

    on_issued(note)  # the IRN, when e-invoicing is on and the shop has a GSTIN (ADR-049)
    outbox.emit(
        "credit_note.issued",
        aggregate_type="CreditNote",
        aggregate_id=note.pk,
        payload={
            "credit_note_id": str(note.pk),
            "number": number,
            "invoice_id": str(invoice.pk),
            "invoice_number": invoice.number,
            "retailer_id": str(invoice.retailer_id),
            "kind": kind,
            "issued_automatically": automatic,
            "grand_total": f"{note.grand_total:.2f}",
        },
    )
    return note


def _rounding(tenant_id: Any) -> ComponentRounding:
    return ComponentRounding(rounding_snapshot(tenant_id)["tax.component_rounding"])


def _quantity_parts(invoice: Invoice, wanted: dict[UUID, tuple[Decimal, str]]) -> list[_Part]:
    """Credit quantities of invoice lines (``wanted``: invoice line id → (qty, disposition))."""
    rounding = _rounding(require_tenant_id())
    lines = {line.pk: line for line in invoice.lines.all()}
    parts: list[_Part] = []
    for line_id, (qty, disposition) in wanted.items():
        line = lines.get(line_id)
        if line is None:
            raise InvalidFields({"lines": ["That line isn't on this invoice."]})
        done_qty, done = _credited(line)
        remaining_qty = Decimal(line.quantity) - done_qty
        if qty <= 0 or qty > remaining_qty:
            left = f"{remaining_qty.normalize():f}"
            raise InvalidFields({"lines": [f"{line.description}: at most {left} can be credited."]})
        credit = credit_for_quantity(
            qty,
            invoiced_qty=Decimal(line.quantity),
            remaining_qty=remaining_qty,
            line=line_tax(line),
            remaining=Components.of(line_tax(line)).minus(done),
            rounding=rounding,
        )
        parts.append(_Part(line, qty, credit, disposition))
    return sorted(parts, key=lambda p: p.line.line_no)


def _locked_invoice(invoice_id: UUID) -> Invoice:
    found = (
        Invoice.objects.filter(pk=invoice_id, status="ISSUED")
        .values_list("retailer_id", flat=True)
        .first()
    )
    if found is None:
        raise NotFound()
    ledger.lock_account(found)  # L1 first
    invoice: Invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    return invoice


RETURN_REASONS = set(CreditNote.ReturnReason.values)


@retry_on_deadlock()
def issue_return(
    invoice_id: UUID,
    lines: list[ReturnLine],
    *,
    reason: str,
    note: str = "",
    by: User,
) -> CreditNote:
    """Goods sent back by the shop (ADR-046 item 5)."""
    if reason not in RETURN_REASONS:
        raise InvalidFields({"reason": ["Choose why the goods came back."]})
    if reason == CreditNote.ReturnReason.OTHER and not note.strip():
        raise InvalidFields({"note": ["Say why the goods came back."]})
    if not lines:
        raise InvalidFields({"lines": ["Choose what came back."]})
    if any(line.disposition not in Disposition.values for line in lines):
        raise InvalidFields({"lines": ["Say what happened to the goods."]})
    if len({line.invoice_line_id for line in lines}) != len(lines):
        raise InvalidFields({"lines": ["List each line once."]})
    with transaction.atomic():
        invoice = _locked_invoice(invoice_id)
        parts = _quantity_parts(
            invoice, {r.invoice_line_id: (r.quantity, r.disposition) for r in lines}
        )
        moving = [p for p in parts if p.disposition != Disposition.NOT_RETURNED]
        levels = stock.lock_levels(  # L3, before the number series (L6)
            [p.line.product_id for p in moving], stock.default_warehouse()
        )
        credit_note = _issue(
            invoice, Kind.RETURN, parts, by=by, return_reason=reason, reason_note=note.strip()
        )
        _move_returned_goods(credit_note, moving, levels, by=by)
        audit.record(
            "billing.credit_note_issued",
            target=credit_note,
            target_repr=credit_note.number,
            metadata={"invoice": invoice.number, "kind": "RETURN", "reason": reason},
        )
    return credit_note


def _move_returned_goods(
    note: CreditNote, moving: list[_Part], levels: dict[UUID, Any], *, by: User
) -> None:
    """Back to stock, or back and written off; then older backorders get the returned stock."""
    if not moving:
        return
    ref = stock.Ref(ReferenceType.CREDIT_NOTE, note.pk, note.number)
    restocked = []
    for p in sorted(moving, key=lambda x: x.line.product_id):
        level = levels[p.line.product_id]
        stock.return_goods(level, p.quantity, ref, by=by, reason=f"Returned on {note.number}")
        if p.disposition == Disposition.DAMAGED:
            stock.remove(
                level,
                p.quantity,
                ref,
                by=by,
                reason=f"Received damaged on {note.number}",
                movement_type=MovementType.DAMAGE,
            )
        else:
            restocked.append(p.line.product_id)
    if restocked:
        from apps.orders import backorders

        backorders.after_stock_returned(restocked)


@retry_on_deadlock()
def issue_price_adjustment(
    invoice_id: UUID, amounts: dict[UUID, Decimal], *, note: str, by: User
) -> CreditNote:
    """A value correction (no goods move): taxable amounts per invoice line, with a reason."""
    if not note.strip():
        raise InvalidFields({"note": ["Say why the price is being corrected."]})
    if not amounts or any(v <= 0 or v != v.quantize(Decimal("0.01")) for v in amounts.values()):
        raise InvalidFields({"lines": ["Enter amounts above zero, in rupees and paise."]})
    with transaction.atomic():
        invoice = _locked_invoice(invoice_id)
        rounding = _rounding(require_tenant_id())
        lines = {line.pk: line for line in invoice.lines.all()}
        parts = []
        for line_id, taxable in amounts.items():
            line = lines.get(line_id)
            if line is None:
                raise InvalidFields({"lines": ["That line isn't on this invoice."]})
            _, done = _credited(line)
            left = Components.of(line_tax(line)).minus(done)
            if taxable > left.taxable:
                raise InvalidFields(
                    {"lines": [f"{line.description}: at most ₹{left.taxable} can be credited."]}
                )
            credit = credit_for_taxable(
                taxable, rates=line_tax(line), remaining=left, rounding=rounding
            )
            parts.append(_Part(line, QTY_ZERO, credit))
        parts.sort(key=lambda p: p.line.line_no)
        credit_note = _issue(invoice, Kind.PRICE_ADJUSTMENT, parts, by=by, reason_note=note.strip())
        audit.record(
            "billing.credit_note_issued",
            target=credit_note,
            target_repr=credit_note.number,
            metadata={"invoice": invoice.number, "kind": "PRICE_ADJUSTMENT", "note": note.strip()},
        )
    return credit_note


def credit_unsupplied(
    fulfilment_lines: dict[Any, Decimal], *, kind: str, by: User | None
) -> CreditNote | None:
    """ON_ACCEPTANCE timing (ADR-007, ADR-046 item 4): invoiced goods that won't be supplied
    (short pack, cancelled shipment or declined higher price). ``fulfilment_lines``: shipment
    line → quantity. Runs inside the caller's transaction BEFORE the quantities are released, so
    the order line's invoiced quantity goes down first. ``None`` when the shipment wasn't
    invoiced."""
    wanted = {fl: q for fl, q in fulfilment_lines.items() if q > 0}
    if not wanted:
        return None
    shipment_ids = {fl.fulfilment_id for fl in wanted}
    invoice = Invoice.objects.filter(fulfilment_id__in=shipment_ids, status="ISSUED").first()
    if invoice is None:
        return None
    by_fl = {line.fulfilment_line_id: line for line in invoice.lines.all()}
    per_line: dict[UUID, Decimal] = defaultdict(Decimal)
    for fl, qty in wanted.items():
        line = by_fl.get(fl.pk)
        if line is None:
            continue
        done_qty, _ = _credited(line)
        per_line[line.pk] += min(qty, Decimal(line.quantity) - done_qty)
    per_line = {k: v for k, v in per_line.items() if v > 0}
    if not per_line:
        return None
    parts = _quantity_parts(invoice, {k: (v, "") for k, v in per_line.items()})
    shipment = next(iter(wanted)).fulfilment
    stock.lock_levels([p.line.product_id for p in parts], shipment.warehouse)  # L3 before L6
    for p in parts:  # the quantity is open on the order again
        OrderLine.objects.filter(pk=p.line.order_line_id).update(
            qty_invoiced=F("qty_invoiced") - p.quantity
        )
    return _issue(invoice, kind, parts, by=by, automatic=True)
