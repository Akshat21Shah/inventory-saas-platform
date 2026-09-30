"""Offline payments (PLAN §4.6, spec 5.12, ADR-017/022/046).

- Recording: cash, bank transfer and UPI are credited to the shop at once; a cheque follows
  ⚙ payments.cheque_credit_timing (snapshotted on the payment): credited when received (reversed
  automatically if it bounces) or only when it clears. A receipt number (RCT/…) is issued either
  way.
- Matching: the payment first pays the dues the user chose, then anything else owed, the earliest
  due first; what is left is the shop's credit (⚙ payments.hold_advances). With advances off, a
  payment above what the shop owes is refused (``PAYMENT_EXCEEDS_OUTSTANDING``).
- Salesman collections (ADR-046 item 6): recorded the same way, from shops the salesman can see,
  "With salesman" until a ``payments.record`` user confirms "Handed over" (audited).
- Undoing: a bounced cheque or a payment entered in error is reversed with a PAYMENT_REVERSAL
  debit; its allocations are undone, and the shop's other money then covers what it can.
- Reallocation (ADR-046 item 10): an allocation (automatic or not) can be undone and the money
  matched to other dues (audited).

Lock order: the shop's account (L1), the payment and the dues (L5), the receipt series (L6).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing import numbering
from apps.billing.models import CreditNote, DocumentType, Invoice
from apps.ledger import allocation
from apps.ledger import services as ledger
from apps.ledger.allocation import CREDIT_KINDS, DEBIT_KINDS, Source, Target
from apps.ledger.models import Allocation, EntryType, LedgerAdjustment, LedgerEntry
from apps.payments.models import MANUAL_MODES, Payment, Refund
from apps.platform.selectors import get_setting
from apps.retailers.models import Retailer
from apps.retailers.selectors import retailer_for
from common import outbox
from common.dates import today_ist
from common.db import retry_on_deadlock
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.tenancy import require_tenant_id

ZERO = Decimal("0.00")
PAISA = Decimal("0.01")


class PaymentExceedsOutstanding(DomainError):
    code = ErrorCode.PAYMENT_EXCEEDS_OUTSTANDING
    default_message = "This is more than the shop owes."


class InvalidPaymentState(DomainError):
    status_code = 409
    code = ErrorCode.INVALID_STATE_TRANSITION
    default_message = "This payment can't be changed that way now."


@dataclass(frozen=True)
class DueAmount:
    """A due to pay first: an invoice or a debit adjustment (an opening balance or a debit)."""

    target_type: str  # INVOICE | ADJUSTMENT
    target_id: UUID
    amount: Decimal


@dataclass(frozen=True)
class PaymentInput:
    retailer_id: UUID
    amount: Decimal
    mode: str
    payment_date: date
    reference_no: str = ""
    cheque_number: str = ""
    cheque_date: date | None = None
    bank_name: str = ""
    notes: str = ""
    pay_first: tuple[DueAmount, ...] = field(default_factory=tuple)


def _validate(data: PaymentInput) -> None:
    errors: dict[str, list[str]] = {}
    if data.amount <= 0 or data.amount != data.amount.quantize(PAISA):
        errors["amount"] = ["Enter an amount above zero, in rupees and paise."]
    if data.mode not in dict(MANUAL_MODES):  # online payments come only from the gateway
        errors["mode"] = ["Choose cash, cheque, bank transfer or UPI."]
    if data.mode == Payment.Mode.CHEQUE and not data.cheque_number.strip():
        errors["cheque_number"] = ["Enter the cheque number."]
    if data.payment_date > today_ist():
        errors["payment_date"] = ["The payment date can't be in the future."]
    chosen = [(d.target_type, d.target_id) for d in data.pay_first]
    if len(set(chosen)) != len(chosen) or any(d.amount <= 0 for d in data.pay_first):
        errors["pay_first"] = ["Choose each due once, with an amount above zero."]
    elif sum((d.amount for d in data.pay_first), ZERO) > data.amount:
        errors["pay_first"] = ["The amounts chosen add up to more than the payment."]
    if errors:
        raise InvalidFields(errors)


def _target(retailer_id: UUID, target_type: str, target_id: UUID) -> Target:
    """A due of this shop, locked (L5)."""
    found: Target | None
    if target_type == "INVOICE":
        found = (
            Invoice.objects.select_for_update()
            .filter(pk=target_id, retailer_id=retailer_id, status="ISSUED")
            .first()
        )
    elif target_type == "ADJUSTMENT":
        found = (
            LedgerAdjustment.objects.select_for_update()
            .filter(pk=target_id, retailer_id=retailer_id, kind__in=DEBIT_KINDS)
            .first()
        )
    else:
        found = None
    if found is None:
        raise InvalidFields({"pay_first": ["One of the chosen dues isn't this shop's."]})
    return cast(Target, found)


def _source(retailer_id: UUID, source_type: str, source_id: UUID) -> Source:
    """Money of this shop that can be matched to dues, locked (L5)."""
    found: Source | None
    if source_type == "PAYMENT":
        found = (
            Payment.objects.select_for_update()
            .filter(pk=source_id, retailer_id=retailer_id, credited=True)
            .first()
        )
    elif source_type == "CREDIT_NOTE":
        found = (
            CreditNote.objects.select_for_update()
            .filter(pk=source_id, retailer_id=retailer_id, status="ISSUED")
            .first()
        )
    elif source_type == "ADJUSTMENT":
        found = (
            LedgerAdjustment.objects.select_for_update()
            .filter(pk=source_id, retailer_id=retailer_id, kind__in=CREDIT_KINDS)
            .first()
        )
    else:
        found = None
    if found is None:
        raise NotFound()
    return cast(Source, found)


def _credit(
    payment: Payment, *, on: date, pay_first: list[tuple[Target, Decimal]], by: User | None
) -> None:
    """Post the payment to the locked account and match it: the chosen dues, then the rest."""
    account = ledger.lock_account(payment.retailer_id)
    ledger.post(
        account,
        EntryType.PAYMENT,
        credit=payment.amount,
        entry_date=on,
        ref=ledger.Reference("PAYMENT", payment.pk, payment.number),
        narration=f"{payment.get_mode_display()} received",
        by=by,
    )
    payment.credited = True
    payment.unapplied_amount = payment.amount
    payment.save(update_fields=["credited", "unapplied_amount", "updated_at"])
    ledger.add_unapplied(account, payment.amount)
    for target, amount in pay_first:
        if amount > target.balance_due:
            raise InvalidFields({"pay_first": ["More than is still owed on a chosen due."]})
        allocation.apply(account, payment, target, amount, automatic=False, by=by)
    allocation.settle(account, by=by)  # oldest money first, for whatever is still owed


def _emit(event: str, payment: Payment, **extra: Any) -> None:
    outbox.emit(
        event,
        aggregate_type="Payment",
        aggregate_id=payment.pk,
        payload={
            "payment_id": str(payment.pk),
            "number": payment.number,
            "retailer_id": str(payment.retailer_id),
            "amount": f"{payment.amount:.2f}",
            "mode": payment.mode,
            "status": payment.status,
            "collected_by": str(payment.collected_by_id or ""),
            **extra,
        },
    )


def _record(data: PaymentInput, *, by: User | None, collected: bool) -> Payment:
    _validate(data)
    tenant_id = require_tenant_id()
    retailer = Retailer.objects.filter(pk=data.retailer_id, deleted_at__isnull=True).first()
    if retailer is None:
        raise NotFound()
    account = ledger.lock_account(retailer.pk)  # L1
    cheque = data.mode == Payment.Mode.CHEQUE
    timing = (
        str(get_setting("payments.cheque_credit_timing", tenant_id))
        if cheque
        else Payment.CreditTiming.ON_RECEIPT
    )
    credit_now = timing == Payment.CreditTiming.ON_RECEIPT
    if data.pay_first and not credit_now:
        raise InvalidFields({"pay_first": ["A cheque is matched to dues when it clears."]})
    if not get_setting("payments.hold_advances", tenant_id) and data.amount > account.balance:
        raise PaymentExceedsOutstanding(
            details={"outstanding": f"{max(account.balance, ZERO):.2f}"}
        )
    pay_first = [
        (_target(retailer.pk, d.target_type, d.target_id), d.amount) for d in data.pay_first
    ]  # L5
    _series, number = numbering.next_number(DocumentType.RECEIPT, today_ist())  # L6
    payment: Payment = Payment.objects.create(
        number=number,
        retailer=retailer,
        amount=data.amount,
        mode=data.mode,
        status=Payment.Status.RECEIVED if credit_now else Payment.Status.PENDING_CLEARANCE,
        credit_timing=timing,
        payment_date=data.payment_date,
        reference_no=data.reference_no.strip()[:60],
        cheque_number=data.cheque_number.strip()[:20],
        cheque_date=data.cheque_date if cheque else None,
        bank_name=data.bank_name.strip()[:120],
        notes=data.notes.strip()[:500],
        recorded_by=by,
        collected_by=by if collected else None,
        handover_status=(
            Payment.Handover.WITH_SALESMAN if collected else Payment.Handover.NOT_TRACKED
        ),
        created_by=by,
    )
    if credit_now:
        _credit(payment, on=data.payment_date, pay_first=pay_first, by=by)
    payment.refresh_from_db()
    _emit("payment.received", payment)
    return payment


@dataclass(frozen=True)
class OnlinePaymentInput:
    """A payment the gateway confirmed (ADR-049 item 9)."""

    retailer_id: UUID
    amount: Decimal
    payment_date: date  # the capture date (IST)
    provider: str
    gateway_payment_id: str
    intent_id: UUID
    pay_first: tuple[DueAmount, ...] = ()
    notes: str = ""
    review_reason: str = ""  # set when the amount differed from the checkout's


def record_online_payment(data: OnlinePaymentInput, *, by: User | None) -> Payment:
    """In the caller's transaction: recorded like any payment (a receipt, credited on the capture
    date, the chosen bill first, then the oldest dues), but never refused: the money was received.
    With advances off, anything above what is owed is kept as credit and shown as such (like a
    cheque that clears for more). Recorded by the shop's login that paid."""
    retailer = Retailer.objects.filter(pk=data.retailer_id).first()
    if retailer is None:
        raise NotFound()
    ledger.lock_account(retailer.pk)  # L1
    pay_first = [
        (_target(retailer.pk, d.target_type, d.target_id), d.amount) for d in data.pay_first
    ]  # L5
    _series, number = numbering.next_number(DocumentType.RECEIPT, today_ist())  # L6
    payment: Payment = Payment.objects.create(
        number=number,
        retailer=retailer,
        amount=data.amount,
        mode=Payment.Mode.ONLINE,
        status=Payment.Status.RECEIVED,
        credit_timing=Payment.CreditTiming.ON_RECEIPT,
        payment_date=data.payment_date,
        reference_no=data.gateway_payment_id[:60],
        notes=data.notes[:500],
        recorded_by=by,
        handover_status=Payment.Handover.NOT_TRACKED,
        gateway_provider=data.provider,
        gateway_payment_id=data.gateway_payment_id,
        intent_id=data.intent_id,
        needs_review=bool(data.review_reason),
        review_reason=data.review_reason[:300],
        created_by=by,
    )
    _credit(payment, on=data.payment_date, pay_first=pay_first, by=by)
    payment.refresh_from_db()
    _emit("payment.received", payment)
    return payment


@retry_on_deadlock()
def record_payment(data: PaymentInput, *, by: User | None) -> Payment:
    """Payments recorded in the office (``payments.record``)."""
    with transaction.atomic():
        return _record(data, by=by, collected=False)


@retry_on_deadlock()
def collect_payment(data: PaymentInput, *, by: User) -> Payment:
    """A salesman's collection from a shop they can see (``payments.collect``); it is "With
    salesman" until handed over. Matched oldest first; choosing dues is left to the office."""
    if not get_setting("payments.sales_can_collect", require_tenant_id()):
        raise DomainError(
            "Sales staff can't record collections.",
            code=ErrorCode.PERMISSION_DENIED,
            status_code=403,
        )
    if retailer_for(by, data.retailer_id) is None:
        raise NotFound()
    if data.pay_first:
        raise InvalidFields({"pay_first": ["Collections are matched oldest first."]})
    with transaction.atomic():
        return _record(data, by=by, collected=True)


def _locked_payment(payment_id: UUID) -> Payment:
    """The shop's account (L1), then the payment (L5)."""
    found = Payment.objects.filter(pk=payment_id).values_list("retailer_id", flat=True)
    retailer_id = found.first()
    if retailer_id is None:
        raise NotFound()
    ledger.lock_account(retailer_id)
    payment: Payment = Payment.objects.select_for_update().get(pk=payment_id)
    return payment


def _undo_credit(payment: Payment, *, reason: str, by: User | None) -> None:
    """Take back a credited payment: its allocations, then a reversing debit."""
    account = ledger.lock_account(payment.retailer_id)
    for row in allocation.live_allocations(payment=payment):
        allocation.reverse(account, row, by=by, reason=reason)
    payment.refresh_from_db()
    original = LedgerEntry.objects.get(
        reference_type="PAYMENT", reference_id=payment.pk, entry_type=EntryType.PAYMENT
    )
    ledger.post(
        account,
        EntryType.PAYMENT_REVERSAL,
        debit=payment.amount,
        entry_date=today_ist(),
        ref=ledger.Reference("PAYMENT", payment.pk, payment.number),
        narration=reason,
        by=by,
        reverses=original,
    )
    ledger.add_unapplied(account, -payment.unapplied_amount)
    payment.unapplied_amount = ZERO
    payment.credited = False
    payment.save(update_fields=["unapplied_amount", "credited", "updated_at"])
    allocation.settle(account, by=by)  # the shop's other money covers what it can


def _require_reason(reason: str) -> str:
    if not reason.strip():
        raise InvalidFields({"reason": ["Say why."]})
    return reason.strip()[:300]


@retry_on_deadlock()
def clear_cheque(payment_id: UUID, *, on: date | None = None, by: User | None) -> Payment:
    """The bank cleared the cheque. Credited now if it was waiting for clearance."""
    cleared_on = on or today_ist()
    with transaction.atomic():
        payment = _locked_payment(payment_id)
        if payment.mode != Payment.Mode.CHEQUE or payment.status not in (
            Payment.Status.PENDING_CLEARANCE,
            Payment.Status.RECEIVED,
        ):
            raise InvalidPaymentState()
        if cleared_on > today_ist() or cleared_on < payment.payment_date:
            raise InvalidFields({"on": ["Choose a date between the payment date and today."]})
        waiting = payment.status == Payment.Status.PENDING_CLEARANCE
        payment.status = Payment.Status.CLEARED
        payment.cleared_at = timezone.now()
        payment.save(update_fields=["status", "cleared_at", "updated_at"])
        if waiting:  # the payment's own date drives the ledger and statements (2026-09-28)
            _credit(payment, on=payment.payment_date, pay_first=[], by=by)
            payment.refresh_from_db()
        _emit("payment.cleared", payment)
        return payment


@retry_on_deadlock()
def bounce_cheque(payment_id: UUID, *, reason: str, by: User | None) -> Payment:
    """The cheque bounced: if it was credited, the credit and its allocations are reversed."""
    note = _require_reason(reason)
    with transaction.atomic():
        payment = _locked_payment(payment_id)
        if payment.mode != Payment.Mode.CHEQUE or payment.status not in (
            Payment.Status.PENDING_CLEARANCE,
            Payment.Status.RECEIVED,
        ):
            raise InvalidPaymentState()
        if payment.handover_status == Payment.Handover.WITH_SALESMAN:
            # A bounced cheque must have come back to the office (2026-09-28).
            _hand_over(payment, by=by, automatic="cheque bounced")
        if payment.credited:
            _undo_credit(payment, reason=f"Cheque {payment.cheque_number} bounced: {note}", by=by)
        payment.status = Payment.Status.BOUNCED
        payment.reversed_at = timezone.now()
        payment.reversal_reason = note
        payment.save(update_fields=["status", "reversed_at", "reversal_reason", "updated_at"])
        audit.record(
            "payments.cheque_bounced",
            target=payment,
            target_repr=payment.number,
            metadata={"amount": str(payment.amount), "reason": note},
        )
        _emit("payment.reversed", payment, reason=note)
        return payment


@retry_on_deadlock()
def reverse_payment(payment_id: UUID, *, reason: str, by: User | None) -> Payment:
    """A payment entered in error (``payments.reverse``)."""
    note = _require_reason(reason)
    with transaction.atomic():
        payment = _locked_payment(payment_id)
        if payment.status not in (
            Payment.Status.RECEIVED,
            Payment.Status.CLEARED,
            Payment.Status.PENDING_CLEARANCE,
        ):
            raise InvalidPaymentState()
        if payment.credited:
            _undo_credit(payment, reason=f"Reversed: {note}", by=by)
        was_with_salesman = payment.handover_status == Payment.Handover.WITH_SALESMAN
        if was_with_salesman:  # entered in error: there is no money to hand over (2026-09-28)
            payment.handover_status = Payment.Handover.NOT_NEEDED
        payment.status = Payment.Status.REVERSED
        payment.reversed_at = timezone.now()
        payment.reversal_reason = note
        payment.save(
            update_fields=[
                "status",
                "reversed_at",
                "reversal_reason",
                "handover_status",
                "updated_at",
            ]
        )
        audit.record(
            "payments.reversed",
            target=payment,
            target_repr=payment.number,
            metadata={
                "amount": str(payment.amount),
                "reason": note,
                "left_pending_handover": was_with_salesman,
            },
        )
        _emit("payment.reversed", payment, reason=note)
        return payment


def hand_over(payment_ids: list[UUID], *, by: User) -> list[Payment]:
    """Confirm that salesmen handed these collections over (``payments.record``). Already handed
    over is fine; a payment not collected by a salesman is refused."""
    with transaction.atomic():
        payments = list(
            Payment.objects.select_for_update().filter(pk__in=set(payment_ids)).order_by("pk")
        )
        if len(payments) != len(set(payment_ids)):
            raise NotFound()
        if any(
            p.handover_status in (Payment.Handover.NOT_TRACKED, Payment.Handover.NOT_NEEDED)
            for p in payments
        ):
            raise InvalidFields(
                {"payments": ["Only collections still with sales staff can be handed over."]}
            )
        for payment in payments:
            if payment.handover_status == Payment.Handover.WITH_SALESMAN:
                _hand_over(payment, by=by)
        return payments


def _hand_over(payment: Payment, *, by: User | None, automatic: str = "") -> None:
    """Record that the collection reached the office (audited, naming who recorded it)."""
    payment.handover_status = Payment.Handover.HANDED_OVER
    payment.handed_over_at = timezone.now()
    payment.handed_over_by = by
    payment.save(
        update_fields=["handover_status", "handed_over_at", "handed_over_by", "updated_at"]
    )
    audit.record(
        "payments.handed_over",
        target=payment,
        target_repr=payment.number,
        metadata={
            "amount": str(payment.amount),
            "collected_by": str(payment.collected_by_id),
            "recorded_by": str(by.pk) if by else "",
            "automatic": automatic,
        },
    )
    _emit("payment.handed_over", payment)  # the salesman hears it reached the office


# --- Allocation by hand (ADR-046 item 10) -----------------------------------------------------


@retry_on_deadlock()
def allocate(
    retailer_id: UUID,
    *,
    source_type: str,
    source_id: UUID,
    to: list[DueAmount],
    by: User,
    reason: str = "",
) -> list[Allocation]:
    """Match unused money (a payment, credit-note credit or a credit adjustment) to dues."""
    if not to or any(d.amount <= 0 for d in to):
        raise InvalidFields({"to": ["Choose at least one due, with an amount above zero."]})
    with transaction.atomic():
        account = ledger.lock_account(retailer_id)  # L1
        source = _source(retailer_id, source_type, source_id)
        made = []
        for due in to:
            target = _target(retailer_id, due.target_type, due.target_id)
            made.append(
                allocation.apply(
                    account, source, target, due.amount, automatic=False, by=by, reason=reason
                )
            )
        audit.record(
            "payments.allocated",
            target_type="Allocation",
            target_id=made[0].pk,
            target_repr=f"{source_type} {source_id}",
            metadata={
                "retailer_id": str(retailer_id),
                "to": [
                    {"type": d.target_type, "id": str(d.target_id), "amount": str(d.amount)}
                    for d in to
                ],
                "reason": reason,
            },
        )
        return made


@retry_on_deadlock()
def reallocate(
    allocation_id: UUID, *, to: list[DueAmount], reason: str, by: User
) -> tuple[Allocation, list[Allocation]]:
    """Undo an allocation (automatic or by hand) and, optionally, match the money to other dues
    in the same step. Without ``to`` the money stays unused until the next match."""
    note = _require_reason(reason)
    with transaction.atomic():
        found = Allocation.objects.filter(pk=allocation_id).values_list("retailer_id", flat=True)
        retailer_id = found.first()
        if retailer_id is None:
            raise NotFound()
        account = ledger.lock_account(retailer_id)  # L1
        row: Allocation = Allocation.objects.select_related(
            "payment", "credit_note", "credit_adjustment", "invoice", "debit_adjustment"
        ).get(pk=allocation_id)
        if row.refund_id:
            raise InvalidFields({"allocation": ["The money used for a refund can't be moved."]})
        undo = allocation.reverse(account, row, by=by, reason=note)
        source: Source = row.payment or row.credit_note or row.credit_adjustment  # type: ignore[assignment]
        source = type(source).objects.select_for_update().get(pk=source.pk)
        made = []
        for due in to:
            target = _target(retailer_id, due.target_type, due.target_id)
            made.append(
                allocation.apply(
                    account, source, target, due.amount, automatic=False, by=by, reason=note
                )
            )
        audit.record(
            "payments.allocation_reversed",
            target=row,
            target_repr=f"{row.amount}",
            metadata={
                "retailer_id": str(retailer_id),
                "automatic": row.automatic,
                "amount": str(row.amount),
                "reason": note,
                "reallocated": [
                    {"type": d.target_type, "id": str(d.target_id), "amount": str(d.amount)}
                    for d in to
                ],
            },
        )
        return undo, made


# --- Refunds (ADR-047 item 4) -----------------------------------------------------------------


class RefundExceedsCredit(DomainError):
    code = ErrorCode.REFUND_EXCEEDS_CREDIT
    default_message = "This is more than the shop's credit balance."


@dataclass(frozen=True)
class RefundInput:
    retailer_id: UUID
    amount: Decimal
    mode: str
    refund_date: date
    reference_no: str = ""
    notes: str = ""


@retry_on_deadlock()
def record_refund(data: RefundInput, *, by: User | None) -> Refund:
    """Pay a shop back from its credit balance (``payments.record``): a ledger debit covered by
    the shop's unused money, oldest first; its own series (RFD/…); audited; a refund voucher."""
    errors: dict[str, list[str]] = {}
    if data.amount <= 0 or data.amount != data.amount.quantize(PAISA):
        errors["amount"] = ["Enter an amount above zero, in rupees and paise."]
    if data.mode not in Refund.Mode.values:
        errors["mode"] = ["Choose cash, bank transfer or UPI."]
    if data.refund_date > today_ist():
        errors["refund_date"] = ["The date can't be in the future."]
    if errors:
        raise InvalidFields(errors)
    with transaction.atomic():
        retailer = Retailer.objects.filter(pk=data.retailer_id, deleted_at__isnull=True).first()
        if retailer is None:
            raise NotFound()
        account = ledger.lock_account(retailer.pk)  # L1
        if data.amount > account.unapplied_credit:
            raise RefundExceedsCredit(details={"available": f"{account.unapplied_credit:.2f}"})
        sources = allocation.open_sources(retailer.pk)  # L5, oldest money first
        _series, number = numbering.next_number(DocumentType.REFUND, today_ist())  # L6
        refund: Refund = Refund.objects.create(
            number=number,
            retailer=retailer,
            amount=data.amount,
            mode=data.mode,
            refund_date=data.refund_date,
            reference_no=data.reference_no.strip()[:60],
            notes=data.notes.strip()[:500],
            recorded_by=by,
            balance_due=data.amount,
            created_by=by,
        )
        ledger.post(
            account,
            EntryType.REFUND,
            debit=refund.amount,
            entry_date=refund.refund_date,
            ref=ledger.Reference("REFUND", refund.pk, number),
            narration=f"Refund by {refund.get_mode_display().lower()}",
            by=by,
        )
        allocation.settle(account, by=by, sources=sources, targets=[refund])
        refund.refresh_from_db()
        if refund.balance_due != 0:  # pragma: no cover - guarded by the credit check above
            raise RuntimeError("a refund must be covered by the shop's credit")
        audit.record(
            "payments.refund_recorded",
            target=refund,
            target_repr=number,
            metadata={
                "retailer_id": str(retailer.pk),
                "amount": str(refund.amount),
                "mode": refund.mode,
                "date": str(refund.refund_date),
            },
        )
        outbox.emit(
            "refund.recorded",
            aggregate_type="Refund",
            aggregate_id=refund.pk,
            payload={
                "refund_id": str(refund.pk),
                "number": number,
                "retailer_id": str(retailer.pk),
                "amount": f"{refund.amount:.2f}",
            },
        )
        return refund


@retry_on_deadlock()
def reverse_refund(refund_id: UUID, *, reason: str, by: User | None) -> Refund:
    """A refund entered in error (``payments.record``): the money it used goes back to the shop's
    credit (and is applied to what it owes, oldest first), a REFUND_REVERSAL credit cancels the
    debit, and the voucher is printed again marked "Reversed". Audited (ADR-047)."""
    note = _require_reason(reason)
    with transaction.atomic():
        retailer_id = Refund.objects.filter(pk=refund_id).values_list("retailer_id", flat=True)
        found = retailer_id.first()
        if found is None:
            raise NotFound()
        account = ledger.lock_account(found)  # L1
        refund: Refund = Refund.objects.select_for_update().get(pk=refund_id)  # L5
        if refund.status != Refund.Status.ISSUED:
            raise InvalidPaymentState("This refund was already reversed.")
        for row in allocation.live_allocations(refund=refund):
            allocation.reverse(account, row, by=by, reason=f"Refund reversed: {note}")
        refund.refresh_from_db()
        refund.status = Refund.Status.REVERSED
        refund.balance_due = ZERO  # cancelled: nothing is owed for it any more
        refund.reversed_at = timezone.now()
        refund.reversed_by = by
        refund.reversal_reason = note
        refund.voucher_pdf_status = "PENDING"
        refund.save(
            update_fields=[
                "status",
                "balance_due",
                "reversed_at",
                "reversed_by",
                "reversal_reason",
                "voucher_pdf_status",
                "updated_at",
            ]
        )
        original = LedgerEntry.objects.get(
            reference_type="REFUND", reference_id=refund.pk, entry_type=EntryType.REFUND
        )
        ledger.post(
            account,
            EntryType.REFUND_REVERSAL,
            credit=refund.amount,
            entry_date=today_ist(),
            ref=ledger.Reference("REFUND", refund.pk, refund.number),
            narration=f"Refund reversed: {note}",
            by=by,
            reverses=original,
        )
        allocation.settle(account, by=by)  # the restored credit pays what is owed, oldest first
        audit.record(
            "payments.refund_reversed",
            target=refund,
            target_repr=refund.number,
            metadata={"amount": str(refund.amount), "reason": note},
        )
        outbox.emit(
            "refund.reversed",
            aggregate_type="Refund",
            aggregate_id=refund.pk,
            payload={
                "refund_id": str(refund.pk),
                "number": refund.number,
                "retailer_id": str(refund.retailer_id),
                "amount": f"{refund.amount:.2f}",
                "reason": note,
            },
        )
        return refund
