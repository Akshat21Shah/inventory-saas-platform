"""Order reads (PLAN §3.8, §3.9). Sales staff may see only their own shops' orders
(⚙ ``orders.sales_visibility``, PLAN B8)."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models import (
    Count,
    Exists,
    F,
    Max,
    Min,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
    Sum,
)

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.inventory.models import StockLevel
from apps.orders.models import (
    ACCEPTED_STATUSES,
    BackorderAllocation,
    Fulfilment,
    FulfilmentLine,
    Order,
    OrderLine,
    OrderStatus,
    OrderStatusHistory,
)
from apps.retailers.models import Retailer
from apps.retailers.selectors import sees_own_retailers_only

IST = ZoneInfo("Asia/Kolkata")
S = OrderStatus

# The distributor's order board (PLAN §3.8).
TABS: dict[str, Q] = {
    "new": Q(status=S.PLACED),
    "on_hold": Q(status=S.ON_HOLD),
    "backorders": Q(status__in=ACCEPTED_STATUSES, backorder_state=Order.BackorderState.OPEN),
    "in_progress": Q(status__in=(S.ACCEPTED, S.PACKED, S.DISPATCHED, S.PARTLY_DELIVERED)),
    "completed": Q(status__in=(S.COMPLETED, S.CANCELLED, S.REJECTED)),
}


def orders() -> QuerySet[Order]:
    return Order.objects.select_related("retailer")


def orders_for(user: User) -> QuerySet[Order]:
    """Every order the staff member may see."""
    qs = orders()
    if sees_own_retailers_only(user):
        qs = qs.filter(retailer__salesperson=user)
    return qs


def _ist_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=IST)


@dataclass(frozen=True)
class OrderFilters:
    tab: str = ""
    status: str = ""
    retailer_id: UUID | None = None
    salesperson_id: UUID | None = None
    placed_from: date | None = None
    placed_to: date | None = None
    search: str = ""


TO_FOLLOW = Count(
    "lines",
    filter=Q(lines__qty_ordered__gt=F("lines__qty_cancelled") + F("lines__qty_delivered")),
)


def order_list(user: User, f: OrderFilters) -> QuerySet[Order]:
    qs = orders_for(user).annotate(
        line_count=Count("lines", distinct=True), items_to_follow=TO_FOLLOW
    )
    if f.tab:
        qs = qs.filter(TABS[f.tab])
    if f.status:
        qs = qs.filter(status=f.status)
    if f.retailer_id:
        qs = qs.filter(retailer_id=f.retailer_id)
    if f.salesperson_id:
        qs = qs.filter(retailer__salesperson_id=f.salesperson_id)
    if f.placed_from:
        qs = qs.filter(placed_at__gte=_ist_start(f.placed_from))
    if f.placed_to:
        qs = qs.filter(placed_at__lt=_ist_start(f.placed_to + timedelta(days=1)))
    term = " ".join(f.search.split())
    if term:
        qs = qs.filter(
            Q(number__icontains=term)
            | Q(retailer__shop_name__icontains=term)
            | Q(retailer__code__iexact=term)
        )
    return qs


def tab_counts(user: User) -> dict[str, int]:
    """Badges for the board; the completed tab has no count."""
    qs = orders_for(user)
    counts = qs.aggregate(
        **{tab: Count("pk", filter=q) for tab, q in TABS.items() if tab != "completed"}
    )
    counts["proposals"] = (
        allocations_for(user).filter(status=BackorderAllocation.Status.PROPOSED).count()
    )
    counts["to_pack"] = fulfilments_for(user).filter(status=Fulfilment.Status.ALLOCATED).count()
    return counts


def order_detail(order_id: UUID, *, user: User | None = None) -> Order | None:
    base = orders_for(user) if user is not None else orders()
    found: Order | None = (
        base.prefetch_related(
            Prefetch("lines", queryset=OrderLine.objects.order_by("line_no")),
            Prefetch("history", queryset=OrderStatusHistory.objects.select_related("actor")),
            Prefetch(
                "fulfilments",
                queryset=Fulfilment.objects.order_by("created_at").prefetch_related(
                    Prefetch(
                        "lines",
                        queryset=FulfilmentLine.objects.select_related("order_line").order_by(
                            "order_line__line_no"
                        ),
                    )
                ),
            ),
        )
        .filter(pk=order_id)
        .first()
    )
    return found


# --- Shipments -----------------------------------------------------------------------------------


def fulfilments_for(user: User) -> QuerySet[Fulfilment]:
    qs = Fulfilment.objects.select_related("order", "order__retailer")
    if sees_own_retailers_only(user):
        qs = qs.filter(order__retailer__salesperson=user)
    return qs


def fulfilment_list(user: User, status: str = "") -> QuerySet[Fulfilment]:
    qs = fulfilments_for(user).annotate(line_count=Count("lines"))
    return qs.filter(status=status) if status else qs


def fulfilment_detail(user: User, fulfilment_id: UUID) -> Fulfilment | None:
    found: Fulfilment | None = (
        fulfilments_for(user)
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=FulfilmentLine.objects.select_related("order_line").order_by(
                    "order_line__line_no"
                ),
            )
        )
        .filter(pk=fulfilment_id)
        .first()
    )
    return found


# --- Backorders ----------------------------------------------------------------------------------


def waiting_lines_for(user: User) -> QuerySet[OrderLine]:
    qs = OrderLine.objects.filter(qty_backordered__gt=0, order__status__in=ACCEPTED_STATUSES)
    if sees_own_retailers_only(user):
        qs = qs.filter(order__retailer__salesperson=user)
    return qs


@dataclass(frozen=True)
class BackorderGroup:
    product_id: UUID
    product_code: str
    product_name: str
    unit_code: str
    waiting: Decimal
    lines: int
    oldest_placed_at: datetime
    available: Decimal
    proposed: Decimal
    skipped_credit: int
    blocked: int  # waiting lines of blocked shops (never allocated)
    approved_over_limit: int  # waiting lines on orders approved from a credit hold


def backorder_queue(user: User, search: str = "") -> list[BackorderGroup]:
    """Waiting demand grouped by product, oldest wait first, with what is free to allocate."""
    lines = waiting_lines_for(user)
    term = " ".join(search.split())
    if term:
        lines = lines.filter(Q(product_code__iexact=term) | Q(product_name__icontains=term))
    skipped = BackorderAllocation.objects.filter(
        order_line=OuterRef("pk"), status=BackorderAllocation.Status.SKIPPED_CREDIT
    )
    rows = list(
        lines.annotate(skipped=Exists(skipped))
        .values("product_id")
        .annotate(
            product_code=Max("product_code"),
            product_name=Max("product_name"),
            unit_code=Max("unit_code"),
            waiting=Sum("qty_backordered"),
            lines=Count("pk"),
            oldest=Min("order__placed_at"),
            skipped_credit=Count("pk", filter=Q(skipped=True)),
            blocked=Count("pk", filter=Q(order__retailer__status=Retailer.Status.BLOCKED)),
            approved_over_limit=Count("pk", filter=Q(order__credit_approved_value__isnull=False)),
        )
        .order_by("oldest")
    )
    ids = [row["product_id"] for row in rows]
    free = {
        level.product_id: level.quantity_on_hand - level.quantity_reserved
        for level in StockLevel.objects.filter(product_id__in=ids)
    }
    proposed = dict(
        BackorderAllocation.objects.filter(
            product_id__in=ids, status=BackorderAllocation.Status.PROPOSED
        )
        .values("product_id")
        .annotate(total=Sum("quantity"))
        .values_list("product_id", "total")
    )
    return [
        BackorderGroup(
            product_id=row["product_id"],
            product_code=row["product_code"],
            product_name=row["product_name"],
            unit_code=row["unit_code"],
            waiting=row["waiting"],
            lines=row["lines"],
            oldest_placed_at=row["oldest"],
            available=max(free.get(row["product_id"], Decimal("0")), Decimal("0")),
            proposed=proposed.get(row["product_id"], Decimal("0")),
            skipped_credit=row["skipped_credit"],
            blocked=row["blocked"],
            approved_over_limit=row["approved_over_limit"],
        )
        for row in rows
    ]


def waiting_for_product(user: User, product_id: UUID) -> QuerySet[OrderLine]:
    """A product's waiting lines, FIFO (the order allocation serves them)."""
    latest = BackorderAllocation.objects.filter(order_line=OuterRef("pk")).order_by("-created_at")
    return (
        waiting_lines_for(user)
        .filter(product_id=product_id)
        .select_related("order", "order__retailer")
        .annotate(last_allocation_status=Subquery(latest.values("status")[:1]))
        .order_by("order__placed_at", "order_id", "line_no")
    )


def backorder_product(product_id: UUID) -> Any:
    return Product.objects.filter(pk=product_id).select_related("unit").first()


def allocations_for(user: User) -> QuerySet[BackorderAllocation]:
    qs = BackorderAllocation.objects.select_related(
        "order_line", "order_line__order", "order_line__order__retailer", "fulfilment"
    )
    if sees_own_retailers_only(user):
        qs = qs.filter(order_line__order__retailer__salesperson=user)
    return qs


def allocation_list(
    user: User, status: str = "", product_id: UUID | None = None
) -> QuerySet[BackorderAllocation]:
    qs = allocations_for(user)
    if status:
        qs = qs.filter(status=status)
    if product_id:
        qs = qs.filter(product_id=product_id)
    return qs


# --- The shop's own orders (PLAN §3.9) -----------------------------------------------------------

SHOP_STATES: dict[str, Q] = {
    "open": Q(
        status__in=(S.PLACED, S.ON_HOLD, S.ACCEPTED, S.PACKED, S.DISPATCHED, S.PARTLY_DELIVERED)
    ),
    "closed": Q(status__in=(S.COMPLETED, S.CANCELLED, S.REJECTED)),
}


def shop_orders(retailer_id: UUID, state: str = "") -> QuerySet[Order]:
    qs: QuerySet[Order] = Order.objects.filter(retailer_id=retailer_id).annotate(
        line_count=Count("lines", distinct=True), items_to_follow=TO_FOLLOW
    )
    return qs.filter(SHOP_STATES[state]) if state else qs


def shop_order(retailer_id: UUID, order_id: UUID) -> Order | None:
    found = order_detail(order_id)
    return found if found is not None and found.retailer_id == retailer_id else None


def last_order(retailer_id: UUID) -> Order | None:
    """The latest order worth repeating (not rejected or cancelled before anything was sent)."""
    found: Order | None = (
        Order.objects.filter(retailer_id=retailer_id)
        .exclude(status__in=(S.REJECTED, S.CANCELLED))
        .prefetch_related(Prefetch("lines", queryset=OrderLine.objects.order_by("line_no")))
        .order_by("-placed_at", "-id")
        .first()
    )
    return found


def repeat_quantities(order: Order) -> list[tuple[UUID, Decimal]]:
    """What the shop asked for on each line (less what was cancelled), in line order."""
    wanted: dict[UUID, Decimal] = {}
    for line in order.lines.all():
        qty = Decimal(line.qty_ordered)
        if qty > 0:
            wanted[line.product_id] = wanted.get(line.product_id, Decimal("0")) + qty
    return list(wanted.items())


def waiting_items(retailer_id: UUID) -> int:
    return (
        OrderLine.objects.filter(
            order__retailer_id=retailer_id,
            order__status__in=ACCEPTED_STATUSES,
            qty_backordered__gt=0,
        )
        .values("product_id")
        .distinct()
        .count()
    )
