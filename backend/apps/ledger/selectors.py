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

from django.db.models import Q, QuerySet, Sum

from apps.billing.models import Invoice
from apps.ledger.allocation import CREDIT_KINDS, DEBIT_KINDS
from apps.ledger.models import Allocation, LedgerAdjustment, LedgerEntry, RetailerAccount
from apps.payments.models import Refund
from apps.platform.selectors import get_setting
from common.dates import today_ist

ZERO = Decimal("0.00")
BUCKETS = ("not_due", "d0_30", "d31_60", "d61_90", "d90_plus")


@dataclass(frozen=True)
class Due:
    kind: str  # INVOICE | ADJUSTMENT | REFUND
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
    refunds = Refund.objects.filter(balance_due__gt=0)  # uncovered after a bounce or reversal
    if retailer_ids is not None:
        ids = list(retailer_ids)
        invoices = invoices.filter(retailer_id__in=ids)
        debits = debits.filter(retailer_id__in=ids)
        refunds = refunds.filter(retailer_id__in=ids)
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
    ] + [
        Due("REFUND", r.pk, r.retailer_id, r.number, r.refund_date, r.refund_date, r.amount,
            r.balance_due)
        for r in refunds
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
    week = today + timedelta(days=7)
    retailer_ids = None if retailer_ids is None else list(retailer_ids)
    # The same dues as ``open_dues``, added up in the database: a large distributor has
    # thousands open (``make perf``). Each source with the field its due date is in.
    sources: list[tuple[QuerySet[Any], str]] = [
        (Invoice.objects.filter(status="ISSUED", balance_due__gt=0), "due_date"),
        (LedgerAdjustment.objects.filter(kind__in=DEBIT_KINDS, balance_due__gt=0), "due_date"),
        (Refund.objects.filter(balance_due__gt=0), "refund_date"),
    ]
    owed = overdue = soon = ZERO
    late_shops: set[UUID] = set()
    for rows, due in sources:
        if retailer_ids is not None:
            rows = rows.filter(retailer_id__in=retailer_ids)
        found = rows.aggregate(
            owed=Sum("balance_due"),
            overdue=Sum("balance_due", filter=Q(**{f"{due}__lt": today})),
            soon=Sum("balance_due", filter=Q(**{f"{due}__gte": today, f"{due}__lte": week})),
        )
        owed += found["owed"] or ZERO
        overdue += found["overdue"] or ZERO
        soon += found["soon"] or ZERO
        late_shops.update(
            rows.filter(**{f"{due}__lt": today}).values_list("retailer_id", flat=True).distinct()
        )
    credit = RetailerAccount.objects.filter(unapplied_credit__gt=0)
    if retailer_ids is not None:
        credit = credit.filter(retailer_id__in=retailer_ids)
    return {
        "owed": owed,
        "overdue": overdue,
        "shops_overdue": len(late_shops),
        "due_this_week": soon,
        "unapplied_credit": Decimal(
            credit.aggregate(total=Sum("unapplied_credit"))["total"] or ZERO
        ),
    }


# --- Allocations, for document pages ------------------------------------------------------------


def _undone(allocations: list[Allocation]) -> set[Any]:
    return {a.reverses_id for a in allocations if a.reverses_id}


def applied_rows(allocations: Iterable[Allocation]) -> list[dict[str, Any]]:
    """Money matched to a due (an invoice or debit adjustment), with where it came from."""
    rows = list(allocations)
    undone = _undone(rows)
    out = []
    for a in rows:
        if a.payment is not None:
            kind, source, number = "PAYMENT", a.payment.pk, a.payment.number
        elif a.credit_note is not None:
            kind, source, number = "CREDIT_NOTE", a.credit_note.pk, a.credit_note.number
        elif a.credit_adjustment is not None:
            kind, source = "ADJUSTMENT", a.credit_adjustment.pk
            number = a.credit_adjustment.get_kind_display()
        else:  # pragma: no cover - a check constraint requires one source
            continue
        out.append(
            {
                "id": a.pk,
                "source_type": kind,
                "source_id": source,
                "source_number": number,
                "amount": a.amount,
                "automatic": a.automatic,
                "reversed": a.pk in undone,
                "created_at": a.created_at,
            }
        )
    return out


def used_for_rows(allocations: Iterable[Allocation]) -> list[dict[str, Any]]:
    """Where a payment's or credit's money went: dues it paid, or a refund."""
    rows = list(allocations)
    undone = _undone(rows)
    out = []
    for a in rows:
        if a.invoice is not None:
            kind, target, number = "INVOICE", a.invoice.pk, a.invoice.number
        elif a.debit_adjustment is not None:
            kind, target = "ADJUSTMENT", a.debit_adjustment.pk
            number = a.debit_adjustment.get_kind_display()
        elif a.refund is not None:
            kind, target, number = "REFUND", a.refund.pk, a.refund.number
        else:  # pragma: no cover - a check constraint requires one target
            continue
        out.append(
            {
                "id": a.pk,
                "target_type": kind,
                "target_id": target,
                "target_number": number,
                "amount": a.amount,
                "automatic": a.automatic,
                "reversed": a.pk in undone,
                "created_at": a.created_at,
            }
        )
    return out


# --- Statement ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class StatementLine:
    id: UUID
    entry_date: date
    entry_type: str
    reference_type: str
    reference_id: UUID
    reference_number: str
    narration: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


@dataclass(frozen=True)
class Statement:
    date_from: date
    date_to: date
    opening_balance: Decimal
    lines: list[StatementLine]
    closing_balance: Decimal
    total_debits: Decimal
    total_credits: Decimal


def statement(retailer_id: UUID, date_from: date, date_to: date) -> Statement:
    """Entries dated in the range, in date order, with a running balance from the balance before
    it (a backdated entry, such as an opening balance, appears on its date)."""
    entries = LedgerEntry.objects.filter(retailer_id=retailer_id)
    before = entries.filter(entry_date__lt=date_from).aggregate(d=Sum("debit"), c=Sum("credit"))
    opening = Decimal(before["d"] or ZERO) - Decimal(before["c"] or ZERO)
    running = opening
    lines: list[StatementLine] = []
    for e in entries.filter(entry_date__gte=date_from, entry_date__lte=date_to).order_by(
        "entry_date", "created_at", "id"
    ):
        running += e.debit - e.credit
        lines.append(
            StatementLine(
                id=e.pk,
                entry_date=e.entry_date,
                entry_type=e.entry_type,
                reference_type=e.reference_type,
                reference_id=e.reference_id,
                reference_number=e.reference_number,
                narration=e.narration,
                debit=e.debit,
                credit=e.credit,
                balance=running,
            )
        )
    return Statement(
        date_from=date_from,
        date_to=date_to,
        opening_balance=opening,
        lines=lines,
        closing_balance=running,
        total_debits=sum((line.debit for line in lines), ZERO),
        total_credits=sum((line.credit for line in lines), ZERO),
    )


def open_money(retailer_id: UUID) -> list[dict[str, Any]]:
    """Unused money a user can match to dues: payments, credit-note credit, credit adjustments."""
    from apps.billing.models import CreditNote
    from apps.payments.models import Payment

    rows: list[dict[str, Any]] = [
        {"source_type": "PAYMENT", "id": p.pk, "number": p.number, "date": p.payment_date,
         "amount": p.amount, "unapplied_amount": p.unapplied_amount}
        for p in Payment.objects.filter(retailer_id=retailer_id, unapplied_amount__gt=0)
    ] + [
        {"source_type": "CREDIT_NOTE", "id": n.pk, "number": n.number, "date": n.note_date,
         "amount": n.grand_total, "unapplied_amount": n.unapplied_amount}
        for n in CreditNote.objects.filter(retailer_id=retailer_id, unapplied_amount__gt=0)
    ] + [
        {"source_type": "ADJUSTMENT", "id": a.pk, "number": a.get_kind_display(),
         "date": a.adjustment_date, "amount": a.amount, "unapplied_amount": a.unapplied_amount}
        for a in LedgerAdjustment.objects.filter(
            retailer_id=retailer_id, kind__in=CREDIT_KINDS, unapplied_amount__gt=0
        )
    ]  # fmt: skip
    return sorted(rows, key=lambda r: (r["date"], r["number"]))


# --- Receivables per shop -----------------------------------------------------------------------


def receivable_rows(
    retailer_ids: list[UUID], *, on: date | None = None, basis: str | None = None
) -> tuple[str, list[dict[str, Any]]]:
    """The receivables and ageing tables: each shop with a balance or unused credit, with its
    name, salesperson, credit limit and last payment; the most overdue first."""
    from apps.payments.models import Payment
    from apps.retailers.models import Retailer

    today = on or today_ist()
    used, rows = ageing(retailer_ids, on=today, basis=basis)
    shops = {
        r.pk: r
        for r in Retailer.objects.filter(pk__in=[row.retailer_id for row in rows]).select_related(
            "salesperson"
        )
    }
    last_paid: dict[UUID, tuple[date, Decimal]] = {}
    for p in (
        Payment.objects.filter(retailer_id__in=list(shops), credited=True)
        .order_by("retailer_id", "-payment_date", "-created_at")
        .distinct("retailer_id")
    ):
        last_paid[p.retailer_id] = (p.payment_date, p.amount)
    out = []
    for row in rows:
        shop = shops[row.retailer_id]
        paid = last_paid.get(row.retailer_id)
        out.append(
            {
                "retailer": shop,
                "salesperson_name": shop.salesperson.full_name if shop.salesperson else "",
                "credit_limit": shop.credit_limit,
                "buckets": row.buckets,
                "owed": row.owed,
                "overdue": row.overdue,
                "unapplied_credit": row.unapplied_credit,
                "net": row.net,
                "oldest_due": row.oldest_due,
                "days_overdue": (today - row.oldest_due).days if row.oldest_due else 0,
                "last_payment_date": paid[0] if paid else None,
                "last_payment_amount": paid[1] if paid else None,
            }
        )
    return used, out


def credit_held_while_advances_off(retailer_id: UUID) -> Decimal | None:
    """Unused credit a shop holds although ⚙ payments.hold_advances is off (a cheque that cleared
    after the bills were paid, credit-note excess): shown to staff as a notice (2026-09-28)."""
    if get_setting("payments.hold_advances"):
        return None
    credit = (
        RetailerAccount.objects.filter(retailer_id=retailer_id)
        .values_list("unapplied_credit", flat=True)
        .first()
    )
    return credit if credit else None
