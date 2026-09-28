"""Credit control (ADR-013, ADR-045, ADR-046 item 9):

    exposure = ledger balance
             + cheques credited on receipt that haven't cleared (they don't reduce exposure)
             + value incl. GST of every open order quantity not yet invoiced
             + this order

An empty credit limit means unlimited; 0 means no credit (every credit order breaches).
With ⚙ ``credit.block_overdue_after_days`` = N, a shop with anything owed more than N days past
its due date is treated as over its limit, whatever the limit: the same hold or block
(⚙ ``credit.breach_action``), with the reason "Overdue invoices".
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce

from apps.billing.models import Invoice
from apps.billing.tax import round2
from apps.ledger import services as ledger
from apps.ledger.allocation import DEBIT_KINDS
from apps.ledger.models import LedgerAdjustment, RetailerAccount
from apps.orders.models import OPEN_STATUSES, OrderLine
from apps.payments.models import Payment, Refund
from apps.platform.selectors import get_setting
from apps.retailers.models import Retailer
from common.dates import today_ist

ZERO = Decimal("0.00")
MONEY = DecimalField(max_digits=20, decimal_places=6)


class CreditOutcome:
    OK = "OK"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"  # the order goes ON_HOLD (credit.breach_action)
    BLOCKED = "BLOCKED"


class BreachReason:
    CREDIT_LIMIT = "CREDIT_LIMIT"
    OVERDUE = "OVERDUE"


@dataclass(frozen=True)
class CreditStatus:
    limit: Decimal | None  # None: no limit
    exposure: Decimal  # before this order
    order_total: Decimal
    outcome: str
    reason: str = ""  # BreachReason when breached; OVERDUE wins when both apply
    oldest_due: date | None = None  # the earliest due date among overdue dues

    @property
    def available(self) -> Decimal | None:
        return None if self.limit is None else self.limit - self.exposure

    @property
    def breached(self) -> bool:
        return self.outcome != CreditOutcome.OK


def open_order_value(retailer_id: UUID, *, exclude_order_id: UUID | None = None) -> Decimal:
    """Value (incl. GST) of open order quantities not yet invoiced (once invoiced, they are in the
    ledger balance). Each line's estimate is for its ordered quantity, so the open part is
    ``line_total x open / ordered``."""
    qs = OrderLine.objects.filter(order__retailer_id=retailer_id, order__status__in=OPEN_STATUSES)
    if exclude_order_id is not None:
        qs = qs.exclude(order_id=exclude_order_id)
    open_value = ExpressionWrapper(
        F("line_total")
        * (F("qty_ordered") - F("qty_cancelled") - F("qty_invoiced"))
        / F("qty_ordered"),
        output_field=MONEY,
    )
    total = qs.aggregate(v=Coalesce(Sum(open_value), Decimal("0"), output_field=MONEY))["v"]
    return round2(Decimal(total))


def uncleared_cheques(retailer_id: UUID) -> Decimal:
    """Cheques credited when received that the bank hasn't cleared yet."""
    total = Payment.objects.filter(
        retailer_id=retailer_id,
        mode=Payment.Mode.CHEQUE,
        status=Payment.Status.RECEIVED,
        credited=True,
    ).aggregate(v=Sum("amount"))["v"]
    return Decimal(total or ZERO)


def exposure(retailer_id: UUID, *, exclude_order_id: UUID | None = None) -> Decimal:
    balance = (
        RetailerAccount.objects.filter(retailer_id=retailer_id)
        .values_list("balance", flat=True)
        .first()
    )
    return (
        Decimal(balance or ZERO)
        + uncleared_cheques(retailer_id)
        + open_order_value(retailer_id, exclude_order_id=exclude_order_id)
    )


def oldest_overdue(retailer_id: UUID, *, on: date | None = None) -> date | None:
    """The earliest due date of anything still owed more than ⚙ credit.block_overdue_after_days
    past due (invoices and debit adjustments such as opening balances); None when the setting is
    off or nothing is that late."""
    days = get_setting("credit.block_overdue_after_days")
    if days is None:
        return None
    cutoff = (on or today_ist()) - timedelta(days=int(days))  # due before this: over N days late
    invoice = (
        Invoice.objects.filter(
            retailer_id=retailer_id, status="ISSUED", balance_due__gt=0, due_date__lt=cutoff
        )
        .order_by("due_date")
        .values_list("due_date", flat=True)
        .first()
    )
    debit = (
        LedgerAdjustment.objects.filter(
            retailer_id=retailer_id, kind__in=DEBIT_KINDS, balance_due__gt=0, due_date__lt=cutoff
        )
        .order_by("due_date")
        .values_list("due_date", flat=True)
        .first()
    )
    refund = (
        Refund.objects.filter(retailer_id=retailer_id, balance_due__gt=0, refund_date__lt=cutoff)
        .order_by("refund_date")
        .values_list("refund_date", flat=True)
        .first()
    )
    found = [d for d in (invoice, debit, refund) if d is not None]
    return min(found) if found else None


def check(
    retailer: Retailer,
    order_total: Decimal,
    *,
    breach_action: str,
    exclude_order_id: UUID | None = None,
) -> CreditStatus:
    """Would ``order_total`` more take the shop over its limit, or is anything overdue for too
    long? ``breach_action`` is the ⚙ ``credit.breach_action`` in effect (live for a cart, the
    snapshot for an order)."""
    current = exposure(retailer.pk, exclude_order_id=exclude_order_id)
    limit = retailer.credit_limit
    late = oldest_overdue(retailer.pk)
    reason = ""
    if late is not None:
        reason = BreachReason.OVERDUE
    elif limit is not None and current + order_total > limit:
        reason = BreachReason.CREDIT_LIMIT
    outcome = CreditOutcome.OK
    if reason:
        outcome = (
            CreditOutcome.BLOCKED if breach_action == "BLOCK" else CreditOutcome.NEEDS_APPROVAL
        )
    return CreditStatus(limit, current, order_total, outcome, reason, late)


def lock_account(retailer_id: UUID) -> RetailerAccount:
    """Lock level L1 (see ``apps.ledger.services.lock_account``)."""
    return ledger.lock_account(retailer_id)


def lock_accounts(retailer_ids: list[UUID]) -> dict[UUID, RetailerAccount]:
    """Several shops' accounts in retailer id order (L1)."""
    return ledger.lock_accounts(retailer_ids)
