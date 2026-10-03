"""Posting to the shop's account (PLAN §4.5, spec 5.12, ADR-013/017/046).

Every money event writes one append-only ``LedgerEntry`` with the balance after it, under the
shop's account row lock (level L1). Rows that money is matched against (invoices, adjustments,
payments, credit notes: level L5) are only ever changed while their shop's account is locked, so
two shops never wait on each other's rows.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing.tax import due_date as due_after
from apps.ledger.models import EntryType, LedgerAdjustment, LedgerEntry, RetailerAccount
from apps.retailers.models import Retailer
from common.db import retry_on_deadlock
from common.errors import InvalidFields, NotFound

ZERO = Decimal("0.00")


def lock_account(retailer_id: UUID) -> RetailerAccount:
    """Lock level L1: serialises a shop's orders, credit checks and money events (PLAN §5.1).
    The row is made with the shop; this creates it if an older shop somehow lacks one."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("lock_account() must run inside the business transaction")
    RetailerAccount.objects.get_or_create(retailer_id=retailer_id)
    account: RetailerAccount = RetailerAccount.objects.select_for_update().get(
        retailer_id=retailer_id
    )
    return account


def lock_accounts(retailer_ids: list[UUID]) -> dict[UUID, RetailerAccount]:
    """Several shops' accounts, always in retailer id order (L1)."""
    ids = sorted(set(retailer_ids))
    for retailer_id in ids:
        RetailerAccount.objects.get_or_create(retailer_id=retailer_id)
    rows = (
        RetailerAccount.objects.select_for_update()
        .filter(retailer_id__in=ids)
        .order_by("retailer_id")
    )
    return {row.retailer_id: row for row in rows}


@dataclass(frozen=True)
class Reference:
    type: str  # INVOICE, CREDIT_NOTE, PAYMENT, ADJUSTMENT
    id: UUID
    number: str = ""


def post(
    account: RetailerAccount,
    entry_type: str,
    *,
    debit: Decimal = ZERO,
    credit: Decimal = ZERO,
    entry_date: date,
    ref: Reference,
    narration: str = "",
    by: User | None,
    reverses: LedgerEntry | None = None,
) -> LedgerEntry:
    """One entry on a locked account: ``balance_after = balance + debit - credit``."""
    if (debit > 0) == (credit > 0) or debit < 0 or credit < 0:
        raise ValueError("an entry is either a debit or a credit, above zero")
    account.total_debits += debit
    account.total_credits += credit
    account.balance = account.total_debits - account.total_credits
    account.last_entry_at = timezone.now()
    account.save(
        update_fields=["total_debits", "total_credits", "balance", "last_entry_at", "updated_at"]
    )
    entry: LedgerEntry = LedgerEntry.objects.create(
        account=account,
        retailer_id=account.retailer_id,
        entry_type=entry_type,
        entry_date=entry_date,
        debit=debit,
        credit=credit,
        balance_after=account.balance,
        reference_type=ref.type,
        reference_id=ref.id,
        reference_number=ref.number,
        narration=narration[:300],
        reverses=reverses,
        created_by=by,
    )
    return entry


def add_unapplied(account: RetailerAccount, amount: Decimal) -> None:
    """Money received or credited that is not matched to anything yet (a locked account)."""
    account.unapplied_credit += amount
    if account.unapplied_credit < 0:
        raise ValueError("unapplied credit can't go below zero")
    account.save(update_fields=["unapplied_credit", "updated_at"])


# --- Adjustments and opening balances (audited) -----------------------------------------------

_ENTRY_FOR = {
    LedgerAdjustment.Kind.OPENING_DEBIT: EntryType.OPENING_BALANCE,
    LedgerAdjustment.Kind.OPENING_CREDIT: EntryType.OPENING_BALANCE,
    LedgerAdjustment.Kind.DEBIT: EntryType.DEBIT_ADJUSTMENT,
    LedgerAdjustment.Kind.CREDIT: EntryType.CREDIT_ADJUSTMENT,
}


def _create_adjustment(
    retailer: Retailer,
    kind: str,
    amount: Decimal,
    *,
    on: date,
    narration: str,
    by: User | None,
    due_date: date | None = None,
    bill_number: str = "",
) -> LedgerAdjustment:
    from apps.ledger import allocation

    if amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise InvalidFields({"amount": [_("Enter an amount above zero, in rupees and paise.")]})
    if not narration.strip():
        raise InvalidFields({"narration": [_("Say what this adjustment is for.")]})
    debit = kind in (LedgerAdjustment.Kind.OPENING_DEBIT, LedgerAdjustment.Kind.DEBIT)
    if debit and due_date is not None and due_date < on:
        raise InvalidFields({"due_date": [_("The due date can't be before the bill date.")]})
    bill_number = bill_number.strip()[:40] if kind == LedgerAdjustment.Kind.OPENING_DEBIT else ""
    account = lock_account(retailer.pk)  # L1
    if (
        kind == LedgerAdjustment.Kind.OPENING_CREDIT
        and LedgerAdjustment.objects.filter(
            retailer=retailer, kind=LedgerAdjustment.Kind.OPENING_CREDIT
        ).exists()
    ):
        raise InvalidFields({"kind": [_("This shop already has an opening advance.")]})
    if (
        bill_number
        and LedgerAdjustment.objects.filter(
            retailer=retailer, kind=LedgerAdjustment.Kind.OPENING_DEBIT, bill_number=bill_number
        ).exists()
    ):
        raise InvalidFields({"bill_number": [_("This old bill is already in the shop's account.")]})
    adjustment = LedgerAdjustment(
        retailer=retailer,
        kind=kind,
        amount=amount,
        adjustment_date=on,
        # Old bills and debits fall due after the shop's payment terms unless a date is given
        # (2026-09-28); credits have no due date of their own.
        due_date=(due_date or due_after(on, retailer.payment_terms_days)) if debit else on,
        bill_number=bill_number,
        narration=narration.strip()[:300],
        created_by=by,
    )
    if adjustment.is_debit:
        adjustment.balance_due = amount
    else:
        adjustment.unapplied_amount = amount
    adjustment.save()
    label = f"{adjustment.get_kind_display()} {bill_number}".strip()
    ref = Reference("ADJUSTMENT", adjustment.pk, label[:40])
    if adjustment.is_debit:
        post(
            account,
            _ENTRY_FOR[LedgerAdjustment.Kind(kind)],
            debit=amount,
            entry_date=on,
            ref=ref,
            narration=adjustment.narration,
            by=by,
        )
    else:
        post(
            account,
            _ENTRY_FOR[LedgerAdjustment.Kind(kind)],
            credit=amount,
            entry_date=on,
            ref=ref,
            narration=adjustment.narration,
            by=by,
        )
        add_unapplied(account, amount)
    allocation.settle(account, by=by)  # unused credit meets what is owed, oldest first
    adjustment.refresh_from_db()  # matching changed it through another instance
    audit.record(
        "ledger.adjustment_posted",
        target=adjustment,
        target_repr=f"{retailer.code} {retailer.shop_name}",
        metadata={
            "kind": kind,
            "amount": str(amount),
            "date": str(on),
            "due_date": str(adjustment.due_date),
            "bill_number": bill_number,
            "narration": adjustment.narration,
        },
    )
    return adjustment


@retry_on_deadlock()
def post_adjustment(
    retailer_id: UUID,
    kind: str,
    amount: Decimal,
    *,
    on: date,
    narration: str,
    by: User | None,
    due_date: date | None = None,
    bill_number: str = "",
) -> LedgerAdjustment:
    """An opening bill (several per shop, each with its bill date and due date), an opening
    advance (once per shop), or a manual debit/credit, with a narration. A debit's due date
    defaults to its date plus the shop's payment terms."""
    if kind not in LedgerAdjustment.Kind.values:
        raise InvalidFields({"kind": [_("Choose the kind of adjustment.")]})
    with transaction.atomic():
        retailer = Retailer.objects.filter(pk=retailer_id, deleted_at__isnull=True).first()
        if retailer is None:
            raise NotFound()
        return _create_adjustment(
            retailer,
            kind,
            amount,
            on=on,
            narration=narration,
            by=by,
            due_date=due_date,
            bill_number=bill_number,
        )
