"""Shop return requests (ADR-057 item 3): the shop asks to return quantities of an invoice's lines;
staff with ``invoices.manage`` approve (the return credit note is issued by ``credit_notes``, as
for any return) or reject; the shop may cancel while it waits.

What may still be asked for, per invoice line: invoiced, less credited, less asked for in requests
still waiting. Requests are allowed while ⚙ ``returns.shop_requests`` is on, within ⚙
``returns.request_days`` of the invoice date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing import credit_notes
from apps.billing.credit_notes import ReturnLine
from apps.billing.models import (
    CreditNote,
    CreditNoteLine,
    DocumentStatus,
    Invoice,
    InvoiceLine,
    ReturnRequest,
    ReturnRequestLine,
)
from apps.ledger import services as ledger
from apps.platform.selectors import get_setting
from common import outbox
from common.dates import today_ist
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.sequences import next_value

ZERO = Decimal("0")
S = ReturnRequest.Status
REASONS = set(CreditNote.ReturnReason.values)


class ReturnsSwitchedOff(DomainError):
    status_code = 403
    code = ErrorCode.PERMISSION_DENIED
    default_message = "Your distributor takes returns by phone."


class NotWaiting(DomainError):
    status_code = 409
    code = ErrorCode.INVALID_STATE_TRANSITION
    default_message = "This return request has already been decided."


def asked_elsewhere(line_ids: list[UUID], *, excluding: UUID | None = None) -> dict[UUID, Decimal]:
    """Quantities of these invoice lines in requests still waiting for a decision."""
    rows = ReturnRequestLine.objects.filter(
        invoice_line_id__in=line_ids, request__status=S.REQUESTED
    )
    if excluding is not None:
        rows = rows.exclude(request_id=excluding)
    return {
        row["invoice_line_id"]: Decimal(row["qty"])
        for row in rows.values("invoice_line_id").annotate(qty=Sum("quantity")).order_by()
    }


def returnable(lines: list[InvoiceLine]) -> dict[UUID, Decimal]:
    """What the shop may still ask to return, per invoice line."""
    ids = [line.pk for line in lines]
    credited = {
        row["invoice_line_id"]: Decimal(row["qty"])
        for row in CreditNoteLine.objects.filter(
            invoice_line_id__in=ids, credit_note__status=DocumentStatus.ISSUED
        )
        .values("invoice_line_id")
        .annotate(qty=Sum("quantity"))
        .order_by()
    }
    waiting = asked_elsewhere(ids)
    return {
        line.pk: max(
            Decimal(line.quantity) - credited.get(line.pk, ZERO) - waiting.get(line.pk, ZERO),
            ZERO,
        )
        for line in lines
    }


def window_open(invoice: Invoice) -> bool:
    days = int(get_setting("returns.request_days", invoice.tenant_id))
    return today_ist() <= invoice.invoice_date + timedelta(days=days)


def can_request(invoice: Invoice) -> bool:
    """Whether the shop may ask to return anything from this invoice now."""
    return (
        bool(get_setting("returns.shop_requests", invoice.tenant_id))
        and invoice.status == DocumentStatus.ISSUED
        and window_open(invoice)
    )


def _emit(event_type: str, request: ReturnRequest) -> None:
    outbox.emit(
        event_type,
        aggregate_type="ReturnRequest",
        aggregate_id=request.pk,
        payload={
            "return_request_id": str(request.pk),
            "number": request.number,
            "retailer_id": str(request.retailer_id),
            "invoice_id": str(request.invoice_id),
            "status": request.status,
        },
    )


@dataclass(frozen=True)
class AskedLine:
    invoice_line_id: UUID
    quantity: Decimal


@transaction.atomic
def request_return(
    invoice_id: UUID,
    lines: list[AskedLine],
    *,
    reason: str,
    note: str,
    by: User,
    retailer_id: UUID,
) -> ReturnRequest:
    """The shop asks; nothing moves until staff approve."""
    invoice = Invoice.objects.filter(pk=invoice_id, retailer_id=retailer_id).first()
    if invoice is None:
        raise NotFound()
    if not get_setting("returns.shop_requests", invoice.tenant_id):
        raise ReturnsSwitchedOff()
    ledger.lock_account(retailer_id)  # L1: one request or credit at a time for this shop
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    problems: dict[str, list[str]] = {}
    if invoice.status != DocumentStatus.ISSUED:
        problems["invoice"] = ["This bill was cancelled."]
    elif not window_open(invoice):
        days = int(get_setting("returns.request_days", invoice.tenant_id))
        problems["invoice"] = [f"Returns can be asked for within {days} days of the bill."]
    if reason not in REASONS:
        problems["reason"] = ["Choose why you are returning the goods."]
    elif reason == CreditNote.ReturnReason.OTHER and not note.strip():
        problems["note"] = ["Say why you are returning the goods."]
    wanted = [line for line in lines if line.quantity > 0]
    if not wanted:
        problems["lines"] = ["Choose what you want to return."]
    if len({line.invoice_line_id for line in wanted}) != len(wanted):
        problems["lines"] = ["List each item once."]
    invoice_lines = {line.pk: line for line in invoice.lines.all()}
    left = returnable(list(invoice_lines.values()))
    for line in wanted:
        found = invoice_lines.get(line.invoice_line_id)
        if found is None:
            problems["lines"] = ["That item isn't on this bill."]
        elif line.quantity > left[found.pk]:
            most = f"{left[found.pk].normalize():f}"
            problems.setdefault("lines", []).append(
                f"{found.description}: at most {most} can be returned."
            )
    if problems:
        raise InvalidFields(problems)
    year = today_ist().year
    request: ReturnRequest = ReturnRequest.objects.create(
        number=f"RR-{year}-{next_value('RETURN_REQUEST', str(year)):06d}",
        retailer_id=retailer_id,
        invoice=invoice,
        reason=reason,
        note=note.strip()[:500],
        requested_by=by,
        created_by=by,
    )
    ReturnRequestLine.objects.bulk_create(
        [
            ReturnRequestLine(
                tenant_id=request.tenant_id,
                request=request,
                invoice_line_id=line.invoice_line_id,
                quantity=line.quantity,
                created_by=by,
            )
            for line in wanted
        ]
    )
    _emit("return.requested", request)
    return request


def _locked_request(request_id: UUID, retailer_id: UUID | None = None) -> ReturnRequest:
    found = ReturnRequest.objects.filter(pk=request_id)
    if retailer_id is not None:
        found = found.filter(retailer_id=retailer_id)
    shop = found.values_list("retailer_id", flat=True).first()
    if shop is None:
        raise NotFound()
    ledger.lock_account(shop)  # L1 first, as every money document does
    request: ReturnRequest = ReturnRequest.objects.select_for_update().get(pk=request_id)
    if request.status != S.REQUESTED:
        raise NotWaiting(details={"status": request.status})
    return request


@transaction.atomic
def cancel_request(request_id: UUID, *, by: User, retailer_id: UUID) -> ReturnRequest:
    """The shop changed its mind before staff decided."""
    request = _locked_request(request_id, retailer_id)
    request.status, request.decided_at = S.CANCELLED, timezone.now()
    request.save(update_fields=["status", "decided_at", "updated_at"])
    return request


@transaction.atomic
def reject_request(request_id: UUID, *, reason: str, by: User) -> ReturnRequest:
    """Staff say no, with a reason the shop sees."""
    if not reason.strip():
        raise InvalidFields({"reason": ["Say why, so the shop knows."]})
    request = _locked_request(request_id)
    request.status = S.REJECTED
    request.decided_by, request.decided_at = by, timezone.now()
    request.decision_note = reason.strip()[:300]
    request.save(
        update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"]
    )
    audit.record(
        "billing.return_request_rejected",
        target=request,
        target_repr=request.number,
        metadata={"reason": request.decision_note},
    )
    _emit("return.rejected", request)
    return request


@dataclass(frozen=True)
class Decision:
    line_id: UUID  # the request line
    quantity: Decimal
    disposition: str


def approve_request(request_id: UUID, decisions: list[Decision], *, by: User) -> ReturnRequest:
    """Staff approve: per line up to what was asked, with what happened to the goods. The return
    credit note is issued as for any return (stock, ledger, e-invoice, messages)."""
    with transaction.atomic():
        request = _locked_request(request_id)
        lines = {line.pk: line for line in request.lines.select_related("invoice_line")}
        problems: dict[str, list[str]] = {}
        chosen: dict[UUID, Decision] = {}
        for decision in decisions:
            line = lines.get(decision.line_id)
            if line is None:
                problems["lines"] = ["That item isn't on this request."]
            elif decision.quantity < 0 or decision.quantity > line.quantity:
                asked = f"{line.quantity.normalize():f}"
                problems.setdefault("lines", []).append(
                    f"{line.invoice_line.description}: between 0 and {asked}."
                )
            elif decision.quantity > 0 and decision.disposition not in (
                CreditNoteLine.Disposition.values
            ):
                problems.setdefault("lines", []).append(
                    f"{line.invoice_line.description}: say what happened to the goods."
                )
            else:
                chosen[line.pk] = decision
        if not problems and not any(d.quantity > 0 for d in chosen.values()):
            problems["lines"] = ["Approve at least one item, or reject the request."]
        if problems:
            raise InvalidFields(problems)
        note = credit_notes.issue_return(
            request.invoice_id,
            [
                ReturnLine(lines[line_id].invoice_line_id, d.quantity, d.disposition)
                for line_id, d in chosen.items()
                if d.quantity > 0
            ],
            reason=request.reason,
            note=request.note or f"Return request {request.number}",
            by=by,
        )
        for line_id, line in lines.items():
            d = chosen.get(line_id)
            line.approved_quantity = d.quantity if d else ZERO
            line.disposition = d.disposition if d and d.quantity > 0 else ""
            line.save(update_fields=["approved_quantity", "disposition", "updated_at"])
        request.status, request.credit_note = S.APPROVED, note
        request.decided_by, request.decided_at = by, timezone.now()
        request.save(
            update_fields=["status", "credit_note", "decided_by", "decided_at", "updated_at"]
        )
        _emit("return.approved", request)
    return request
