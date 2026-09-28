"""Matching money to what is owed (ADR-017, ADR-046 item 10).

Sources: payments, credit-note credit, credit adjustments (their ``unapplied_amount``).
Targets: invoices and debit adjustments (their ``balance_due``).
Allocations never change the ledger balance: they only say which dues are paid. Every function
here runs on a shop whose account is locked (L1); the source and target rows (L5) belong to it.
"""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any

from apps.accounts.models import User
from apps.billing.models import CreditNote, Invoice, PaymentStatus
from apps.ledger.models import Allocation, LedgerAdjustment, RetailerAccount
from apps.ledger.services import add_unapplied
from apps.payments.models import Payment
from common.errors import InvalidFields

ZERO = Decimal("0.00")
Source = Payment | CreditNote | LedgerAdjustment
Target = Invoice | LedgerAdjustment
CREDIT_KINDS = (LedgerAdjustment.Kind.OPENING_CREDIT, LedgerAdjustment.Kind.CREDIT)
DEBIT_KINDS = (LedgerAdjustment.Kind.OPENING_DEBIT, LedgerAdjustment.Kind.DEBIT)


def _source_date(source: Source) -> date:
    if isinstance(source, Payment):
        return source.payment_date
    if isinstance(source, CreditNote):
        return source.note_date
    return source.adjustment_date


def _target_key(target: Target) -> tuple[date, date, Any]:
    if isinstance(target, Invoice):
        return (target.due_date, target.invoice_date, target.created_at)
    return (target.due_date, target.adjustment_date, target.created_at)


def open_sources(retailer_id: Any) -> list[Source]:
    """Money not yet matched, oldest first (ADR-046 item 10)."""
    rows: list[Source] = [
        *Payment.objects.select_for_update().filter(
            retailer_id=retailer_id, unapplied_amount__gt=0
        ),
        *CreditNote.objects.select_for_update().filter(
            retailer_id=retailer_id, unapplied_amount__gt=0
        ),
        *LedgerAdjustment.objects.select_for_update().filter(
            retailer_id=retailer_id, kind__in=CREDIT_KINDS, unapplied_amount__gt=0
        ),
    ]
    return sorted(rows, key=lambda s: (_source_date(s), s.created_at))


def open_targets(retailer_id: Any) -> list[Target]:
    """What is still owed, the earliest due first."""
    rows: list[Target] = [
        *Invoice.objects.select_for_update().filter(
            retailer_id=retailer_id, status="ISSUED", balance_due__gt=0
        ),
        *LedgerAdjustment.objects.select_for_update().filter(
            retailer_id=retailer_id, kind__in=DEBIT_KINDS, balance_due__gt=0
        ),
    ]
    return sorted(rows, key=_target_key)


def _refresh_status(invoice: Invoice) -> None:
    if invoice.balance_due == 0:
        invoice.payment_status = PaymentStatus.PAID
    elif invoice.amount_paid + invoice.amount_credited > 0:
        invoice.payment_status = PaymentStatus.PARTIAL
    else:
        invoice.payment_status = PaymentStatus.UNPAID


def _move(source: Source, target: Target, amount: Decimal) -> None:
    """Apply ``amount`` (negative to undo) to the running columns of both sides."""
    source.unapplied_amount -= amount
    source.save(update_fields=["unapplied_amount", "updated_at"])
    if isinstance(target, Invoice):
        if isinstance(source, Payment):
            target.amount_paid += amount
        else:
            target.amount_credited += amount
        target.balance_due -= amount
        _refresh_status(target)
        target.save(
            update_fields=[
                "amount_paid",
                "amount_credited",
                "balance_due",
                "payment_status",
                "updated_at",
            ]
        )
    else:
        target.balance_due -= amount
        target.save(update_fields=["balance_due", "updated_at"])


def _fields(source: Source, target: Target) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if isinstance(source, Payment):
        fields["payment"] = source
    elif isinstance(source, CreditNote):
        fields["credit_note"] = source
    else:
        fields["credit_adjustment"] = source
    if isinstance(target, Invoice):
        fields["invoice"] = target
    else:
        fields["debit_adjustment"] = target
    return fields


def apply(
    account: RetailerAccount,
    source: Source,
    target: Target,
    amount: Decimal,
    *,
    automatic: bool,
    by: User | None,
    reason: str = "",
) -> Allocation:
    """Match ``amount`` of ``source`` to ``target`` on a locked account."""
    if amount <= 0 or amount > source.unapplied_amount or amount > target.balance_due:
        raise InvalidFields({"amount": ["More than the payment has left, or than is still owed."]})
    allocation: Allocation = Allocation.objects.create(
        retailer_id=account.retailer_id,
        amount=amount,
        automatic=automatic,
        reason=reason[:300],
        created_by=by,
        **_fields(source, target),
    )
    _move(source, target, amount)
    add_unapplied(account, -amount)
    return allocation


def settle(
    account: RetailerAccount,
    *,
    by: User | None,
    sources: Iterable[Source] | None = None,
    targets: Iterable[Target] | None = None,
) -> list[Allocation]:
    """Oldest money against the earliest dues until one side runs out (automatic)."""
    money = list(sources) if sources is not None else open_sources(account.retailer_id)
    dues = list(targets) if targets is not None else open_targets(account.retailer_id)
    made: list[Allocation] = []
    for source in money:
        for target in dues:
            if source.unapplied_amount <= 0:
                break
            if target.balance_due <= 0:
                continue
            amount = min(source.unapplied_amount, target.balance_due)
            made.append(apply(account, source, target, amount, automatic=True, by=by))
    return made


def reverse(
    account: RetailerAccount, allocation: Allocation, *, by: User | None, reason: str
) -> Allocation:
    """Undo an allocation (to reallocate it, or because its payment bounced): a new row with the
    opposite amount; the money is unused again and the due is owed again (audited by callers)."""
    if allocation.amount <= 0 or Allocation.objects.filter(reverses=allocation).exists():
        raise InvalidFields({"allocation": ["This allocation was already undone."]})
    source: Source = (
        allocation.payment or allocation.credit_note or allocation.credit_adjustment  # type: ignore[assignment]
    )
    target: Target = allocation.invoice or allocation.debit_adjustment  # type: ignore[assignment]
    source = type(source).objects.select_for_update().get(pk=source.pk)
    target = type(target).objects.select_for_update().get(pk=target.pk)
    undo: Allocation = Allocation.objects.create(
        retailer_id=account.retailer_id,
        amount=-allocation.amount,
        automatic=False,
        reverses=allocation,
        reason=reason[:300],
        created_by=by,
        **_fields(source, target),
    )
    _move(source, target, -allocation.amount)
    add_unapplied(account, allocation.amount)
    return undo


def live_allocations(**filters: Any) -> list[Allocation]:
    """Allocations not undone (positive rows without a reversal)."""
    return list(
        Allocation.objects.filter(amount__gt=0, reversed_by__isnull=True, **filters).order_by(
            "created_at"
        )
    )
