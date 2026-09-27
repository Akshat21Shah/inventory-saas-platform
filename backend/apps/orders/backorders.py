"""Backorder allocation (spec 5.9, PLAN §4.3, §5.2, ADR-014/021).

Fixed rules: FIFO by order placement time; only accepted orders are eligible; allocation runs in
the same transaction as the stock increase, so new orders can't take the stock first; proposals
hold (reserve) the stock; credit is re-checked and shops over their limit are skipped and flagged.
Settings: ⚙ backorders.allocation_mode (CONFIRM default | AUTO, live) and the order's snapshot of
⚙ backorders.billing_price (ORIGINAL default | CURRENT).

Two-phase locking (PLAN §5.1 rule 2): find the waiting lines without locks, then lock their shops'
accounts (L1) and orders (L2), then stock (L3), then the lines (L4), and re-check under the locks.
Lines whose order wasn't locked in the first phase wait for the next run.
"""

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.inventory import services as stock
from apps.inventory.models import ReferenceType, StockLevel
from apps.orders import credit
from apps.orders.models import (
    ACCEPTED_STATUSES,
    BackorderAllocation,
    Fulfilment,
    FulfilmentLine,
    Order,
    OrderEvent,
    OrderLine,
)
from apps.platform.selectors import get_setting
from apps.pricing.resolve import resolve_prices
from common.db import retry_on_deadlock
from common.errors import InvalidFields, NotFound
from common.tenancy import require_tenant_id, tenant_context

ZERO = Decimal("0")
HUNDRED = Decimal("100")
A = BackorderAllocation.Status
Trigger = BackorderAllocation.Trigger
Pairs = list[tuple[BackorderAllocation, OrderLine]]


def waiting_lines(product_ids: Iterable[UUID]) -> QuerySet[OrderLine]:
    """Backordered lines of accepted orders, oldest order first (FIFO, fixed)."""
    return (
        OrderLine.objects.filter(
            product_id__in=list(product_ids),
            qty_backordered__gt=0,
            order__status__in=ACCEPTED_STATUSES,
        )
        .select_related("order", "order__retailer", "product")
        .order_by("order__placed_at", "order_id", "line_no")
    )


def lock_orders(order_ids: Iterable[UUID]) -> dict[UUID, Order]:
    """L1 then L2 for several orders: their shops' accounts, then the orders, each in id order."""
    ids = sorted(set(order_ids))
    if not ids:
        return {}
    retailer_ids = Order.objects.filter(pk__in=ids).values_list("retailer_id", flat=True)
    credit.lock_accounts(list(retailer_ids))
    rows = Order.objects.select_for_update().select_related("retailer").filter(pk__in=ids)
    return {order.pk: order for order in rows.order_by("pk")}


# --- Allocation run ------------------------------------------------------------------------------


def before_stock_increase(product_ids: Iterable[UUID]) -> dict[UUID, Order]:
    """Phase A, then L1 and L2: lock the shops and orders waiting for these products. Call BEFORE
    locking the stock rows of a stock increase (goods receipt, stock added); pass the result to
    ``allocate_locked``."""
    order_ids = waiting_lines(product_ids).values_list("order_id", flat=True).distinct()
    return lock_orders(order_ids)


def allocate_locked(
    levels: dict[UUID, StockLevel],
    orders: dict[UUID, Order],
    *,
    trigger: str,
    source_id: UUID | None = None,
    by: User | None = None,
    exclude_line_ids: Iterable[UUID] = (),
) -> list[BackorderAllocation]:
    """Serve waiting backorders from free stock, FIFO. The caller holds these orders (L1, L2)
    and stock rows (L3); the lines are locked here (L4)."""
    if not orders:
        return []
    lines = list(
        waiting_lines(levels)
        .filter(order_id__in=list(orders))
        .exclude(pk__in=list(exclude_line_ids))
        .select_for_update(of=("self",))
    )
    if not lines:
        return []
    auto = get_setting("backorders.allocation_mode", require_tenant_id()) == "AUTO"
    made: list[BackorderAllocation] = []
    proposed: dict[UUID, Pairs] = defaultdict(list)
    for line in lines:
        level = levels[line.product_id]
        free = level.quantity_on_hand - level.quantity_reserved
        if free <= 0:
            continue
        order = line.order = orders[line.order_id]
        quantity = min(line.qty_backordered, free)
        if not _credit_allows(order, line, quantity):
            made.extend(_flag_skipped(line, order, level, quantity, trigger, source_id))
            continue
        allocation = BackorderAllocation.objects.create(
            order_line=line,
            product_id=line.product_id,
            warehouse_id=level.warehouse_id,
            quantity=quantity,
            status=A.PROPOSED,
            trigger=trigger,
            source_id=source_id,
        )
        _hold(level, line, allocation, order, by=by)
        _emit("backorder.proposed", allocation, order)
        proposed[order.pk].append((allocation, line))
        made.append(allocation)
    if auto:
        for order_id, pairs in sorted(proposed.items()):
            _confirm_locked(orders[order_id], pairs, by=None)
    return made


def _hold(
    level: StockLevel,
    line: OrderLine,
    allocation: BackorderAllocation,
    order: Order,
    *,
    by: User | None,
) -> None:
    """The proposal holds the stock (fixed): waiting → reserved."""
    ref = stock.Ref(ReferenceType.ALLOCATION, allocation.pk, order.number)
    stock.reserve(level, allocation.quantity, ref, by=by)
    stock.change_backordered(level, -allocation.quantity)
    line.qty_backordered -= allocation.quantity
    line.qty_reserved += allocation.quantity
    line.save(update_fields=["qty_backordered", "qty_reserved", "updated_at"])


def _flag_skipped(
    line: OrderLine,
    order: Order,
    level: StockLevel,
    quantity: Decimal,
    trigger: str,
    source_id: UUID | None,
) -> list[BackorderAllocation]:
    """Over the credit limit: skipped and flagged for staff, once until something else happens
    on the line."""
    latest = BackorderAllocation.objects.filter(order_line=line).order_by("-created_at").first()
    if latest is not None and latest.status == A.SKIPPED_CREDIT:
        return []
    allocation = BackorderAllocation.objects.create(
        order_line=line,
        product_id=line.product_id,
        warehouse_id=level.warehouse_id,
        quantity=quantity,
        status=A.SKIPPED_CREDIT,
        trigger=trigger,
        source_id=source_id,
        note="Over the credit limit",
    )
    _emit("backorder.skipped_credit", allocation, order)
    return [allocation]


def _billing_price(order: Order, line: OrderLine, quantity: Decimal) -> tuple[Decimal, bool]:
    """(unit price, repriced) per the order's snapshot of ⚙ backorders.billing_price: the order
    price, or the shop's price today (the order price when there is none today)."""
    if order.settings_snapshot.get("backorders.billing_price") != "CURRENT":
        return line.unit_price, False
    [result] = resolve_prices(order.retailer, [(line.product, quantity)])
    return (result.unit_price if result.valid else line.unit_price), True


def _credit_allows(
    order: Order, line: OrderLine, quantity: Decimal, price: Decimal | None = None
) -> bool:
    """The waiting quantity is already in the shop's exposure at its order price; a higher
    billing price adds the difference (tax included)."""
    limit = order.retailer.credit_limit
    if limit is None:
        return True
    if price is None:
        price, _ = _billing_price(order, line, quantity)
    extra = max(price - Decimal(line.unit_price), ZERO) * quantity
    if not order.prices_include_tax:
        extra *= 1 + (Decimal(line.gst_rate) + Decimal(line.cess_rate)) / HUNDRED
    return bool(credit.exposure(order.retailer_id) + extra <= Decimal(limit))


def _emit(event_type: str, allocation: BackorderAllocation, order: Order) -> None:
    from apps.orders.services import emit

    emit(
        event_type,
        order,
        allocation_id=str(allocation.pk),
        product_id=str(allocation.product_id),
        quantity=f"{allocation.quantity:f}",
    )


# --- Confirm and reject --------------------------------------------------------------------------


def _confirm_locked(
    order: Order,
    pairs: Pairs,
    *,
    by: User | None,
    prices: dict[UUID, Decimal] | None = None,
) -> Fulfilment:
    """PROPOSED → CONFIRMED: one backorder shipment for the order, at the order price, or today's
    price when the order's snapshot says CURRENT (flagged when higher, ADR-021)."""
    from apps.orders.fulfilment import derive_status
    from apps.orders.services import emit, record
    from apps.orders.transitions import next_fulfilment_number

    shipment: Fulfilment = Fulfilment.objects.create(
        order=order,
        number=next_fulfilment_number(order),
        kind=Fulfilment.Kind.BACKORDER,
        warehouse_id=pairs[0][0].warehouse_id,
    )
    now = timezone.now()
    increased: list[str] = []
    for allocation, line in sorted(pairs, key=lambda pair: pair[1].product_id):
        price, repriced = _billing_price(order, line, allocation.quantity)
        if prices is not None and allocation.pk in prices:
            price = prices[allocation.pk]
        higher = repriced and price > line.unit_price
        if higher:
            increased.append(line.product_code)
        FulfilmentLine.objects.create(
            fulfilment=shipment,
            order_line=line,
            product_id=line.product_id,
            quantity=allocation.quantity,
            unit_price=price,
            price_source=(
                FulfilmentLine.PriceSource.REPRICED
                if repriced
                else FulfilmentLine.PriceSource.ORDER_SNAPSHOT
            ),
            price_increased=higher,
        )
        line.qty_reserved -= allocation.quantity
        line.qty_allocated += allocation.quantity
        line.save(update_fields=["qty_reserved", "qty_allocated", "updated_at"])
        allocation.status, allocation.fulfilment = A.CONFIRMED, shipment
        allocation.decided_by, allocation.decided_at = by, now
        allocation.save(
            update_fields=["status", "fulfilment", "decided_by", "decided_at", "updated_at"]
        )
    record(
        order,
        OrderEvent.BACKORDER_ALLOCATED,
        to=order.status,
        by=by,
        payload={
            "shipment": shipment.number,
            "products": sorted(line.product_code for _, line in pairs),
            "price_increased": increased,
        },
    )
    emit(
        "backorder.allocated",
        order,
        shipment_id=str(shipment.pk),
        shipment=shipment.number,
        price_increased=increased,
    )
    derive_status(order, by=by)
    return shipment


def _lock_allocations(
    allocation_ids: Iterable[UUID],
) -> tuple[dict[UUID, Order], list[BackorderAllocation]]:
    ids = sorted(set(allocation_ids))
    order_ids = BackorderAllocation.objects.filter(pk__in=ids).values_list(
        "order_line__order_id", flat=True
    )
    orders = lock_orders(order_ids)  # L1, L2
    allocations = list(
        BackorderAllocation.objects.select_for_update().filter(pk__in=ids).order_by("pk")
    )
    if not ids or len(allocations) != len(ids):
        raise NotFound()
    return orders, allocations


def _require_open(orders: Iterable[Order]) -> None:
    from apps.orders.transitions import InvalidTransition

    closed = [order.number for order in orders if order.status not in ACCEPTED_STATUSES]
    if closed:
        raise InvalidTransition("Some of these orders are closed.", details={"orders": closed})


def _require_proposed(allocations: list[BackorderAllocation]) -> None:
    from apps.orders.transitions import InvalidTransition

    decided = [a for a in allocations if a.status != A.PROPOSED]
    if decided:
        raise InvalidTransition(
            "Some of these were already decided.",
            details={"allocations": [str(a.pk) for a in decided]},
        )


def void_proposals(order: Order, *, by: User | None, note: str) -> None:
    """The order is closing: its open proposals end (their stock is released with the order's
    lines by the caller)."""
    BackorderAllocation.objects.filter(order_line__order=order, status=A.PROPOSED).update(
        status=A.REJECTED, decided_by=by, decided_at=timezone.now(), note=note[:300]
    )


def _lock_lines(line_ids: Iterable[UUID]) -> dict[UUID, OrderLine]:
    rows = OrderLine.objects.select_for_update().filter(pk__in=sorted(set(line_ids)))
    return {line.pk: line for line in rows.order_by("pk")}  # L4


@retry_on_deadlock()
def confirm(allocation_ids: list[UUID], *, by: User) -> list[Fulfilment]:
    """Staff confirm proposals (bulk): one backorder shipment per order. With a CURRENT billing
    price the credit re-check uses today's price (PLAN §4.3)."""
    from apps.orders.services import CreditLimitExceeded

    with transaction.atomic():
        orders, allocations = _lock_allocations(allocation_ids)
        _require_proposed(allocations)
        lines = _lock_lines(a.order_line_id for a in allocations)
        _require_open(orders.values())
        grouped: dict[UUID, Pairs] = defaultdict(list)
        prices: dict[UUID, Decimal] = {}
        for allocation in allocations:
            line = lines[allocation.order_line_id]
            order = line.order = orders[line.order_id]
            price, repriced = _billing_price(order, line, allocation.quantity)
            if repriced and not _credit_allows(order, line, allocation.quantity, price):
                raise CreditLimitExceeded(
                    f"Today's price puts {order.retailer.shop_name} over the credit limit.",
                    details={"order": order.number, "product": line.product_code},
                )
            prices[allocation.pk] = price
            grouped[order.pk].append((allocation, line))
        return [
            _confirm_locked(orders[order_id], pairs, by=by, prices=prices)
            for order_id, pairs in sorted(grouped.items())
        ]


@retry_on_deadlock()
def reject(allocation_id: UUID, *, by: User) -> BackorderAllocation:
    """PROPOSED → REJECTED: the stock is released and offered to the next shop in line; this line
    keeps its FIFO place but is left out of that run."""
    with transaction.atomic():
        orders, [allocation] = _lock_allocations([allocation_id])
        _require_proposed([allocation])
        product_id = allocation.product_id
        level = stock.lock_levels([product_id], allocation.warehouse)[product_id]  # L3
        line = _lock_lines([allocation.order_line_id])[allocation.order_line_id]  # L4
        order = orders[line.order_id]
        ref = stock.Ref(ReferenceType.ALLOCATION, allocation.pk, order.number)
        stock.release(level, allocation.quantity, ref, by=by)
        stock.change_backordered(level, allocation.quantity)
        line.qty_reserved -= allocation.quantity
        line.qty_backordered += allocation.quantity
        line.save(update_fields=["qty_reserved", "qty_backordered", "updated_at"])
        allocation.status = A.REJECTED
        allocation.decided_by, allocation.decided_at = by, timezone.now()
        allocation.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
        _after_commit_allocate([product_id], exclude_line_ids=[line.pk])
    return allocation


@retry_on_deadlock()
def allocate_manually(
    product_id: UUID, amounts: dict[UUID, Decimal], *, by: User
) -> list[Fulfilment]:
    """Staff choose how much free stock each waiting line gets, in any order, and each order gets
    a backorder shipment at once (🔑 ``orders.allocate_backorder``: a staff decision, so no credit
    re-check)."""
    if not amounts or any(q <= 0 for q in amounts.values()):
        raise InvalidFields({"allocations": ["Choose waiting lines and quantities above 0."]})
    with transaction.atomic():
        candidates = OrderLine.objects.filter(pk__in=list(amounts), product_id=product_id)
        orders = lock_orders(candidates.values_list("order_id", flat=True))  # L1, L2
        level = stock.lock_levels([product_id], stock.default_warehouse())[product_id]  # L3
        lines = _lock_lines(amounts)  # L4
        if set(lines) != set(amounts) or any(
            line.product_id != product_id
            or line.qty_backordered < amounts[line.pk]
            or line.order_id not in orders
            or orders[line.order_id].status not in ACCEPTED_STATUSES
            for line in lines.values()
        ):
            raise InvalidFields({"allocations": ["Some lines aren't waiting for that much."]})
        free = level.quantity_on_hand - level.quantity_reserved
        if sum(amounts.values(), ZERO) > free:
            raise InvalidFields({"allocations": [f"Only {free.normalize():f} is free."]})
        grouped: dict[UUID, Pairs] = defaultdict(list)
        for line_id in sorted(amounts):
            line = lines[line_id]
            order = line.order = orders[line.order_id]
            allocation = BackorderAllocation.objects.create(
                order_line=line,
                product_id=product_id,
                warehouse_id=level.warehouse_id,
                quantity=amounts[line_id],
                status=A.PROPOSED,
                trigger=Trigger.MANUAL,
            )
            _hold(level, line, allocation, order, by=by)
            grouped[order.pk].append((allocation, line))
        return [
            _confirm_locked(orders[order_id], pairs, by=by)
            for order_id, pairs in sorted(grouped.items())
        ]


# --- Cancelling what still waits -----------------------------------------------------------------


@retry_on_deadlock()
def cancel_backorder(line_id: UUID, *, by: User, retailer_id: UUID | None = None) -> OrderLine:
    """The shop (own orders) or staff cancel what a line is still waiting for."""
    from apps.orders.fulfilment import derive_status
    from apps.orders.services import emit, record

    found = OrderLine.objects.filter(pk=line_id).values_list("order_id", "product_id").first()
    if found is None:
        raise NotFound()
    order_id, product_id = found
    with transaction.atomic():
        order = lock_orders([order_id])[order_id]  # L1, L2
        if retailer_id is not None and order.retailer_id != retailer_id:
            raise NotFound()
        level = stock.lock_levels([product_id], stock.default_warehouse())[product_id]  # L3
        line = _lock_lines([line_id])[line_id]  # L4
        if line.qty_backordered <= 0 or order.status not in ACCEPTED_STATUSES:
            raise InvalidFields({"line": ["Nothing is waiting on this line."]})
        quantity = line.qty_backordered
        stock.change_backordered(level, -quantity)
        line.qty_backordered, line.qty_cancelled = ZERO, line.qty_cancelled + quantity
        line.save(update_fields=["qty_backordered", "qty_cancelled", "updated_at"])
        record(
            order,
            OrderEvent.BACKORDER_CANCELLED,
            to=order.status,
            by=by,
            payload={"product": line.product_code, "quantity": f"{quantity:f}"},
        )
        emit("backorder.cancelled", order, product=line.product_code, quantity=f"{quantity:f}")
        derive_status(order, by=by)
    return line


@retry_on_deadlock()
def cancel_repriced(fulfilment_line_id: UUID, *, by: User, retailer_id: UUID) -> FulfilmentLine:
    """ADR-021: when a backorder shipment's price went up, the shop may decline that quantity
    until the shipment is packed. The quantity is cancelled; the stock goes to the next shop in
    line."""
    from apps.orders.fulfilment import derive_status
    from apps.orders.services import emit, record
    from apps.orders.transitions import InvalidTransition

    found = (
        FulfilmentLine.objects.filter(pk=fulfilment_line_id)
        .values_list("fulfilment__order_id", "product_id", "order_line_id")
        .first()
    )
    if found is None:
        raise NotFound()
    order_id, product_id, line_id = found
    with transaction.atomic():
        order = lock_orders([order_id])[order_id]  # L1, L2
        if order.retailer_id != retailer_id:
            raise NotFound()
        fl: FulfilmentLine = FulfilmentLine.objects.select_for_update().get(pk=fulfilment_line_id)
        shipment: Fulfilment = Fulfilment.objects.select_for_update().get(pk=fl.fulfilment_id)
        if not fl.price_increased or fl.cancelled_by_retailer_at is not None:
            raise InvalidTransition("Only a higher price can be declined, once.")
        if shipment.status != Fulfilment.Status.ALLOCATED:
            raise InvalidTransition("This shipment is already packed.")
        level = stock.lock_levels([product_id], shipment.warehouse)[product_id]  # L3
        line = _lock_lines([line_id])[line_id]  # L4
        ref = stock.Ref(ReferenceType.FULFILMENT, shipment.pk, shipment.number)
        stock.release(level, fl.quantity, ref, by=by)
        line.qty_allocated -= fl.quantity
        line.qty_cancelled += fl.quantity
        line.save(update_fields=["qty_allocated", "qty_cancelled", "updated_at"])
        fl.cancelled_by_retailer_at, fl.qty_packed = timezone.now(), ZERO
        fl.save(update_fields=["cancelled_by_retailer_at", "qty_packed", "updated_at"])
        if not FulfilmentLine.objects.filter(
            fulfilment=shipment, cancelled_by_retailer_at__isnull=True
        ).exists():
            shipment.status = Fulfilment.Status.CANCELLED
            shipment.cancelled_reason = "The shop declined the higher price"
            shipment.save(update_fields=["status", "cancelled_reason", "updated_at"])
        record(
            order,
            OrderEvent.BACKORDER_CANCELLED,
            to=order.status,
            by=by,
            payload={
                "product": line.product_code,
                "quantity": f"{fl.quantity:f}",
                "reason": "price_increased",
            },
        )
        emit("backorder.repriced_cancelled", order, product=line.product_code)
        derive_status(order, by=by)
        _after_commit_allocate([product_id])
    return fl


# --- Freed stock ---------------------------------------------------------------------------------


def after_stock_released(product_ids: Iterable[UUID]) -> None:
    """Stock released by a reject, cancel, short pack or cancelled shipment may serve older
    backorders: an allocation run for these products after the transaction commits."""
    _after_commit_allocate(list(product_ids))


def _after_commit_allocate(product_ids: list[UUID], exclude_line_ids: Iterable[UUID] = ()) -> None:
    if not product_ids:
        return
    tenant_id = require_tenant_id()
    ids, excluded = sorted(set(product_ids)), list(exclude_line_ids)

    def run() -> None:
        with tenant_context(tenant_id):
            run_allocation(ids, trigger=Trigger.RELEASE, exclude_line_ids=excluded)

    transaction.on_commit(run)


@retry_on_deadlock()
def run_allocation(
    product_ids: list[UUID],
    *,
    trigger: str,
    source_id: UUID | None = None,
    exclude_line_ids: Iterable[UUID] = (),
) -> list[BackorderAllocation]:
    """A stand-alone allocation run (freed stock), in its own transaction."""
    with transaction.atomic():
        orders = before_stock_increase(product_ids)  # A, L1, L2
        if not orders:
            return []
        levels = stock.lock_levels(product_ids, stock.default_warehouse())  # L3
        return allocate_locked(
            levels,
            orders,
            trigger=trigger,
            source_id=source_id,
            exclude_line_ids=exclude_line_ids,
        )
