"""E-way bills (ADR-049 item 8, Phase 7 plan answer 4).

- Needed when the invoice (with tax) is worth more than the threshold: one for goods going to
  another state, one within the state (⚙ ``ewaybill.threshold_*``, placeholder ₹50,000 until
  verified). Shops with or without a GSTIN alike (to verify).
- Made at dispatch, from the shipment's transport details and distance (the shop address's
  distance, editable at dispatch), in the background: dispatch never waits. With
  ``ewaybill.auto_generate`` off, staff press "Make e-way bill".
- Retried like IRNs when the portal is down; a refusal (a missing distance or vehicle) fails at
  once, shown with "Try again" (with corrected details).
- Afterwards: a new vehicle (Part-B) and cancellation within the window (⚙ platform, to verify),
  audited, each asked of the portal in the background and kept as an ``EWayBillUpdate``.
- The invoice's PDF shows the e-way bill number and validity once generated.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing.models import DocumentStatus, Invoice
from apps.compliance import credentials
from apps.compliance.adapters import get_gsp_client
from apps.compliance.adapters.base import EwbResult, GspError, GspErrorCode
from apps.compliance.document import ewaybill_document
from apps.compliance.ewaybill_reasons import CANCEL_REASONS, PART_B_REASONS
from apps.compliance.models import EWayBill, EWayBillUpdate
from apps.orders.models import Fulfilment
from apps.platform.selectors import get_platform_setting, get_setting, is_feature_enabled
from common import outbox
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.tenancy import require_tenant_id, tenant_transaction

logger = logging.getLogger(__name__)

RETRY_MINUTES = (1, 2, 4, 8, 16, 32, 60, 120)
STUCK_AFTER = timedelta(minutes=10)
LOST_AFTER = timedelta(minutes=2)
S = EWayBill.Status
U = EWayBillUpdate.Status
LIVE = (S.PENDING, S.SUBMITTED, S.GENERATED)


@dataclass(frozen=True)
class TransportInput:
    mode: str = EWayBill.Mode.ROAD
    vehicle_number: str = ""
    transporter_id: str = ""
    transporter_name: str = ""
    doc_no: str = ""
    doc_date: date | None = None
    distance_km: int | None = None


def module_on(tenant_id: UUID) -> bool:
    return is_feature_enabled("ewaybill", tenant_id)


def require_module() -> None:
    if not module_on(require_tenant_id()):
        raise DomainError(
            _("E-way bills aren't switched on for your business."),
            code=ErrorCode.MODULE_NOT_ENABLED,
            status_code=403,
        )


def threshold(invoice: Invoice) -> Decimal:
    key = "inter_state" if invoice.supply_type == "INTER" else "intra_state"
    return Decimal(get_setting(f"ewaybill.threshold_{key}", invoice.tenant_id))


def needs_ewaybill(invoice: Invoice) -> bool:
    """TODO(verify): the consignment value (taken as the invoice total with tax) and the
    thresholds (PROGRESS pre-production item 19)."""
    return module_on(invoice.tenant_id) and invoice.grand_total > threshold(invoice)


def live_for(invoice: Invoice) -> EWayBill | None:
    found: EWayBill | None = EWayBill.objects.filter(invoice=invoice, status__in=LIVE).first()
    return found


def address_distance(shipment: Fulfilment) -> int | None:
    """The distance saved on the shop address the order goes to."""
    from apps.retailers.models import RetailerAddress

    address_id = (shipment.order.shipping_address or {}).get("id")
    if not address_id:
        return None
    found = RetailerAddress.objects.filter(pk=address_id).values_list("distance_km", flat=True)
    return found.first()


def _enqueue(ewb: EWayBill) -> None:
    from apps.compliance import tasks

    ewb_id, tenant_id = str(ewb.pk), str(ewb.tenant_id)
    transaction.on_commit(
        lambda: tasks.generate_ewaybill.apply_async(
            kwargs={"ewaybill_id": ewb_id, "tenant_id": tenant_id}
        )
    )


def _apply_transport(ewb: EWayBill, transport: TransportInput) -> None:
    ewb.transport_mode = transport.mode
    ewb.vehicle_number = "".join(transport.vehicle_number.upper().split())[:20]
    ewb.transporter_id = transport.transporter_id.strip().upper()[:15]
    ewb.transporter_name = transport.transporter_name.strip()[:120]
    ewb.transport_doc_no = transport.doc_no.strip()[:40]
    ewb.transport_doc_date = transport.doc_date
    ewb.distance_km = transport.distance_km


# --- At dispatch ----------------------------------------------------------------------------------


def on_dispatched(shipment: Fulfilment, *, by: User | None = None) -> EWayBill | None:
    """In the dispatch transaction, after the invoice: the e-way bill when the invoice needs one."""
    invoice = Invoice.objects.filter(fulfilment=shipment, status=DocumentStatus.ISSUED).first()
    if invoice is None or not needs_ewaybill(invoice) or live_for(invoice) is not None:
        return None
    auto = bool(get_setting("ewaybill.auto_generate", shipment.tenant_id))
    ewb = EWayBill(
        invoice=invoice,
        fulfilment=shipment,
        consignment_value=invoice.grand_total,
        requested_at=timezone.now() if auto else None,
        created_by=by,  # told if it fails
    )
    _apply_transport(
        ewb,
        TransportInput(
            vehicle_number=shipment.vehicle_number,
            transporter_name=shipment.transporter_name,
            doc_no=shipment.lr_number,
            doc_date=timezone.localdate() if shipment.lr_number else None,
            distance_km=shipment.distance_km,
        ),
    )
    ewb.save()
    if auto:
        _enqueue(ewb)
    return ewb


def request(invoice_id: UUID, transport: TransportInput, *, by: User) -> EWayBill:
    """Staff make the e-way bill ("Make e-way bill", or "Try again" with corrected details).
    Allowed below the threshold too (a distributor may want one). Audited."""
    require_module()
    invoice = Invoice.objects.select_for_update().filter(pk=invoice_id).first()
    if invoice is None:
        raise NotFound()
    if invoice.status != DocumentStatus.ISSUED:
        raise InvalidFields({"invoice": [_("This invoice is cancelled.")]})
    if transport.mode not in EWayBill.Mode.values:
        raise InvalidFields({"transport_mode": [_("Choose road, rail, air or ship.")]})
    ewb: EWayBill | None = (
        EWayBill.objects.select_for_update().filter(invoice=invoice, status__in=LIVE).first()
    )
    if ewb is not None and ewb.status == S.GENERATED:
        raise InvalidFields({"invoice": [_("This invoice already has an e-way bill.")]})
    if ewb is not None and ewb.status == S.SUBMITTED:
        return ewb  # being made right now
    if ewb is None:  # "Try again": the failed one, with the corrected details
        ewb = (
            EWayBill.objects.select_for_update()
            .filter(invoice=invoice, status=S.FAILED)
            .order_by("-created_at")
            .first()
        )
    if ewb is None:
        ewb = EWayBill(
            invoice=invoice,
            fulfilment_id=invoice.fulfilment_id,
            consignment_value=invoice.grand_total,
            created_by=by,
        )
    _apply_transport(ewb, transport)
    ewb.status, ewb.attempts, ewb.next_retry_at = S.PENDING, 0, None
    ewb.error_code, ewb.error_message, ewb.retryable = "", "", False
    ewb.requested_at = timezone.now()
    ewb.save()
    audit.record("ewaybill.requested", target=ewb, target_repr=f"E-way bill for {invoice.number}")
    _enqueue(ewb)
    return ewb


# --- Generating (background) ----------------------------------------------------------------------


def generate(ewb_id: UUID, tenant_id: UUID) -> str:
    now = timezone.now()
    with tenant_transaction(tenant_id):
        ewb = EWayBill.objects.select_for_update(skip_locked=True).filter(pk=ewb_id).first()
        if ewb is None:
            return "BUSY"
        stuck = ewb.status == S.SUBMITTED and ewb.updated_at < now - STUCK_AFTER
        due = ewb.status == S.PENDING and ewb.requested_at is not None
        if not stuck and not (due and (ewb.next_retry_at is None or ewb.next_retry_at <= now)):
            return str(ewb.status)
        try:
            given = credentials.for_use(credentials.ready())
        except credentials.NotReady:
            _failed(
                ewb,
                "CREDENTIALS_NOT_READY",
                "The GST provider credentials aren't saved or "
                "working. Check them in Settings, then try again.",
                retryable=True,
            )
            return str(S.FAILED)
        ewb = EWayBill.objects.select_related("invoice").get(pk=ewb.pk)
        body = ewaybill_document(ewb)
        ewb.request_document, ewb.status = body, S.SUBMITTED
        ewb.attempts += 1
        ewb.save()
    client = get_gsp_client(given.provider)
    try:
        result = client.generate_ewb(body, given)
    except GspError as exc:
        if exc.code != GspErrorCode.DUPLICATE:
            return _after_error(ewb_id, tenant_id, exc)
        try:
            found = client.ewb_for_document(body, given)
        except GspError as lookup:
            return _after_error(ewb_id, tenant_id, lookup)
        if found is None:
            return _after_error(ewb_id, tenant_id, exc)
        result = found
    except Exception:  # an adapter bug: logged, tried again like the portal being down
        logger.exception("GSP adapter failed", extra={"ewaybill_id": str(ewb_id)})
        error = GspError(GspErrorCode.PORTAL_DOWN, "The GST provider could not be reached.")
        return _after_error(ewb_id, tenant_id, error)
    return _generated(ewb_id, tenant_id, result)


def _generated(ewb_id: UUID, tenant_id: UUID, result: EwbResult) -> str:
    from apps.billing.tasks import render_document

    with tenant_transaction(tenant_id):
        ewb = EWayBill.objects.select_for_update().get(pk=ewb_id)
        ewb.status, ewb.generated_at = S.GENERATED, timezone.now()
        ewb.ewb_number, ewb.ewb_date, ewb.valid_until = (
            result.ewb_number,
            result.ewb_date,
            result.valid_until,
        )
        ewb.response, ewb.next_retry_at = result.raw, None
        ewb.error_code, ewb.error_message, ewb.retryable = "", "", False
        ewb.save()
        invoice_id = str(ewb.invoice_id)
        transaction.on_commit(  # printed again with the e-way bill number
            lambda: render_document.apply_async(
                kwargs={"kind": "invoice", "object_id": invoice_id, "tenant_id": str(tenant_id)}
            )
        )
    return str(S.GENERATED)


def _after_error(ewb_id: UUID, tenant_id: UUID, exc: GspError) -> str:
    with tenant_transaction(tenant_id):
        ewb = EWayBill.objects.select_for_update().get(pk=ewb_id)
        ewb.response = exc.raw or {"error": exc.code}
        if exc.retryable and ewb.attempts <= len(RETRY_MINUTES):
            ewb.status = S.PENDING
            ewb.next_retry_at = timezone.now() + timedelta(minutes=RETRY_MINUTES[ewb.attempts - 1])
            ewb.error_code, ewb.error_message, ewb.retryable = exc.code, exc.message[:500], True
            ewb.save()
            return "RETRY"
        _failed(ewb, exc.code, exc.message, retryable=exc.retryable)
    return str(S.FAILED)


def _failed(ewb: EWayBill, code: str, message: str, *, retryable: bool) -> None:
    """FAILED, and staff told at once (Phase 7 backend checkpoint, change 4): those who manage
    compliance and whoever dispatched the shipment, in the app and by email."""
    ewb.status, ewb.next_retry_at = S.FAILED, None
    ewb.error_code, ewb.error_message, ewb.retryable = code, message[:500], retryable
    ewb.save()
    shipment = Fulfilment.objects.get(pk=ewb.fulfilment_id)
    invoice = Invoice.objects.get(pk=ewb.invoice_id)
    outbox.emit(
        "ewaybill.failed",
        aggregate_type="EWayBill",
        aggregate_id=ewb.pk,
        payload={
            "ewaybill_id": str(ewb.pk),
            "invoice_id": str(invoice.pk),
            "invoice_number": invoice.number,
            "shipment_number": shipment.number,
            "vehicle_number": ewb.vehicle_number,
            "retailer_id": str(invoice.retailer_id),
            "dispatcher_id": str(ewb.created_by_id or ""),
            "error_code": code,
            "error": message[:300],
        },
    )


# --- Part-B and cancellation ----------------------------------------------------------------------


def _generated_bill(ewb_id: UUID) -> EWayBill:
    require_module()
    ewb: EWayBill | None = EWayBill.objects.select_for_update().filter(pk=ewb_id).first()
    if ewb is None:
        raise NotFound()
    if ewb.status != S.GENERATED:
        raise InvalidFields({"ewaybill": [_("Only a generated e-way bill can be changed.")]})
    if EWayBillUpdate.objects.filter(eway_bill=ewb, status=U.PENDING).exists():
        raise InvalidFields({"ewaybill": [_("A change to this e-way bill is being sent.")]})
    return ewb


def cancel_window_ends(ewb: EWayBill) -> Any:
    if ewb.ewb_date is None:
        return None
    hours = int(get_platform_setting("platform.ewaybill_cancel_window_hours"))
    return ewb.ewb_date + timedelta(hours=hours)


def request_part_b(
    ewb_id: UUID, *, vehicle_number: str, doc_no: str, reason_code: str, remarks: str, by: User
) -> EWayBillUpdate:
    ewb = _generated_bill(ewb_id)
    errors: dict[str, list[str]] = {}
    vehicle = "".join(vehicle_number.upper().split())[:20]
    if not vehicle:
        errors["vehicle_number"] = [_("Enter the vehicle number.")]
    if reason_code not in PART_B_REASONS:
        errors["reason_code"] = [_("Choose a reason.")]
    if reason_code == "OTHER" and not remarks.strip():
        errors["remarks"] = [_("Say why.")]
    if ewb.valid_until is not None and timezone.now() > ewb.valid_until:
        errors["ewaybill"] = [_("This e-way bill has expired.")]
    if errors:
        raise InvalidFields(errors)
    update: EWayBillUpdate = EWayBillUpdate.objects.create(
        eway_bill=ewb,
        kind=EWayBillUpdate.Kind.PART_B,
        vehicle_number=vehicle,
        transport_doc_no=doc_no.strip()[:40],
        reason_code=reason_code,
        remarks=" ".join(remarks.split())[:100],
        created_by=by,
    )
    audit.record(
        "ewaybill.vehicle_change_requested",
        target=ewb,
        target_repr=f"E-way bill {ewb.ewb_number}",
        changes={"vehicle_number": [ewb.vehicle_number, vehicle]},
    )
    _enqueue_update(update)
    return update


def request_cancel(ewb_id: UUID, *, reason_code: str, remarks: str, by: User) -> EWayBillUpdate:
    ewb = _generated_bill(ewb_id)
    errors: dict[str, list[str]] = {}
    if reason_code not in CANCEL_REASONS:
        errors["reason_code"] = [_("Choose a reason.")]
    if reason_code == "OTHER" and not remarks.strip():
        errors["remarks"] = [_("Say why.")]
    ends = cancel_window_ends(ewb)
    if ends is None or timezone.now() > ends:
        errors["ewaybill"] = [_("The time allowed for cancelling this e-way bill has passed.")]
    if errors:
        raise InvalidFields(errors)
    update: EWayBillUpdate = EWayBillUpdate.objects.create(
        eway_bill=ewb,
        kind=EWayBillUpdate.Kind.CANCEL,
        reason_code=reason_code,
        remarks=" ".join(remarks.split())[:100],
        created_by=by,
    )
    audit.record(
        "ewaybill.cancel_requested",
        target=ewb,
        target_repr=f"E-way bill {ewb.ewb_number}",
        metadata={"reason": reason_code, "remarks": update.remarks},
    )
    _enqueue_update(update)
    return update


def _enqueue_update(update: EWayBillUpdate) -> None:
    from apps.compliance import tasks

    update_id, tenant_id = str(update.pk), str(update.tenant_id)
    transaction.on_commit(
        lambda: tasks.send_ewaybill_update.apply_async(
            kwargs={"update_id": update_id, "tenant_id": tenant_id}
        )
    )


def send_update(update_id: UUID, tenant_id: UUID) -> str:
    now = timezone.now()
    with tenant_transaction(tenant_id):
        rows = EWayBillUpdate.objects.select_for_update(skip_locked=True).select_related(
            "eway_bill"
        )
        update = rows.filter(pk=update_id).first()
        if update is None or update.status != U.PENDING:
            return update.status if update else "BUSY"
        if update.next_retry_at and update.next_retry_at > now:
            return "WAIT"
        try:
            given = credentials.for_use(credentials.ready())
        except credentials.NotReady:
            _update_failed(update, "The GST provider credentials aren't saved or working.")
            return str(U.FAILED)
        update.attempts += 1
        update.save(update_fields=["attempts", "updated_at"])
        number, kind = update.eway_bill.ewb_number, update.kind
        vehicle, reason, remarks = update.vehicle_number, update.reason_code, update.remarks
    client = get_gsp_client(given.provider)
    try:
        if kind == EWayBillUpdate.Kind.PART_B:
            part_b = client.update_part_b(number, vehicle, reason, remarks, given)
            raw, valid_until = part_b.raw, part_b.valid_until
        else:
            cancelled = client.cancel_ewb(number, reason, remarks, given)
            raw, valid_until = cancelled.raw, None
    except GspError as exc:
        if not (kind == EWayBillUpdate.Kind.CANCEL and exc.code == GspErrorCode.ALREADY_CANCELLED):
            with tenant_transaction(tenant_id):
                update = EWayBillUpdate.objects.select_for_update().get(pk=update_id)
                if exc.retryable and update.attempts <= len(RETRY_MINUTES[:4]):
                    minutes = RETRY_MINUTES[update.attempts - 1]
                    update.next_retry_at = timezone.now() + timedelta(minutes=minutes)
                    update.error_message = exc.message[:500]
                    update.save(update_fields=["next_retry_at", "error_message", "updated_at"])
                    return "RETRY"
                _update_failed(update, exc.message)
            return str(U.FAILED)
        raw, valid_until = exc.raw, None  # cancelled already: our first answer was lost
    with tenant_transaction(tenant_id):
        update = EWayBillUpdate.objects.select_for_update().get(pk=update_id)
        ewb = EWayBill.objects.select_for_update().get(pk=update.eway_bill_id)
        update.status, update.done_at, update.response = U.DONE, timezone.now(), raw
        update.error_message, update.next_retry_at = "", None
        update.save()
        if kind == EWayBillUpdate.Kind.PART_B:
            ewb.vehicle_number = update.vehicle_number
            if update.transport_doc_no:
                ewb.transport_doc_no = update.transport_doc_no
            ewb.valid_until = valid_until or ewb.valid_until
        else:
            ewb.status, ewb.cancelled_at = S.CANCELLED, timezone.now()
        ewb.save()
        audit.record(
            "ewaybill.vehicle_changed"
            if kind == EWayBillUpdate.Kind.PART_B
            else "ewaybill.cancelled",
            target=ewb,
            target_repr=f"E-way bill {ewb.ewb_number}",
        )
        invoice_id = str(ewb.invoice_id)
        from apps.billing.tasks import render_document

        transaction.on_commit(
            lambda: render_document.apply_async(
                kwargs={"kind": "invoice", "object_id": invoice_id, "tenant_id": str(tenant_id)}
            )
        )
    return str(U.DONE)


def _update_failed(update: EWayBillUpdate, message: str) -> None:
    update.status, update.error_message, update.next_retry_at = U.FAILED, message[:500], None
    update.save(update_fields=["status", "error_message", "next_retry_at", "updated_at"])


# --- The every-minute sweep -----------------------------------------------------------------------


def due() -> tuple[list[UUID], list[UUID]]:
    """E-way bills to generate now (retries, lost sends, dead workers) and updates to send."""
    now = timezone.now()
    ready = Q(status=S.PENDING, requested_at__isnull=False) & (
        Q(next_retry_at__lte=now) | Q(next_retry_at__isnull=True, requested_at__lt=now - LOST_AFTER)
    )
    stuck = Q(status=S.SUBMITTED, updated_at__lt=now - STUCK_AFTER)
    bills = EWayBill.objects.filter(ready | stuck).values_list("pk", flat=True)[:100]
    updates = EWayBillUpdate.objects.filter(status=U.PENDING).filter(
        Q(next_retry_at__lte=now) | Q(next_retry_at__isnull=True, created_at__lt=now - LOST_AFTER)
    )
    return list(bills), list(updates.values_list("pk", flat=True)[:100])
