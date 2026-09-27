"""Credit exposure (ADR-013, fixed formula) with the Phase 4 stub (ADR-044):

    exposure = ledger balance (0 until Phase 5)
             + value incl. GST of every open order quantity not yet dispatched
             + this order

An empty credit limit means unlimited; 0 means no credit (every credit order breaches).
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce

from apps.billing.tax import round2
from apps.ledger.models import RetailerAccount
from apps.orders.models import OPEN_STATUSES, OrderLine
from apps.retailers.models import Retailer

ZERO = Decimal("0.00")
MONEY = DecimalField(max_digits=20, decimal_places=6)


class CreditOutcome:
    OK = "OK"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"  # the order goes ON_HOLD (credit.breach_action)
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class CreditStatus:
    limit: Decimal | None  # None: no limit
    exposure: Decimal  # before this order
    order_total: Decimal
    outcome: str

    @property
    def available(self) -> Decimal | None:
        return None if self.limit is None else self.limit - self.exposure

    @property
    def breached(self) -> bool:
        return self.outcome != CreditOutcome.OK


def open_order_value(retailer_id: UUID, *, exclude_order_id: UUID | None = None) -> Decimal:
    """Value (incl. GST) of open order quantities not yet dispatched. Each line's estimate is for
    its ordered quantity, so the open part is ``line_total x open / ordered``."""
    qs = OrderLine.objects.filter(order__retailer_id=retailer_id, order__status__in=OPEN_STATUSES)
    if exclude_order_id is not None:
        qs = qs.exclude(order_id=exclude_order_id)
    open_value = ExpressionWrapper(
        F("line_total")
        * (F("qty_ordered") - F("qty_cancelled") - F("qty_dispatched"))
        / F("qty_ordered"),
        output_field=MONEY,
    )
    total = qs.aggregate(v=Coalesce(Sum(open_value), Decimal("0"), output_field=MONEY))["v"]
    return round2(Decimal(total))


def exposure(retailer_id: UUID, *, exclude_order_id: UUID | None = None) -> Decimal:
    balance = (
        RetailerAccount.objects.filter(retailer_id=retailer_id)
        .values_list("balance", flat=True)
        .first()
    )
    return Decimal(balance or ZERO) + open_order_value(
        retailer_id, exclude_order_id=exclude_order_id
    )


def check(
    retailer: Retailer,
    order_total: Decimal,
    *,
    breach_action: str,
    exclude_order_id: UUID | None = None,
) -> CreditStatus:
    """Would ``order_total`` more take the shop over its limit? ``breach_action`` is the
    ⚙ ``credit.breach_action`` in effect (live for a cart, the snapshot for an order)."""
    current = exposure(retailer.pk, exclude_order_id=exclude_order_id)
    limit = retailer.credit_limit
    over = limit is not None and current + order_total > limit
    outcome = CreditOutcome.OK
    if over:
        outcome = (
            CreditOutcome.BLOCKED if breach_action == "BLOCK" else CreditOutcome.NEEDS_APPROVAL
        )
    return CreditStatus(limit, current, order_total, outcome)


def lock_account(retailer_id: UUID) -> RetailerAccount:
    """Lock level L1: serialises a shop's orders and credit checks (PLAN §5.1). The row is made
    with the shop; this creates it if an older shop somehow lacks one."""
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
