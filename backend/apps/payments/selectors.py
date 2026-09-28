"""Payment reads (PLAN §3.8, ADR-046 item 6)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db.models import Count, Min, Sum

from apps.payments.models import Payment


@dataclass(frozen=True)
class PendingHandover:
    salesman_id: UUID
    salesman_name: str
    count: int
    amount: Decimal
    oldest: date


def collections_pending_handover() -> list[PendingHandover]:
    """Per salesman: collections still "With salesman" (count, amount, oldest payment date).
    Reversed and bounced collections count too: the cash or cheque is still with them."""
    rows = (
        Payment.objects.filter(handover_status=Payment.Handover.WITH_SALESMAN)
        .values("collected_by", "collected_by__full_name")
        .annotate(count=Count("id"), amount=Sum("amount"), oldest=Min("payment_date"))
        .order_by("oldest", "collected_by__full_name")
    )
    return [
        PendingHandover(
            salesman_id=r["collected_by"],
            salesman_name=r["collected_by__full_name"] or "",
            count=r["count"],
            amount=Decimal(r["amount"]),
            oldest=r["oldest"],
        )
        for r in rows
    ]


def pending_handover_total() -> Decimal:
    """The dashboard total for ``payments.record`` users."""
    total = Payment.objects.filter(handover_status=Payment.Handover.WITH_SALESMAN).aggregate(
        total=Sum("amount")
    )["total"]
    return Decimal(total or 0)
