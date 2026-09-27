"""Order reads (PLAN §3.8, §3.9)."""

from uuid import UUID

from django.db.models import Prefetch, QuerySet

from apps.orders.models import Order, OrderLine, OrderStatusHistory


def orders() -> QuerySet[Order]:
    return Order.objects.select_related("retailer")


def order_detail(order_id: UUID) -> Order | None:
    found: Order | None = (
        orders()
        .prefetch_related(
            Prefetch("lines", queryset=OrderLine.objects.order_by("line_no")),
            Prefetch("history", queryset=OrderStatusHistory.objects.select_related("actor")),
        )
        .filter(pk=order_id)
        .first()
    )
    return found
