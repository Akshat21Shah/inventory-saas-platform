"""Payment reads (PLAN §3.8, ADR-046 item 6)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db.models import Count, Min, Q, QuerySet, Sum

from apps.accounts.models import User
from apps.payments.models import Payment, Refund
from apps.retailers.selectors import sees_own_retailers_only


@dataclass(frozen=True)
class PendingHandover:
    salesman_id: UUID
    salesman_name: str
    count: int
    amount: Decimal
    oldest: date


def collections_pending_handover() -> list[PendingHandover]:
    """Per salesman: money actually with them (count, amount, oldest payment date). Collections
    reversed as errors leave the list; bounced cheques were handed over first (2026-09-28)."""
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


# --- Lists and details ------------------------------------------------------------------------


@dataclass(frozen=True)
class PaymentFilters:
    retailer_id: UUID | None = None
    mode: str = ""
    status: str = ""
    handover_status: str = ""
    collected_by: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    search: str = ""
    needs_review: bool = False


def payments_for(user: User) -> QuerySet[Payment]:
    qs = Payment.objects.select_related("retailer", "collected_by", "recorded_by")
    return qs.filter(retailer__salesperson=user) if sees_own_retailers_only(user) else qs


def payment_list(user: User, f: PaymentFilters) -> QuerySet[Payment]:
    qs = payments_for(user)
    if f.retailer_id:
        qs = qs.filter(retailer_id=f.retailer_id)
    if f.mode:
        qs = qs.filter(mode=f.mode)
    if f.status:
        qs = qs.filter(status=f.status)
    if f.handover_status:
        qs = qs.filter(handover_status=f.handover_status)
    if f.collected_by:
        qs = qs.filter(collected_by_id=f.collected_by)
    if f.date_from:
        qs = qs.filter(payment_date__gte=f.date_from)
    if f.date_to:
        qs = qs.filter(payment_date__lte=f.date_to)
    if f.needs_review:
        qs = qs.filter(needs_review=True)
    if f.search:
        term = f.search.strip()
        qs = qs.filter(
            Q(number__icontains=term)
            | Q(retailer__shop_name__icontains=term)
            | Q(retailer__code__iexact=term)
            | Q(reference_no__icontains=term)
            | Q(cheque_number__icontains=term)
        )
    return qs


def payment_detail(
    payment_id: UUID, *, user: User | None = None, retailer_id: UUID | None = None
) -> Payment | None:
    from apps.ledger.models import Allocation
    from apps.ledger.selectors import used_for_rows

    qs = (
        payments_for(user)
        if user is not None
        else Payment.objects.filter(retailer_id=retailer_id).select_related("retailer")
    )
    payment: Payment | None = qs.select_related("handed_over_by").filter(pk=payment_id).first()
    if payment is not None:
        payment.used_for_rows = used_for_rows(  # type: ignore[attr-defined]
            Allocation.objects.filter(payment=payment)
            .select_related("invoice", "debit_adjustment", "refund")
            .order_by("created_at")
        )
    return payment


def refunds_for(user: User) -> QuerySet[Refund]:
    qs = Refund.objects.select_related("retailer", "recorded_by")
    return qs.filter(retailer__salesperson=user) if sees_own_retailers_only(user) else qs


def refund_detail(refund_id: UUID, *, user: User) -> Refund | None:
    from apps.ledger.models import Allocation
    from apps.ledger.selectors import applied_rows

    refund: Refund | None = refunds_for(user).filter(pk=refund_id).first()
    if refund is not None:
        refund.paid_from_rows = applied_rows(  # type: ignore[attr-defined]
            Allocation.objects.filter(refund=refund)
            .select_related("payment", "credit_note", "credit_adjustment")
            .order_by("created_at")
        )
    return refund
