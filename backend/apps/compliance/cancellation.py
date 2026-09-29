"""Cancelling an IRN (ADR-049 item 7, Phase 7 plan answer 1).

Only within the permitted window after the IRN (``platform.irn_cancel_window_hours``, to verify),
with a reason, audited; afterwards corrections are by credit note only, as before. Staff choose
what happens to the goods:

- REISSUE (the default): the invoice is cancelled and a corrected invoice is issued with a new
  number for the same shipment (it gets its own IRN);
- TAKE_BACK: the goods come back to stock, and their quantities wait on backorder again or are
  cancelled.

The portal is asked first, in the background; nothing changes here until it agrees. Then, in one
transaction: payments matched to the invoice are freed, a reversing ledger entry credits the
invoice's amount (so the cancelled invoice owes nothing), the quantities are no longer invoiced,
and the chosen outcome follows; freed money settles onto what the shop still owes (the re-issued
invoice first, being the newest dues' replacement, by the usual oldest-due order). An invoice with
credit notes can't be cancelled (correct it with another credit note). Its number is never reused.

TODO(verify): the portal's cancellation reason codes, the window, and that a cancelled number
can't be reused (PROGRESS pre-production item 13).
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing import invoicing
from apps.billing.models import CreditNote, DocumentStatus, EInvoiceStatus, Invoice, PaymentStatus
from apps.compliance import credentials, rules
from apps.compliance.adapters import get_gsp_client
from apps.compliance.adapters.base import GspError, GspErrorCode
from apps.compliance.models import CancelReason, DocumentType, EInvoiceRecord
from apps.ledger import allocation
from apps.ledger import services as ledger
from apps.ledger.models import EntryType
from apps.orders import fulfilment
from apps.orders.models import Fulfilment, OrderLine
from apps.orders.transitions import lock_order
from common import outbox
from common.dates import today_ist
from common.errors import InvalidFields, NotFound
from common.tenancy import tenant_transaction

logger = logging.getLogger(__name__)

RETRY_MINUTES = (1, 2, 4, 8)
LOST_AFTER = timedelta(minutes=2)
S = EInvoiceRecord.Status
OUTCOME = EInvoiceRecord.CancelOutcome


def window_ends(record: EInvoiceRecord) -> datetime | None:
    start = record.ack_date or record.generated_at
    return rules.cancel_window_ends(start) if start else None


def can_cancel(record: EInvoiceRecord) -> bool:
    ends = window_ends(record)
    return (
        record.document_type == DocumentType.INVOICE
        and record.status == S.GENERATED
        and ends is not None
        and timezone.now() <= ends
    )


def _check(record: EInvoiceRecord, invoice: Invoice) -> None:
    if record.document_type != DocumentType.INVOICE:
        raise InvalidFields({"document": ["Only an invoice's IRN can be cancelled here."]})
    if record.status != S.GENERATED or invoice.status != DocumentStatus.ISSUED:
        raise InvalidFields({"document": ["Only an invoice with an IRN can be cancelled."]})
    ends = window_ends(record)
    if ends is None or timezone.now() > ends:
        raise InvalidFields(
            {
                "document": [
                    "The time allowed for cancelling this IRN has passed. Correct the invoice "
                    "with a credit note instead."
                ]
            }
        )
    from apps.compliance.models import EWayBill

    live_bill = EWayBill.objects.filter(invoice=invoice, status__in=("SUBMITTED", "GENERATED"))
    if live_bill.exists():
        raise InvalidFields(
            {"document": ["This invoice has an e-way bill. Cancel the e-way bill first."]}
        )
    if CreditNote.objects.filter(invoice=invoice, status=DocumentStatus.ISSUED).exists():
        raise InvalidFields(
            {"document": ["This invoice has credit notes. Correct it with another credit note."]}
        )


def request(
    record_id: UUID,
    *,
    reason_code: str,
    remarks: str,
    outcome: str,
    to_backorder: bool,
    by: User,
) -> EInvoiceRecord:
    """Staff ask to cancel (``compliance.manage``); the portal is asked after this commits."""
    from apps.compliance.einvoice import require_module

    require_module()
    record: EInvoiceRecord | None = (
        EInvoiceRecord.objects.select_for_update().filter(pk=record_id).first()
    )
    if record is None:
        raise NotFound()
    if record.status == S.CANCELLING:
        return record
    if record.document_type != DocumentType.INVOICE or record.invoice_id is None:
        raise InvalidFields({"document": ["Only an invoice's IRN can be cancelled here."]})
    invoice = Invoice.objects.select_related("order").get(pk=record.invoice_id)
    _check(record, invoice)
    errors: dict[str, list[str]] = {}
    if reason_code not in CancelReason.values:
        errors["reason_code"] = ["Choose a reason."]
    remarks = " ".join(remarks.split())
    if reason_code == "OTHER" and not remarks:
        errors["remarks"] = ["Say why."]
    if len(remarks) > 100:
        errors["remarks"] = ["Keep it to 100 characters."]
    if outcome not in OUTCOME.values:
        errors["outcome"] = ["Choose re-issue or take the goods back."]
    backorders_on = bool(invoice.order.settings_snapshot.get("backorders.enabled", True))
    if outcome == OUTCOME.TAKE_BACK and to_backorder and not backorders_on:
        errors["to_backorder"] = ["This order doesn't take backorders: cancel the quantities."]
    if errors:
        raise InvalidFields(errors)
    record.status, record.cancel_error = S.CANCELLING, ""
    record.cancel_reason_code, record.cancel_remarks = reason_code, remarks
    record.cancel_outcome = outcome
    record.cancel_to_backorder = outcome == OUTCOME.TAKE_BACK and to_backorder
    record.cancel_requested_at, record.cancel_requested_by = timezone.now(), by
    record.attempts, record.next_retry_at = 0, None
    record.save()
    audit.record(
        "einvoice.cancel_requested",
        target=record,
        target_repr=f"IRN of {record.document_number}",
        metadata={"reason": reason_code, "remarks": remarks, "outcome": outcome},
    )
    _enqueue(record)
    return record


def _enqueue(record: EInvoiceRecord) -> None:
    from apps.compliance import tasks

    record_id, tenant_id = str(record.pk), str(record.tenant_id)
    transaction.on_commit(
        lambda: tasks.cancel_irn.apply_async(
            kwargs={"record_id": record_id, "tenant_id": tenant_id}
        )
    )


def cancel(record_id: UUID, tenant_id: UUID) -> str:
    """Ask the portal (no transaction held), then apply the cancellation here."""
    with tenant_transaction(tenant_id):
        rec = EInvoiceRecord.objects.select_for_update(skip_locked=True).filter(pk=record_id)
        record = rec.first()
        if record is None or record.status != S.CANCELLING:
            return record.status if record else "BUSY"
        if record.next_retry_at and record.next_retry_at > timezone.now():
            return "WAIT"
        try:
            given = credentials.for_use(credentials.ready())
        except credentials.NotReady:
            _refused(record, "The GST provider credentials aren't saved or working.")
            return str(S.GENERATED)
        record.attempts += 1
        record.save(update_fields=["attempts", "updated_at"])
        irn, reason, remarks = record.irn, record.cancel_reason_code, record.cancel_remarks
    try:
        result = get_gsp_client(given.provider).cancel_irn(irn, reason, remarks, given)
        cancelled_at, raw = result.cancelled_at, result.raw
    except GspError as exc:
        if exc.code != GspErrorCode.ALREADY_CANCELLED:  # already: our first answer was lost
            with tenant_transaction(tenant_id):
                record = EInvoiceRecord.objects.select_for_update().get(pk=record_id)
                if exc.retryable and record.attempts <= len(RETRY_MINUTES):
                    minutes = RETRY_MINUTES[record.attempts - 1]
                    record.next_retry_at = timezone.now() + timedelta(minutes=minutes)
                    record.cancel_error = exc.message[:500]
                    record.save(update_fields=["next_retry_at", "cancel_error", "updated_at"])
                    return "RETRY"  # ``due`` sends it again
                _refused(record, exc.message)
            return str(S.GENERATED)
        cancelled_at, raw = timezone.now(), exc.raw
    with tenant_transaction(tenant_id):
        return _apply(record_id, cancelled_at, raw)


def due() -> list[UUID]:
    """Cancellations to send now: retries that are due, and requests whose send was lost."""
    now = timezone.now()
    rows = EInvoiceRecord.objects.filter(status=S.CANCELLING).filter(
        Q(next_retry_at__lte=now)
        | Q(next_retry_at__isnull=True, cancel_requested_at__lt=now - LOST_AFTER)
    )
    return list(rows.values_list("pk", flat=True)[:100])


def _refused(record: EInvoiceRecord, message: str) -> None:
    """The portal (or our checks) said no: the invoice stays as it was, with the reason."""
    record.status, record.cancel_error, record.next_retry_at = S.GENERATED, message[:500], None
    record.save(update_fields=["status", "cancel_error", "next_retry_at", "updated_at"])
    audit.record(
        "einvoice.cancel_refused",
        target=record,
        target_repr=f"IRN of {record.document_number}",
        metadata={"error": message[:300]},
    )


def _apply(record_id: UUID, cancelled_at: datetime, raw: dict[str, Any]) -> str:
    """In one transaction, locks in the usual order: shop account and order (L1, L2), then the
    invoice, stock (L3) and the numbering (L6) for a re-issue."""
    record = EInvoiceRecord.objects.get(pk=record_id)
    invoice = Invoice.objects.get(pk=record.invoice_id)
    lock_order(invoice.order_id)
    account = ledger.lock_account(invoice.retailer_id)
    record = EInvoiceRecord.objects.select_for_update().get(pk=record_id)
    invoice = Invoice.objects.select_for_update().get(pk=record.invoice_id)
    by = record.cancel_requested_by
    note = f"Invoice {invoice.number} cancelled (IRN cancelled)"
    for row in allocation.live_allocations(invoice=invoice):
        allocation.reverse(account, row, by=by, reason=note)
    invoice.refresh_from_db()
    ledger.post(
        account,
        EntryType.INVOICE_CANCELLED,
        credit=invoice.grand_total,
        entry_date=today_ist(),
        ref=ledger.Reference("INVOICE", invoice.pk, invoice.number),
        narration=note,
        by=by,
    )
    # The cancellation credits the whole invoice: it owes nothing and drops out of the dues.
    Invoice.objects.filter(pk=invoice.pk).update(
        status=DocumentStatus.CANCELLED,
        einvoice_status=EInvoiceStatus.CANCELLED,
        amount_credited=invoice.grand_total - invoice.amount_paid,
        balance_due=0,
        payment_status=PaymentStatus.PAID,
        updated_at=timezone.now(),
    )
    for line in invoice.lines.all():
        OrderLine.objects.filter(pk=line.order_line_id).update(
            qty_invoiced=F("qty_invoiced") - line.quantity
        )
    from apps.compliance.models import EWayBill

    EWayBill.objects.filter(invoice=invoice, status="PENDING").update(  # never to be sent now
        status="FAILED",
        error_code="INVOICE_CANCELLED",
        error_message="The invoice was cancelled.",
        retryable=False,
        next_retry_at=None,
        updated_at=timezone.now(),
    )
    shipment = Fulfilment.objects.get(pk=invoice.fulfilment_id)
    reason = f"IRN of {invoice.number} cancelled"
    reissued: Invoice | None = None
    if record.cancel_outcome == EInvoiceRecord.CancelOutcome.TAKE_BACK:
        fulfilment.take_back(
            shipment.pk, to_backorder=record.cancel_to_backorder, reason=reason, by=by
        )
    else:
        reissued = invoicing.issue_invoice_for_fulfilment(
            shipment, trigger=invoice.issued_trigger, by=by
        )
    allocation.settle(account, by=by)
    record.status, record.cancelled_at, record.cancelled_by = S.CANCELLED, cancelled_at, by
    record.reissued_invoice, record.response = reissued, {**record.response, "cancel": raw}
    record.next_retry_at, record.cancel_error = None, ""
    record.save()
    outbox.emit(
        "invoice.cancelled",
        aggregate_type="Invoice",
        aggregate_id=invoice.pk,
        payload={
            "invoice_id": str(invoice.pk),
            "number": invoice.number,
            "retailer_id": str(invoice.retailer_id),
            "outcome": record.cancel_outcome,
            "reissued_invoice_id": str(reissued.pk) if reissued else None,
            "reissued_number": reissued.number if reissued else "",
        },
    )
    audit.record(
        "einvoice.cancelled",
        target=record,
        target_repr=f"IRN of {record.document_number}",
        metadata={
            "outcome": record.cancel_outcome,
            "reissued": reissued.number if reissued else "",
            "requested_by": str(by.pk) if by else "",
        },
    )
    return str(S.CANCELLED)
