"""Receivables reads (PLAN §3.8, spec 5.12, ADR-046 items 8-9).

Dues are invoices and debit adjustments (opening balances, debits) with a balance. Due date =
invoice date + the shop's payment terms; overdue = past the due date with a balance. Ageing
buckets (0-30, 31-60, 61-90, 90+ days) count days since the invoice date, or days past the due
date (⚙ ``receivables.ageing_basis``; then dues not yet due are "Not due"). A shop's net
outstanding is what it owes minus its unused credit (= its ledger balance).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Sum

from apps.billing.models import Invoice
from apps.ledger.allocation import DEBIT_KINDS
from apps.ledger.models import LedgerAdjustment, RetailerAccount
from apps.platform.selectors import get_setting
from common.dates import today_ist

ZERO = Decimal("0.00")
BUCKETS = ("not_due", "d0_30", "d31_60", "d61_90", "d90_plus")


@dataclass(frozen=True)
class Due:
    kind: str  # INVOICE | ADJUSTMENT
    id: UUID
    retailer_id: UUID
    number: str
    document_date: date
    due_date: date
    amount: Decimal
    balance_due: Decimal

    def days_overdue(self, on: date) -> int:
        return max((on - self.due_date).days, 0)


def open_dues(retailer_ids: Iterable[UUID] | None = None) -> list[Due]:
    """Everything still owed, the earliest due first."""
    invoices = Invoice.objects.filter(status="ISSUED", balance_due__gt=0)
    debits = LedgerAdjustment.objects.filter(kind__in=DEBIT_KINDS, balance_due__gt=0)
    if retailer_ids is not None:
        ids = list(retailer_ids)
        invoices = invoices.filter(retailer_id__in=ids)
        debits = debits.filter(retailer_id__in=ids)
    rows = [
        Due("INVOICE", i.pk, i.retailer_id, i.number, i.invoice_date, i.due_date, i.grand_total,
            i.balance_due)
        for i in invoices.only(
            "id", "retailer_id", "number", "invoice_date", "due_date", "grand_total",
            "balance_due",
        )
    ] + [
        Due("ADJUSTMENT", a.pk, a.retailer_id, a.get_kind_display(), a.adjustment_date,
            a.due_date, a.amount, a.balance_due)
        for a in debits
    ]  # fmt: skip
    return sorted(rows, key=lambda d: (d.due_date, d.document_date, d.number))


def bucket_of(due: Due, *, on: date, basis: str) -> str:
    if basis == "DUE_DATE":
        if due.due_date >= on:
            return "not_due"
        days = (on - due.due_date).days
    else:
        days = max((on - due.document_date).days, 0)
    if days <= 30:
        return "d0_30"
    if days <= 60:
        return "d31_60"
    if days <= 90:
        return "d61_90"
    return "d90_plus"


@dataclass
class AgeingRow:
    retailer_id: UUID
    buckets: dict[str, Decimal] = field(default_factory=lambda: dict.fromkeys(BUCKETS, ZERO))
    owed: Decimal = ZERO  # every due's balance
    overdue: Decimal = ZERO  # past its due date
    unapplied_credit: Decimal = ZERO
    oldest_due: date | None = None

    @property
    def net(self) -> Decimal:
        """What the shop owes after its unused credit (= the ledger balance)."""
        return self.owed - self.unapplied_credit


def ageing(
    retailer_ids: Iterable[UUID] | None = None, *, on: date | None = None, basis: str | None = None
) -> tuple[str, list[AgeingRow]]:
    """Per shop with a balance or unused credit: owed per bucket, overdue, unused credit and net.
    Returns the basis used and the rows, the most overdue shops first."""
    today = on or today_ist()
    used = basis or str(get_setting("receivables.ageing_basis"))
    ids = None if retailer_ids is None else list(retailer_ids)
    rows: dict[UUID, AgeingRow] = {}
    for due in open_dues(ids):
        row = rows.setdefault(due.retailer_id, AgeingRow(due.retailer_id))
        row.buckets[bucket_of(due, on=today, basis=used)] += due.balance_due
        row.owed += due.balance_due
        if due.due_date < today:
            row.overdue += due.balance_due
            row.oldest_due = min(row.oldest_due or due.due_date, due.due_date)
    accounts = RetailerAccount.objects.filter(unapplied_credit__gt=0)
    if ids is not None:
        accounts = accounts.filter(retailer_id__in=ids)
    for retailer_id, credit in accounts.values_list("retailer_id", "unapplied_credit"):
        rows.setdefault(retailer_id, AgeingRow(retailer_id)).unapplied_credit = credit
    ordered = sorted(rows.values(), key=lambda r: (-r.overdue, r.oldest_due or date.max, -r.owed))
    return used, ordered


@dataclass(frozen=True)
class Outstanding:
    balance: Decimal  # net: owed - unused credit
    owed: Decimal
    overdue: Decimal
    unapplied_credit: Decimal
    oldest_due: date | None
    days_overdue: int  # of the oldest overdue due


def outstanding(retailer_id: UUID, *, on: date | None = None) -> Outstanding:
    """One shop's position (its account page, the shop's own "what I owe")."""
    today = on or today_ist()
    dues = open_dues([retailer_id])
    late = [d for d in dues if d.due_date < today]
    account = RetailerAccount.objects.filter(retailer_id=retailer_id).first()
    oldest = late[0].due_date if late else None
    return Outstanding(
        balance=account.balance if account else ZERO,
        owed=sum((d.balance_due for d in dues), ZERO),
        overdue=sum((d.balance_due for d in late), ZERO),
        unapplied_credit=account.unapplied_credit if account else ZERO,
        oldest_due=oldest,
        days_overdue=(today - oldest).days if oldest else 0,
    )


def receivables_summary(
    retailer_ids: Iterable[UUID] | None = None, *, on: date | None = None
) -> dict[str, Any]:
    """Dashboard totals: owed, overdue, shops overdue, and what falls due in the next 7 days."""
    today = on or today_ist()
    retailer_ids = None if retailer_ids is None else list(retailer_ids)
    dues = open_dues(retailer_ids)
    late = [d for d in dues if d.due_date < today]
    soon = [d for d in dues if today <= d.due_date <= today + timedelta(days=7)]
    credit = RetailerAccount.objects.filter(unapplied_credit__gt=0)
    if retailer_ids is not None:
        credit = credit.filter(retailer_id__in=retailer_ids)
    return {
        "owed": sum((d.balance_due for d in dues), ZERO),
        "overdue": sum((d.balance_due for d in late), ZERO),
        "shops_overdue": len({d.retailer_id for d in late}),
        "due_this_week": sum((d.balance_due for d in soon), ZERO),
        "unapplied_credit": Decimal(
            credit.aggregate(total=Sum("unapplied_credit"))["total"] or ZERO
        ),
    }
