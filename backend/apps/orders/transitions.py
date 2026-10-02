"""Order state machine before dispatch (PLAN §4.1): accept, reject, cancel, modify before
acceptance, approve a credit hold. Shipments after acceptance are in ``fulfilment.py``.

Every function takes the shop's account (L1), then the order (L2), then stock levels (L3).
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy

from apps.accounts.models import User
from apps.audit import services as audit
from apps.inventory import services as stock
from apps.inventory.availability import ShopStockRules
from apps.inventory.models import ReferenceType, StockLevel
from apps.orders import backorders, credit
from apps.orders.models import (
    Fulfilment,
    FulfilmentLine,
    Order,
    OrderEvent,
    OrderLine,
    OrderStatus,
)
from apps.orders.quote import build_quote
from apps.orders.services import (
    CartNotReady,
    _create_line,
    _problems,
    credit_refusal,
    emit,
    free_lines_of,
    order_rules,
    plan_lines,
    recompute_totals,
    record,
)
from common.db import retry_on_deadlock
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound

ZERO = Decimal("0")


class InvalidTransition(DomainError):
    status_code = 409
    code = ErrorCode.INVALID_STATE_TRANSITION
    default_message = gettext_lazy("This order can't be changed that way any more.")


def _status_message(order: Order) -> str:
    return gettext("This order is %(order)s now.") % {"order": order.get_status_display().lower()}


def lock_order(order_id: UUID) -> Order:
    """L1 then L2: the shop's account, then the order row."""
    retailer_id = Order.objects.filter(pk=order_id).values_list("retailer_id", flat=True).first()
    if retailer_id is None:
        raise NotFound()
    credit.lock_account(retailer_id)
    order: Order = Order.objects.select_for_update().select_related("retailer").get(pk=order_id)
    return order


def _require(order: Order, *allowed: str) -> None:
    if order.status not in allowed:
        raise InvalidTransition(_status_message(order), details={"status": order.status})


def _lines(order: Order) -> list[OrderLine]:
    return list(OrderLine.objects.select_for_update().filter(order=order).order_by("product_id"))


def _levels(order: Order, lines: list[OrderLine]) -> dict[UUID, StockLevel]:
    return stock.lock_levels([line.product_id for line in lines], stock.default_warehouse())


def release_quantities(
    order: Order,
    wanted: dict[OrderLine, Decimal],
    *,
    to_backorder: bool,
    by: User | None,
    levels: dict[UUID, StockLevel] | None = None,
) -> None:
    """Take the wanted quantity off each line and move it to cancelled, or to backordered.
    Cancelling takes what still waits first (backordered, then pending), then held stock, so the
    shop keeps what is ready to send (product-owner decision 2026-09-28). Moving to backorder takes
    pending, then held stock. Stock is released and demand counters kept in step."""
    lines = sorted(wanted, key=lambda line: line.product_id)
    levels = levels or stock.lock_levels(
        [line.product_id for line in lines], stock.default_warehouse()
    )
    for line in lines:
        remaining = wanted[line]
        level = levels[line.product_id]
        moved = ZERO
        if not to_backorder:
            take = min(line.qty_backordered, remaining)
            if take:
                stock.change_backordered(level, -take)
                line.qty_backordered -= take
                remaining -= take
                moved += take
        take = min(line.qty_pending, remaining)
        line.qty_pending -= take
        remaining -= take
        moved += take
        take = min(line.qty_reserved, remaining)
        if take:
            stock.release(
                level, take, stock.Ref(ReferenceType.ORDER_LINE, line.pk, order.number), by=by
            )
            line.qty_reserved -= take
            remaining -= take
            moved += take
        if remaining > 0:
            raise ValueError("more released than the line holds")
        if to_backorder:
            line.qty_backordered += moved
            if moved:
                stock.change_backordered(level, moved)
        else:
            line.qty_cancelled += moved
        line.save()
    backorders.after_stock_released([line.product_id for line in lines])


def _open_quantity(line: OrderLine) -> Decimal:
    return Decimal(line.qty_pending + line.qty_reserved + line.qty_backordered)


def rebalance_free_lines(order: Order, *, by: User | None) -> None:
    """ADR-056 item 9: after a bought line loses quantity (a change, short supply, a cancelled
    backorder or shipment), its free line keeps only what the rest still earns under the terms it
    was given; the excess not yet in a shipment is cancelled. Call last, with the order locked."""
    from apps.pricing.schemes import Terms

    wanted: dict[OrderLine, Decimal] = {}
    for line in (
        OrderLine.objects.select_for_update()
        .filter(order=order, free_of_line__isnull=False)
        .select_related("free_of_line")
    ):
        source = line.free_of_line
        if source is None or not line.scheme_rule:
            continue
        earned = Terms.from_line(line).earned(source.qty_ordered - source.qty_cancelled)
        excess = line.qty_ordered - line.qty_cancelled - earned
        take = min(excess, _open_quantity(line))
        if take > 0:
            wanted[line] = take
    if wanted:
        release_quantities(order, wanted, to_backorder=False, by=by)


# --- Accept ------------------------------------------------------------------------------------


def next_fulfilment_number(order: Order) -> str:
    return f"{order.number}/{Fulfilment.objects.filter(order=order).count() + 1}"


@retry_on_deadlock()
def accept_order(order_id: UUID, *, by: User | None) -> Order:
    """PLACED → ACCEPTED: what is reserved becomes shipment #1 (stock stays reserved); what is
    backordered waits for stock (``backorder_state`` OPEN). ``by=None`` is automatic acceptance."""
    with transaction.atomic():
        order = lock_order(order_id)
        _require(order, OrderStatus.PLACED)
        lines = _lines(order)
        ready = [line for line in lines if line.qty_reserved > 0]
        if ready:
            shipment = Fulfilment.objects.create(
                order=order,
                number=next_fulfilment_number(order),
                kind=Fulfilment.Kind.INITIAL,
                warehouse=stock.default_warehouse(),
            )
            for line in ready:
                FulfilmentLine.objects.create(
                    fulfilment=shipment,
                    order_line=line,
                    product_id=line.product_id,
                    quantity=line.qty_reserved,
                    unit_price=line.unit_price,
                )
                line.qty_allocated += line.qty_reserved
                line.qty_reserved = ZERO
                line.save(update_fields=["qty_allocated", "qty_reserved", "updated_at"])
        waiting = any(line.qty_backordered > 0 for line in lines)
        order.backorder_state = Order.BackorderState.OPEN if waiting else Order.BackorderState.NONE
        record(order, OrderEvent.ACCEPT, to=OrderStatus.ACCEPTED, by=by)
        order.status = OrderStatus.ACCEPTED
        order.accepted_at, order.accepted_by = timezone.now(), by
        order.save(
            update_fields=["status", "backorder_state", "accepted_at", "accepted_by", "updated_at"]
        )
        emit("order.accepted", order)
        if order.settings_snapshot.get("orders.send_confirmation_on_accept", True):
            from apps.billing import documents

            documents.create_confirmation(order)  # ADR-046 item 2; its PDF follows
        if ready:
            from apps.billing import invoicing

            if invoicing.timing(order) == "ON_ACCEPTANCE":  # ADR-007
                invoicing.issue_invoice_for_fulfilment(shipment, trigger="ON_ACCEPTANCE", by=by)
    return order


def schedule_auto_accept(order: Order) -> None:
    """⚙ orders.acceptance_mode = AUTO (snapshot): accept after the placing transaction commits."""
    if order.status != OrderStatus.PLACED:
        return
    if order.settings_snapshot.get("orders.acceptance_mode") != "AUTO":
        return
    order_id, tenant_id = order.pk, order.tenant_id

    def run() -> None:
        from common.tenancy import tenant_context

        with tenant_context(tenant_id):
            accept_order(order_id, by=None)

    transaction.on_commit(run)


# --- Reject / cancel before acceptance ---------------------------------------------------------


def _close(order: Order, event: str, to: str, *, by: User | None, reason: str) -> None:
    lines = _lines(order)
    open_lines = {line: _open_quantity(line) for line in lines if _open_quantity(line) > 0}
    if open_lines:
        release_quantities(order, open_lines, to_backorder=False, by=by)
    record(order, event, to=to, by=by, note=reason)
    order.status = to
    order.backorder_state = (
        Order.BackorderState.CLOSED
        if order.backorder_state == Order.BackorderState.OPEN
        else order.backorder_state
    )
    order.closed_at = timezone.now()
    if to == OrderStatus.REJECTED:
        order.rejection_reason = reason[:500]
    else:
        order.cancellation_reason, order.cancelled_by = reason[:500], by
    order.save()


@retry_on_deadlock()
def reject_order(order_id: UUID, *, reason: str, by: User) -> Order:
    """PLACED / ON_HOLD → REJECTED (a reason is required); everything held is released."""
    if not reason.strip():
        raise InvalidFields({"reason": [gettext("Tell the shop why the order is rejected.")]})
    with transaction.atomic():
        order = lock_order(order_id)
        _require(order, OrderStatus.PLACED, OrderStatus.ON_HOLD)
        _close(order, OrderEvent.REJECT, OrderStatus.REJECTED, by=by, reason=reason.strip())
        emit("order.rejected", order, reason=reason.strip())
    return order


@retry_on_deadlock()
def cancel_order(
    order_id: UUID, *, by: User, reason: str = "", retailer_id: UUID | None = None
) -> Order:
    """PLACED / ON_HOLD → CANCELLED, by the shop (its own orders only, ``retailer_id``) or by
    staff. After acceptance only staff can cancel, through ``fulfilment.cancel_accepted``."""
    with transaction.atomic():
        order = lock_order(order_id)
        if retailer_id is not None and order.retailer_id != retailer_id:
            raise NotFound()
        _require(order, OrderStatus.PLACED, OrderStatus.ON_HOLD)
        _close(order, OrderEvent.CANCEL, OrderStatus.CANCELLED, by=by, reason=reason.strip())
        emit("order.cancelled", order, by="retailer" if retailer_id else "staff")
    return order


# --- Modify before acceptance (PLAN B5, ADR-022) -----------------------------------------------


@dataclass(frozen=True)
class Modification:
    quantities: dict[UUID, Decimal]  # order line id → new quantity (0 removes it)
    additions: list[tuple[UUID, Decimal]]  # (product, quantity): FULL_EDIT only
    override_reason: str = ""  # credit.manage: accept a credit breach (audited)


@retry_on_deadlock()
def modify_order(order_id: UUID, change: Modification, *, by: User) -> Order:
    """PLACED → PLACED. REDUCE_ONLY (default): lower or remove lines. FULL_EDIT (snapshot): also
    raise quantities or add products at today's prices; an increase is a new line, so each
    line keeps the price it was ordered at. Credit is re-checked for increases; a breach is
    refused unless a ``credit.manage`` user gives an override reason. The shop is always told."""
    with transaction.atomic():
        order = lock_order(order_id)
        _require(order, OrderStatus.PLACED)
        full_edit = order.settings_snapshot.get("orders.pre_acceptance_edit_mode") == "FULL_EDIT"
        lines = {line.pk: line for line in _lines(order)}
        diff: list[dict[str, str]] = []
        reductions: dict[OrderLine, Decimal] = {}
        increases: list[tuple[UUID, Decimal]] = list(change.additions)
        for line_id, new_qty in change.quantities.items():
            line = lines.get(line_id)
            if line is None:
                raise InvalidFields({"lines": [gettext("That line isn't on this order.")]})
            current = line.qty_ordered - line.qty_cancelled
            if new_qty < 0:
                raise InvalidFields({"lines": [gettext("Quantities can't be negative.")]})
            if line.free_of_line_id is not None and new_qty > current:
                raise InvalidFields(
                    {
                        "lines": [
                            gettext("Free goods follow what is bought: change that line instead.")
                        ]
                    }
                )
            if new_qty < current:
                reductions[line] = current - new_qty
            elif new_qty > current:
                increases.append((line.product_id, new_qty - current))
            if new_qty != current:
                diff.append(
                    {"product": line.product_code, "from": f"{current:f}", "to": f"{new_qty:f}"}
                )
        if increases and not full_edit:
            raise InvalidFields(
                {
                    "lines": [
                        gettext("Only reducing or removing items is allowed before acceptance.")
                    ]
                }
            )
        remaining = sum(
            (line.qty_ordered - line.qty_cancelled - reductions.get(line, ZERO))
            for line in lines.values()
        )
        if remaining + sum((q for _, q in increases), ZERO) <= 0:
            raise InvalidFields(
                {"lines": [gettext("Keep at least one item, or reject the order.")]}
            )
        if reductions:
            release_quantities(order, reductions, to_backorder=False, by=by)
        if increases:
            diff += _add_lines(order, increases, by=by, override_reason=change.override_reason)
        rebalance_free_lines(order, by=by)
        recompute_totals(order, list(OrderLine.objects.filter(order=order)))
        record(order, OrderEvent.MODIFY, to=OrderStatus.PLACED, by=by, payload={"changes": diff})
        emit("order.modified", order, changes=diff)
    return order


def _add_lines(
    order: Order, wanted: list[tuple[UUID, Decimal]], *, by: User, override_reason: str
) -> list[dict[str, str]]:
    rules = order_rules(order.settings_snapshot, order.tenant_id)
    quote = build_quote(
        order.retailer,
        wanted,
        rules=rules,
        stock_rules=ShopStockRules.for_tenant(order.tenant_id),
    )
    credit_codes = ("CREDIT_LIMIT_EXCEEDED", "OVERDUE_INVOICES")
    problems = [p for p in quote.blocking if p.code not in credit_codes]
    if problems:
        raise CartNotReady(details={"problems": _problems(problems)})
    added = quote.totals.grand_total
    # This order's open value is already part of the exposure; only the addition is new.
    status = credit.check(order.retailer, added, breach_action="BLOCK")
    if status.breached:
        if not (override_reason.strip() and by.has_permission_code("credit.manage")):
            raise credit_refusal(status)
        audit.record(
            "credit.override_applied",
            target=order,
            target_repr=order.number,
            metadata={"reason": override_reason.strip(), "added": str(added)},
        )
    levels = stock.lock_levels([line.product_id for line in quote.lines], stock.default_warehouse())
    paid = sorted((x for x in quote.lines if not x.is_free), key=lambda x: x.product_id)
    plan = plan_lines(paid, free_lines_of(quote.lines), levels, rules, drop_short=False)
    next_no = (OrderLine.objects.filter(order=order).count()) + 1
    diff = []
    rows: dict[int, OrderLine] = {}
    for offset, planned in enumerate(plan):
        line = planned.line
        free_of = rows[id(line.free_of)] if line.free_of is not None else None
        row = _create_line(
            order,
            next_no + offset,
            line,
            planned.reserved,
            planned.later,
            planned.cancelled,
            False,
            free_of=free_of,
        )
        rows[id(line)] = row
        level = levels[line.product_id]
        ref = stock.Ref(ReferenceType.ORDER_LINE, row.pk, order.number)
        if planned.reserved:
            stock.reserve(level, planned.reserved, ref, by=by)
        if planned.later:
            stock.change_backordered(level, planned.later)
        if free_of is None:
            diff.append({"product": row.product_code, "from": "0", "to": f"{line.qty:f}"})
    return diff


# --- Credit holds -------------------------------------------------------------------------------


@retry_on_deadlock()
def approve_hold(order_id: UUID, *, by: User) -> Order:
    """ON_HOLD → PLACED (or accepted, with automatic acceptance): parked quantities are now
    reserved or backordered by the normal rules."""
    with transaction.atomic():
        order = lock_order(order_id)
        _require(order, OrderStatus.ON_HOLD)
        # Bought lines before free lines, so free goods take only the stock left (ADR-056).
        lines = sorted(
            (line for line in _lines(order) if line.qty_pending > 0),
            key=lambda line: line.free_of_line_id is not None,
        )
        if lines:
            rules = order_rules(order.settings_snapshot, order.tenant_id)
            levels = _levels(order, lines)
            for line in lines:
                level = levels[line.product_id]
                available = max(level.quantity_on_hand - level.quantity_reserved, ZERO)
                reserve = min(line.qty_pending, available)
                later = line.qty_pending - reserve
                if later and not rules.backorders_enabled:
                    line.qty_cancelled += later  # nothing to wait for: the shop is told
                    later = ZERO
                if reserve:
                    stock.reserve(
                        level,
                        reserve,
                        stock.Ref(ReferenceType.ORDER_LINE, line.pk, order.number),
                        by=by,
                    )
                if later:
                    stock.change_backordered(level, later)
                line.qty_reserved += reserve
                line.qty_backordered += later
                line.qty_pending = ZERO
                line.save()
            rebalance_free_lines(order, by=by)
            recompute_totals(order, list(OrderLine.objects.filter(order=order)))
        # The approval covers the whole order, backorders included (2026-09-28).
        order.credit_approved_value = order.grand_total
        audit.record(
            "credit.hold_approved",
            target=order,
            target_repr=order.number,
            metadata={"approved_value": str(order.credit_approved_value)},
        )
        record(
            order,
            OrderEvent.APPROVE_HOLD,
            to=OrderStatus.PLACED,
            by=by,
            payload={"approved_value": str(order.credit_approved_value)},
        )
        order.status, order.hold_reason = OrderStatus.PLACED, ""
        order.save(update_fields=["status", "hold_reason", "credit_approved_value", "updated_at"])
        emit("order.hold_approved", order)
        schedule_auto_accept(order)
    return order
