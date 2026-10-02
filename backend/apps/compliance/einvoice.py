"""Getting IRNs (ADR-049 items 5 and 6).

- When a B2B invoice or credit note is issued with e-invoicing on, a record is made in the same
  transaction and the document shows "IRN pending". With ``einvoice.auto_generate`` (the default)
  it is sent after the issue commits; otherwise staff press "Get IRN".
- Sending runs in the background, never holding a transaction while the provider answers. The
  portal down or a timeout is tried again after 1, 2, 4, 8, 16, 32, 60 and 120 minutes; a refusal
  (invalid GSTIN, the document's problems, credentials) fails at once. A failed document stays
  a valid invoice, marked "IRN failed", and staff are told (``einvoice.failed``) so they can fix it
  and try again.
- A duplicate answer means the portal already has this number (e.g. its answer to us was lost):
  the IRN is fetched and recorded; a number used by a cancelled IRN fails.
- Once the IRN arrives the PDF is printed again with the IRN, acknowledgement and QR code, and the
  shop's bill message, held for it (at most ``BILL_MESSAGE_HOLD``), goes out.
- ``due()`` (every minute) picks up retries, sends whose enqueue was lost, and sends whose worker
  died (SUBMITTED for ``STUCK_AFTER``).
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing.models import CreditNote, EInvoiceStatus, Invoice
from apps.compliance import credentials, rules
from apps.compliance.adapters import get_gsp_client
from apps.compliance.adapters.base import (
    GspClient,
    GspCredentials,
    GspError,
    GspErrorCode,
    IrnResult,
)
from apps.compliance.document import credit_note_document, invoice_document, number_key
from apps.compliance.models import DocumentType, EInvoiceRecord
from apps.platform.selectors import get_setting
from common import outbox
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.tenancy import require_tenant_id, tenant_transaction

logger = logging.getLogger(__name__)

RETRY_MINUTES = (1, 2, 4, 8, 16, 32, 60, 120)
STUCK_AFTER = timedelta(minutes=10)
LOST_AFTER = timedelta(minutes=2)
BILL_MESSAGE_HOLD = timedelta(minutes=10)
S = EInvoiceRecord.Status
NOT_READY = "CREDENTIALS_NOT_READY"
NUMBER_USED = "NUMBER_USED"


def _model(document_type: str) -> type[Invoice] | type[CreditNote]:
    return Invoice if document_type == DocumentType.INVOICE else CreditNote


def document_of(record: EInvoiceRecord) -> Invoice | CreditNote:
    doc: Invoice | CreditNote
    if record.document_type == DocumentType.INVOICE:
        doc = Invoice.objects.get(pk=record.invoice_id)
    else:
        doc = CreditNote.objects.get(pk=record.credit_note_id)
    return doc


def _set_document(record: EInvoiceRecord, **fields: Any) -> None:
    doc_id = record.invoice_id or record.credit_note_id
    _model(record.document_type).objects.filter(pk=doc_id).update(**fields)


def _enqueue(record: EInvoiceRecord) -> None:
    from apps.compliance import tasks

    record_id, tenant_id = str(record.pk), str(record.tenant_id)
    transaction.on_commit(
        lambda: tasks.generate_irn.apply_async(
            kwargs={"record_id": record_id, "tenant_id": tenant_id}
        )
    )


# --- Issue and request ---------------------------------------------------------------------------


def on_issued(document: Invoice | CreditNote) -> EInvoiceRecord | None:
    """In the issuing transaction: start the document's IRN when it needs one."""
    if not rules.needs_irn(document):
        return None
    auto = bool(get_setting("einvoice.auto_generate", document.tenant_id))
    is_invoice = isinstance(document, Invoice)
    record: EInvoiceRecord = EInvoiceRecord.objects.create(
        document_type=DocumentType.INVOICE if is_invoice else DocumentType.CREDIT_NOTE,
        invoice=document if is_invoice else None,
        credit_note=None if is_invoice else document,
        document_number=document.number,
        document_number_key=number_key(document.number),
        requested_at=timezone.now() if auto else None,
    )
    type(document).objects.filter(pk=document.pk).update(einvoice_status=EInvoiceStatus.PENDING)
    document.einvoice_status = EInvoiceStatus.PENDING
    if auto:
        _enqueue(record)
    return record


def require_module() -> None:
    if not rules.einvoicing_on(require_tenant_id()):
        raise DomainError(
            _("E-invoicing isn't switched on for your business."),
            code=ErrorCode.MODULE_NOT_ENABLED,
            status_code=403,
        )


def request(document_type: str, document_id: UUID, *, by: User) -> EInvoiceRecord:
    """Staff ask for the IRN ("Get IRN", or "Try again" after a failure). Audited."""
    require_module()
    doc = _model(document_type).objects.select_for_update().filter(pk=document_id).first()
    if doc is None:
        raise NotFound()
    if not doc.buyer.get("gstin"):
        raise InvalidFields({"document": [_("Only bills to shops with a GSTIN get an IRN.")]})
    field = "invoice" if document_type == DocumentType.INVOICE else "credit_note"
    record: EInvoiceRecord | None = (
        EInvoiceRecord.objects.select_for_update().filter(**{field: doc}).first()
    )
    if record is None:  # issued before e-invoicing was switched on
        record = EInvoiceRecord(
            document_type=document_type,
            document_number=doc.number,
            document_number_key=number_key(doc.number),
            **{field: doc},
        )
    elif record.status in (S.GENERATED, S.CANCELLED):
        return record
    elif record.status == S.SUBMITTED and record.updated_at > timezone.now() - STUCK_AFTER:
        return record  # being sent right now
    record.status, record.attempts, record.next_retry_at = S.PENDING, 0, None
    record.error_code, record.error_message, record.retryable = "", "", False
    record.requested_at = timezone.now()
    record.save()
    _set_document(record, einvoice_status=EInvoiceStatus.PENDING)
    audit.record(
        "einvoice.requested", target=record, target_repr=f"IRN for {record.document_number}"
    )
    _enqueue(record)
    return record


def waiting_for_irn(document_kind: str, object_id: UUID) -> bool:
    """Is an IRN being fetched for this document right now (so its bill message waits)?"""
    field = "invoice_id" if document_kind == "INVOICE" else "credit_note_id"
    return EInvoiceRecord.objects.filter(
        **{field: object_id},
        status__in=(S.PENDING, S.SUBMITTED),
        requested_at__isnull=False,
    ).exists()


# --- Sending (background; no transaction held while the provider answers) -----------------------


def generate(record_id: UUID, tenant_id: UUID) -> str:
    now = timezone.now()
    with tenant_transaction(tenant_id):
        record = EInvoiceRecord.objects.select_for_update(skip_locked=True).filter(pk=record_id)
        rec = record.first()
        if rec is None:
            return "BUSY"  # another worker has it
        stuck = rec.status == S.SUBMITTED and rec.updated_at < now - STUCK_AFTER
        due = rec.status == S.PENDING and rec.requested_at is not None
        if not stuck and not (due and (rec.next_retry_at is None or rec.next_retry_at <= now)):
            return str(rec.status)
        try:
            given = credentials.for_use(credentials.ready())
        except credentials.NotReady:
            _fail(
                rec,
                NOT_READY,
                "The GST provider credentials aren't saved or working. Check them in Settings, "
                "then try again.",
                retryable=True,
            )
            return str(S.FAILED)
        doc = document_of(rec)
        body = invoice_document(doc) if isinstance(doc, Invoice) else credit_note_document(doc)
        rec.request_document, rec.status = body, S.SUBMITTED
        rec.attempts += 1
        rec.save()
    client = get_gsp_client(given.provider)
    try:
        result = client.generate_irn(body, given)
    except GspError as exc:
        if exc.code != GspErrorCode.DUPLICATE:
            return _after_error(record_id, tenant_id, exc)
        return _after_duplicate(record_id, tenant_id, client, body, given, exc)
    except Exception:  # an adapter bug: logged, tried again like the portal being down
        logger.exception("GSP adapter failed", extra={"record_id": str(record_id)})
        error = GspError(GspErrorCode.PORTAL_DOWN, "The GST provider could not be reached.")
        return _after_error(record_id, tenant_id, error)
    return _generated(record_id, tenant_id, result)


def _after_duplicate(
    record_id: UUID,
    tenant_id: UUID,
    client: GspClient,
    body: dict[str, Any],
    given: GspCredentials,
    exc: GspError,
) -> str:
    try:
        found = client.irn_for_document(body, given)
    except GspError as lookup:
        return _after_error(record_id, tenant_id, lookup)
    if found is not None:
        return _generated(record_id, tenant_id, found)
    used = GspError(
        NUMBER_USED,
        "This number was already used for an IRN that has been cancelled; it can't be used again.",
        raw=exc.raw,
    )
    return _after_error(record_id, tenant_id, used)


def _generated(record_id: UUID, tenant_id: UUID, result: IrnResult) -> str:
    from apps.billing.tasks import render_document

    with tenant_transaction(tenant_id):
        rec = EInvoiceRecord.objects.select_for_update().get(pk=record_id)
        rec.status, rec.generated_at = S.GENERATED, timezone.now()
        rec.irn, rec.ack_no, rec.ack_date = result.irn, result.ack_no, result.ack_date
        rec.signed_invoice, rec.signed_qr = result.signed_invoice, result.signed_qr
        rec.response, rec.next_retry_at = result.raw, None
        rec.error_code, rec.error_message, rec.retryable = "", "", False
        rec.save()
        _set_document(
            rec,
            einvoice_status=EInvoiceStatus.GENERATED,
            irn=result.irn,
            ack_no=result.ack_no,
            ack_date=result.ack_date,
            signed_qr=result.signed_qr,
        )
        kind = "invoice" if rec.document_type == DocumentType.INVOICE else "credit_note"
        doc_id = str(rec.invoice_id or rec.credit_note_id)
        transaction.on_commit(
            lambda: render_document.apply_async(
                kwargs={"kind": kind, "object_id": doc_id, "tenant_id": str(tenant_id)}
            )
        )
        _release_bill_message(rec)
    return str(S.GENERATED)


def _after_error(record_id: UUID, tenant_id: UUID, exc: GspError) -> str:
    with tenant_transaction(tenant_id):
        rec = EInvoiceRecord.objects.select_for_update().get(pk=record_id)
        rec.response = exc.raw or {"error": exc.code}
        if exc.retryable and rec.attempts <= len(RETRY_MINUTES):
            rec.status = S.PENDING
            rec.next_retry_at = timezone.now() + timedelta(minutes=RETRY_MINUTES[rec.attempts - 1])
            rec.error_code, rec.error_message, rec.retryable = exc.code, exc.message[:500], True
            rec.save()
            return "RETRY"
        _fail(rec, exc.code, exc.message, retryable=exc.retryable, details=exc.details)
    return str(S.FAILED)


def _fail(
    rec: EInvoiceRecord,
    code: str,
    message: str,
    *,
    retryable: bool,
    details: dict[str, Any] | None = None,
) -> None:
    """In the caller's transaction: FAILED, the document marked, staff told, the bill message
    released (it goes without an IRN)."""
    rec.status, rec.next_retry_at = S.FAILED, None
    rec.error_code, rec.error_message, rec.retryable = code, message[:500], retryable
    rec.save()
    _set_document(rec, einvoice_status=EInvoiceStatus.FAILED)
    doc = document_of(rec)
    outbox.emit(
        "einvoice.failed",
        aggregate_type="EInvoiceRecord",
        aggregate_id=rec.pk,
        payload={
            "record_id": str(rec.pk),
            "document_type": rec.document_type,
            "document_id": str(doc.pk),
            "document_number": rec.document_number,
            "retailer_id": str(doc.retailer_id),
            "error_code": code,
            "error": message[:300],
            "details": details or {},
        },
    )
    _release_bill_message(rec)


def _release_bill_message(rec: EInvoiceRecord) -> None:
    from apps.notifications.delivery import release_held_for_irn

    kind = "INVOICE" if rec.document_type == DocumentType.INVOICE else "CREDIT_NOTE"
    object_id = rec.invoice_id or rec.credit_note_id
    if object_id is not None:
        release_held_for_irn(kind, object_id)


def due() -> list[UUID]:
    """What the every-minute sweep sends now for the active tenant."""
    now = timezone.now()
    ready = Q(status=S.PENDING, requested_at__isnull=False) & (
        Q(next_retry_at__lte=now) | Q(next_retry_at__isnull=True, requested_at__lt=now - LOST_AFTER)
    )
    stuck = Q(status=S.SUBMITTED, updated_at__lt=now - STUCK_AFTER)
    rows = EInvoiceRecord.objects.filter(ready | stuck).order_by("requested_at")
    return list(rows.values_list("pk", flat=True)[:100])


def hold_until(document_kind: str, object_id: UUID, now: datetime) -> datetime | None:
    """How long the shop's bill message waits for the IRN (ADR-049 item 6)."""
    return now + BILL_MESSAGE_HOLD if waiting_for_irn(document_kind, object_id) else None
