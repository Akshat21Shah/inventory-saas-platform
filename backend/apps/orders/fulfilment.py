"""Shipments after acceptance (PLAN §4.2, ADR-006/007/044): pack (a short pack's remainder goes
back to backorder or is cancelled, per the order's snapshot), dispatch (SALE movements; the
invoice is Phase 5's), deliver, cancel before dispatch, and the order status derived from its
shipments. Lock order: shop account (L1) → order and shipment (L2) → stock levels (L3)."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.inventory import services as stock
from apps.inventory.models import ReferenceType
from apps.orders import backorders
from apps.orders.models import (
    Fulfilment,
    FulfilmentLine,
    Order,
    OrderEvent,
    OrderLine,
    OrderStatus,
)
from apps.orders.services import emit, record
from apps.orders.transitions import InvalidTransition, lock_order, release_quantities
from common.db import retry_on_deadlock
from common.errors import InvalidFields, NotFound

ZERO = Decimal("0")
F = Fulfilment.Status
PROGRESS = {F.ALLOCATED: 0, F.PACKED: 1, F.DISPATCHED: 2}
AS_ORDER_STATUS = {
    F.ALLOCATED: OrderStatus.ACCEPTED,
    F.PACKED: OrderStatus.PACKED,
    F.DISPATCHED: OrderStatus.DISPATCHED,
}
FOLLOWING = (
    OrderStatus.ACCEPTED,
    OrderStatus.PACKED,
    OrderStatus.DISPATCHED,
    OrderStatus.PARTLY_DELIVERED,
)


def _open(line: OrderLine) -> Decimal:
    return Decimal(line.qty_pending + line.qty_reserved + line.qty_backordered)


def next_status(order: Order) -> str:
    """What an accepted order's status is now, from its lines and shipments (PLAN §4.1):
    - COMPLETED: every shipment delivered and nothing left to send;
    - CANCELLED: every shipment cancelled and nothing left;
    - PARTLY_DELIVERED: something delivered, something still to follow (waiting, proposed, or
      in a shipment not yet delivered);
    - otherwise the least advanced open shipment (ACCEPTED when there is none yet)."""
    if order.status not in FOLLOWING:
        return order.status
    lines = list(OrderLine.objects.filter(order=order))
    shipments = list(Fulfilment.objects.filter(order=order).exclude(status=F.CANCELLED))
    open_qty = sum((_open(line) for line in lines), ZERO)
    delivered = [s for s in shipments if s.status == F.DELIVERED]
    undelivered = [s for s in shipments if s.status != F.DELIVERED]
    if open_qty == 0 and not undelivered:
        return OrderStatus.COMPLETED if shipments else OrderStatus.CANCELLED
    if delivered:
        return OrderStatus.PARTLY_DELIVERED
    if undelivered:
        return AS_ORDER_STATUS[min(undelivered, key=lambda s: PROGRESS[s.status]).status]
    return OrderStatus.ACCEPTED


def items_to_follow(order: Order) -> int:
    """Products on the order still to be delivered (for "N items to follow")."""
    return sum(
        1
        for line in OrderLine.objects.filter(order=order)
        if line.qty_ordered - line.qty_cancelled - line.qty_delivered > 0
    )


def derive_status(order: Order, *, by: User | None) -> None:
    """After acceptance the order follows its shipments (``next_status``); ``backorder_state``
    stays in step. Saves the order."""
    if order.status not in FOLLOWING:
        return
    waiting = OrderLine.objects.filter(order=order, qty_backordered__gt=0).exists()
    if waiting:
        order.backorder_state = Order.BackorderState.OPEN
    elif order.backorder_state == Order.BackorderState.OPEN:
        order.backorder_state = Order.BackorderState.CLOSED
    before = order.status
    order.status = next_status(order)
    if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
        order.closed_at = timezone.now()
    if order.status != before and order.status == OrderStatus.COMPLETED:
        record(order, OrderEvent.COMPLETE, to=order.status, by=by, frm=before)
        emit("order.completed", order)
    order.save(update_fields=["status", "backorder_state", "closed_at", "updated_at"])


def _lock_shipment(fulfilment_id: UUID) -> tuple[Order, Fulfilment]:
    order_id = (
        Fulfilment.objects.filter(pk=fulfilment_id).values_list("order_id", flat=True).first()
    )
    if order_id is None:
        raise NotFound()
    order = lock_order(order_id)
    shipment: Fulfilment = Fulfilment.objects.select_for_update().get(pk=fulfilment_id)
    return order, shipment


def _require(shipment: Fulfilment, *allowed: str) -> None:
    if shipment.status not in allowed:
        raise InvalidTransition(
            f"This shipment is {shipment.get_status_display().lower()} now.",
            details={"status": shipment.status},
        )


def _shipment_lines(shipment: Fulfilment) -> list[FulfilmentLine]:
    return list(
        FulfilmentLine.objects.select_for_update()
        .filter(fulfilment=shipment)
        .select_related("order_line")
        .order_by("product_id")
    )


def _return_from_shipment(
    order: Order,
    shipment: Fulfilment,
    amounts: dict[FulfilmentLine, Decimal],
    *,
    to_backorder: bool,
    by: User | None,
    correction: str = "CANCELLATION",
) -> None:
    """Take quantities back out of a shipment: stock released, and the quantity waits again on
    backorder, or is cancelled. Freed stock may serve older backorders after commit. When the
    shipment was already invoiced (ON_ACCEPTANCE), a credit note (``correction``: SHORT_SUPPLY
    or CANCELLATION) is issued first (ADR-046 item 4)."""
    from apps.billing.credit_notes import credit_unsupplied

    credit_unsupplied(amounts, kind=correction, by=by)
    lines = sorted(amounts, key=lambda fl: fl.product_id)
    levels = stock.lock_levels([fl.product_id for fl in lines], shipment.warehouse)
    for fl in lines:
        qty = amounts[fl]
        if qty <= 0:
            continue
        line = OrderLine.objects.select_for_update().get(pk=fl.order_line_id)
        level = levels[fl.product_id]
        stock.release(
            level, qty, stock.Ref(ReferenceType.FULFILMENT, shipment.pk, shipment.number), by=by
        )
        line.qty_allocated -= qty
        if to_backorder:
            line.qty_backordered += qty
            stock.change_backordered(level, qty)
        else:
            line.qty_cancelled += qty
        line.save()
    backorders.after_stock_released([fl.product_id for fl in lines])


# --- Pack --------------------------------------------------------------------------------------


@retry_on_deadlock()
def pack(fulfilment_id: UUID, packed: dict[UUID, Decimal], *, by: User) -> Fulfilment:
    """Record what was packed per shipment line (0 up to the shipment quantity). A short pack's
    remainder goes back on backorder when the order's snapshot allows backorders, else it is
    cancelled; the shop is told (``order.short_supplied``). Nothing packed cancels the shipment."""
    with transaction.atomic():
        order, shipment = _lock_shipment(fulfilment_id)
        _require(shipment, F.ALLOCATED)
        lines = _shipment_lines(shipment)
        errors: dict[str, list[str]] = {}
        for fl in lines:
            qty = packed.get(fl.pk, fl.quantity)
            if qty < 0 or qty > fl.quantity:
                errors[str(fl.pk)] = [f"Pack between 0 and {fl.quantity.normalize():f}."]
        if errors:
            raise InvalidFields(errors)
        short: dict[FulfilmentLine, Decimal] = {}
        for fl in lines:
            fl.qty_packed = packed.get(fl.pk, fl.quantity)
            fl.save(update_fields=["qty_packed", "updated_at"])
            if fl.qty_packed < fl.quantity:
                short[fl] = fl.quantity - fl.qty_packed
        to_backorder = bool(order.settings_snapshot.get("backorders.enabled", True))
        if short:
            _return_from_shipment(
                order, shipment, short, to_backorder=to_backorder, by=by, correction="SHORT_SUPPLY"
            )
            details = [
                {"product": fl.order_line.product_code, "short": f"{q.normalize():f}"}
                for fl, q in short.items()
            ]
            record(
                order,
                OrderEvent.SHORT_SUPPLY,
                to=order.status,
                by=by,
                payload={"lines": details, "to": "backorder" if to_backorder else "cancelled"},
            )
            emit("order.short_supplied", order, lines=details)
        if all(fl.qty_packed == 0 for fl in lines):
            shipment.status = F.CANCELLED
            shipment.cancelled_reason = "Nothing packed"
        else:
            shipment.status, shipment.packed_at = F.PACKED, timezone.now()
        shipment.save(update_fields=["status", "packed_at", "cancelled_reason", "updated_at"])
        if shipment.status == F.PACKED:
            record(
                order,
                OrderEvent.PACK,
                to=next_status(order),
                by=by,
                payload={"shipment": shipment.number},
            )
        derive_status(order, by=by)
    return shipment


# --- Dispatch ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Transport:
    vehicle_number: str = ""
    transporter_name: str = ""
    lr_number: str = ""


@retry_on_deadlock()
def dispatch(fulfilment_id: UUID, transport: Transport, *, by: User) -> Fulfilment:
    """PACKED → DISPATCHED: the packed stock leaves (SALE movements consume the reservation).
    Phase 5 issues the invoice here in the default ON_DISPATCH mode (ADR-044)."""
    with transaction.atomic():
        order, shipment = _lock_shipment(fulfilment_id)
        _require(shipment, F.PACKED)
        lines = [fl for fl in _shipment_lines(shipment) if fl.qty_packed]
        levels = stock.lock_levels([fl.product_id for fl in lines], shipment.warehouse)
        ref = stock.Ref(ReferenceType.FULFILMENT, shipment.pk, shipment.number)
        for fl in lines:
            assert fl.qty_packed is not None
            stock.consume_reserved(levels[fl.product_id], fl.qty_packed, ref, by=by)
            line = OrderLine.objects.select_for_update().get(pk=fl.order_line_id)
            line.qty_dispatched += fl.qty_packed
            line.save(update_fields=["qty_dispatched", "updated_at"])
        shipment.vehicle_number = transport.vehicle_number.strip()[:20]
        shipment.transporter_name = transport.transporter_name.strip()[:120]
        shipment.lr_number = transport.lr_number.strip()[:40]
        shipment.status, shipment.dispatched_at = F.DISPATCHED, timezone.now()
        shipment.save()
        record(
            order,
            OrderEvent.DISPATCH,
            to=next_status(order),
            by=by,
            payload={"shipment": shipment.number, "vehicle": shipment.vehicle_number},
        )
        emit("order.dispatched", order, shipment=shipment.number)
        derive_status(order, by=by)
        from apps.billing import invoicing

        if invoicing.timing(order) == "ON_DISPATCH":  # ADR-007: the packed quantity
            invoicing.issue_invoice_for_fulfilment(shipment, trigger="ON_DISPATCH", by=by)
    return shipment


@retry_on_deadlock()
def deliver(fulfilment_id: UUID, *, by: User) -> Fulfilment:
    """DISPATCHED → DELIVERED (staff with orders.fulfil in v1, ADR-044)."""
    with transaction.atomic():
        order, shipment = _lock_shipment(fulfilment_id)
        _require(shipment, F.DISPATCHED)
        for fl in _shipment_lines(shipment):
            line = OrderLine.objects.select_for_update().get(pk=fl.order_line_id)
            line.qty_delivered += fl.qty_packed or ZERO
            line.save(update_fields=["qty_delivered", "updated_at"])
        shipment.status, shipment.delivered_at = F.DELIVERED, timezone.now()
        shipment.save(update_fields=["status", "delivered_at", "updated_at"])
        record(
            order,
            OrderEvent.DELIVER,
            to=next_status(order),
            by=by,
            payload={"shipment": shipment.number, "items_to_follow": items_to_follow(order)},
        )
        emit("order.delivered", order, shipment=shipment.number)
        derive_status(order, by=by)
    return shipment


# --- Take back after dispatch (IRN cancelled) -----------------------------------------------------


def take_back(
    fulfilment_id: UUID, *, to_backorder: bool, reason: str, by: User | None
) -> Fulfilment:
    """DISPATCHED / DELIVERED → CANCELLED when its invoice's IRN is cancelled and the goods come
    back (ADR-049 item 7): the stock returns, and the quantities wait on backorder again or are
    cancelled. No credit note: the invoice itself is cancelled. The caller holds the transaction,
    the shop's account and the order (L1, L2) and has already un-invoiced the quantities."""
    order, shipment = _lock_shipment(fulfilment_id)
    _require(shipment, F.DISPATCHED, F.DELIVERED)
    delivered = shipment.status == F.DELIVERED
    lines = [fl for fl in _shipment_lines(shipment) if fl.qty_packed]
    levels = stock.lock_levels([fl.product_id for fl in lines], shipment.warehouse)
    ref = stock.Ref(ReferenceType.FULFILMENT, shipment.pk, shipment.number)
    for fl in lines:
        qty = Decimal(fl.qty_packed or ZERO)
        level = levels[fl.product_id]
        stock.return_goods(level, qty, ref, by=by, reason=f"Taken back: {reason}"[:200])
        line = OrderLine.objects.select_for_update().get(pk=fl.order_line_id)
        line.qty_dispatched -= qty
        if delivered:
            line.qty_delivered -= qty
        line.qty_allocated -= qty
        if to_backorder:
            line.qty_backordered += qty
            stock.change_backordered(level, qty)
        else:
            line.qty_cancelled += qty
        line.save()
    shipment.status, shipment.cancelled_reason = F.CANCELLED, reason.strip()[:300]
    shipment.save(update_fields=["status", "cancelled_reason", "updated_at"])
    if order.status == OrderStatus.COMPLETED:  # open again: its shipments decide from here
        order.status, order.closed_at = OrderStatus.ACCEPTED, None
    record(
        order,
        OrderEvent.TAKE_BACK,
        to=next_status(order),
        by=by,
        note=reason,
        payload={
            "shipment": shipment.number,
            "to": "backorder" if to_backorder else "cancelled",
        },
    )
    derive_status(order, by=by)
    backorders.after_stock_returned([fl.product_id for fl in lines])
    return shipment


# --- Cancel before dispatch --------------------------------------------------------------------


@retry_on_deadlock()
def cancel_shipment(
    fulfilment_id: UUID, *, to_backorder: bool, reason: str, by: User
) -> Fulfilment:
    """ALLOCATED / PACKED → CANCELLED: its quantities wait on backorder again, or are cancelled
    (the user chooses, PLAN §4.2)."""
    with transaction.atomic():
        order, shipment = _lock_shipment(fulfilment_id)
        _require(shipment, F.ALLOCATED, F.PACKED)
        lines = _shipment_lines(shipment)
        amounts = {fl: fl.qty_packed if fl.qty_packed is not None else fl.quantity for fl in lines}
        _return_from_shipment(order, shipment, amounts, to_backorder=to_backorder, by=by)
        shipment.status, shipment.cancelled_reason = F.CANCELLED, reason.strip()[:300]
        shipment.save(update_fields=["status", "cancelled_reason", "updated_at"])
        record(
            order,
            OrderEvent.CANCEL,
            to=order.status,
            by=by,
            note=reason,
            payload={
                "shipment": shipment.number,
                "to": "backorder" if to_backorder else "cancelled",
            },
        )
        derive_status(order, by=by)
    return shipment


@retry_on_deadlock()
def cancel_accepted(order_id: UUID, *, reason: str, by: User) -> Order:
    """Staff cancel an accepted order before anything is dispatched: every open shipment and the
    open backorder are cancelled (PLAN §4.1)."""
    with transaction.atomic():
        order = lock_order(order_id)
        if order.status not in (OrderStatus.ACCEPTED, OrderStatus.PACKED):
            raise InvalidTransition(
                "Only orders not yet dispatched can be cancelled.", details={"status": order.status}
            )
        shipments = Fulfilment.objects.select_for_update().filter(order=order)
        if shipments.filter(status__in=(F.DISPATCHED, F.DELIVERED)).exists():
            raise InvalidTransition("Part of this order has been dispatched already.")
        for shipment in shipments.filter(status__in=(F.ALLOCATED, F.PACKED)):
            lines = _shipment_lines(shipment)
            amounts = {
                fl: fl.qty_packed if fl.qty_packed is not None else fl.quantity for fl in lines
            }
            _return_from_shipment(order, shipment, amounts, to_backorder=False, by=by)
            shipment.status, shipment.cancelled_reason = F.CANCELLED, reason.strip()[:300]
            shipment.save(update_fields=["status", "cancelled_reason", "updated_at"])
        backorders.void_proposals(order, by=by, note="Order cancelled")
        waiting = {
            line: _open(line)
            for line in OrderLine.objects.select_for_update().filter(order=order)
            if _open(line) > 0
        }
        if waiting:
            release_quantities(order, waiting, to_backorder=False, by=by)
        record(order, OrderEvent.CANCEL, to=OrderStatus.CANCELLED, by=by, note=reason)
        order.status, order.closed_at = OrderStatus.CANCELLED, timezone.now()
        order.cancellation_reason, order.cancelled_by = reason.strip()[:500], by
        if order.backorder_state == Order.BackorderState.OPEN:
            order.backorder_state = Order.BackorderState.CLOSED
        order.save()
        emit("order.cancelled", order, by="staff")
    return order
