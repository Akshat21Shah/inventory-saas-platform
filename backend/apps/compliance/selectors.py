"""Reads for the e-invoice screens (ADR-049): the list with the portal's reasons, the reporting-
limit warning, and each document's summary for its own page."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import Q, QuerySet

from apps.billing.models import CreditNote, Invoice
from apps.compliance import rules
from apps.compliance.models import DocumentType, EInvoiceRecord
from common.dates import today_ist
from common.tenancy import require_tenant_id

S = EInvoiceRecord.Status
OPEN = (S.PENDING, S.SUBMITTED, S.FAILED)


@dataclass(frozen=True)
class Filters:
    status: str = ""
    document_type: str = ""
    search: str = ""


def einvoice_list(filters: Filters) -> QuerySet[EInvoiceRecord]:
    rows = EInvoiceRecord.objects.select_related(
        "invoice__retailer", "credit_note__retailer", "credit_note__invoice", "reissued_invoice"
    )
    if filters.status:
        rows = rows.filter(status=filters.status)
    if filters.document_type:
        rows = rows.filter(document_type=filters.document_type)
    if filters.search.strip():
        term = filters.search.strip()
        rows = rows.filter(
            Q(document_number_key__contains=term.upper())
            | Q(invoice__retailer__shop_name__icontains=term)
            | Q(credit_note__retailer__shop_name__icontains=term)
            | Q(irn__iexact=term)
        )
    return rows


def document_date(record: EInvoiceRecord) -> date:
    if record.document_type == DocumentType.INVOICE and record.invoice is not None:
        return record.invoice.invoice_date
    assert record.credit_note is not None
    return record.credit_note.note_date


def report_by(record: EInvoiceRecord) -> date | None:
    """The last day for the IRN while it is still missing, when the reporting limit applies."""
    if record.status not in OPEN:
        return None
    return rules.report_by(record.tenant_id, document_date(record))


def summary(record: EInvoiceRecord) -> dict[str, Any]:
    from apps.compliance.cancellation import can_cancel, window_ends

    last_day = report_by(record)
    reissued = record.reissued_invoice
    return {
        "id": record.pk,
        "status": record.status,
        "irn": record.irn,
        "ack_no": record.ack_no,
        "ack_date": record.ack_date,
        "error_code": record.error_code,
        "error_message": record.error_message,
        "retryable": record.retryable,
        "attempts": record.attempts,
        "requested_at": record.requested_at,
        "next_retry_at": record.next_retry_at,
        "generated_at": record.generated_at,
        "report_by": last_day,
        "past_report_by": bool(last_day and last_day < today_ist()),
        # "Get IRN" while waiting for staff, "Try again" after a failure
        "can_request": record.status == S.FAILED
        or (record.status == S.PENDING and record.requested_at is None),
        "can_cancel": can_cancel(record),
        "cancel_until": window_ends(record) if record.document_type == "INVOICE" else None,
        "cancel_reason_code": record.cancel_reason_code,
        "cancel_remarks": record.cancel_remarks,
        "cancel_outcome": record.cancel_outcome,
        "cancel_error": record.cancel_error,
        "cancelled_at": record.cancelled_at,
        "reissued_invoice": (
            {"id": reissued.pk, "number": reissued.number} if reissued is not None else None
        ),
    }


def row(record: EInvoiceRecord) -> dict[str, Any]:
    """A list row: the summary with its document and shop."""
    doc: Invoice | CreditNote | None = record.invoice or record.credit_note
    assert doc is not None
    invoice_id = doc.pk if isinstance(doc, Invoice) else doc.invoice_id
    return {
        **summary(record),
        "document_type": record.document_type,
        "document_id": doc.pk,
        "document_number": record.document_number,
        "document_date": document_date(record),
        "shop_name": doc.retailer.shop_name,
        "retailer_id": doc.retailer_id,
        "grand_total": doc.grand_total,
        "invoice_id": invoice_id,
    }


def summary_for(document: Invoice | CreditNote) -> dict[str, Any] | None:
    field = "invoice" if isinstance(document, Invoice) else "credit_note"
    record = EInvoiceRecord.objects.filter(**{field: document}).first()
    return summary(record) if record is not None else None


def counts() -> dict[str, int]:
    tenant_id = require_tenant_id()
    rows = EInvoiceRecord.objects.filter(tenant_id=tenant_id)
    open_rows = list(rows.filter(status__in=OPEN).select_related("invoice", "credit_note"))
    soon = [r for r in open_rows if (day := report_by(r)) and (day - today_ist()).days <= 3]
    return {
        "pending": sum(1 for r in open_rows if r.status in (S.PENDING, S.SUBMITTED)),
        "failed": sum(1 for r in open_rows if r.status == S.FAILED),
        "near_report_by": len(soon),
    }
