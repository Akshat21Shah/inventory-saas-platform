"""Shipments (PLAN §4.2, ADR-006/007/044): pack with short packs, dispatch, deliver, cancel
before dispatch, and the order status derived from its shipments."""

from decimal import Decimal as D

import pytest
from django.core.cache import cache

from apps.accounts.tests.factories import make_staff_in
from apps.inventory.models import StockLevel, StockMovement
from apps.inventory.tests.helpers import check_invariants, make_product
from apps.orders import fulfilment, transitions
from apps.orders.fulfilment import Transport
from apps.orders.models import Fulfilment, Order, OrderLine
from apps.orders.tests.helpers import add_stock, make_shop, place, settings
from apps.orders.transitions import InvalidTransition
from common.errors import InvalidFields
from common.models import OutboxEvent
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def accepted(tenant_a):
    """An accepted order: A 5 in stock (shipment #1), B 2 on backorder."""
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("100"))
    b = make_product(tenant_a, "B")
    add_stock(tenant_a, a, "10")
    owner = make_staff_in(tenant_a, "OWNER")
    order = place(tenant_a, shop, (a, "5"), (b, "2"))
    with tenant_context(tenant_a.pk):
        transitions.accept_order(order.pk, by=owner)
        shipment = Fulfilment.objects.get(order=order)
    return {
        "tenant": tenant_a,
        "order": order,
        "shipment": shipment,
        "a": a,
        "b": b,
        "owner": owner,
    }


def _state(tenant, order):
    with tenant_context(tenant.pk):
        o = Order.objects.get(pk=order.pk)
        lines = {line.product_code: line for line in OrderLine.objects.filter(order=order)}
        return o, lines


def _level(tenant, product):
    with tenant_context(tenant.pk):
        return StockLevel.objects.get(product=product)


def test_pack_dispatch_deliver(accepted):
    t, owner, shipment = accepted["tenant"], accepted["owner"], accepted["shipment"]
    with tenant_context(t.pk):
        fulfilment.pack(shipment.pk, {}, by=owner)  # everything packed
        order, _ = _state(t, accepted["order"])
        assert order.status == "PACKED"
        with pytest.raises(InvalidTransition):
            fulfilment.deliver(shipment.pk, by=owner)
        fulfilment.dispatch(
            shipment.pk, Transport("MH12AB1234", "Speed Logistics", "LR-9"), by=owner
        )
        shipment.refresh_from_db()
        assert (shipment.vehicle_number, shipment.lr_number) == ("MH12AB1234", "LR-9")
        sale = StockMovement.objects.get(movement_type="SALE")
        assert (sale.quantity, sale.reference_type) == (5, "FULFILMENT")
    order, lines = _state(t, accepted["order"])
    assert order.status == "DISPATCHED" and lines["A"].qty_dispatched == 5
    level = _level(t, accepted["a"])
    assert (level.quantity_on_hand, level.quantity_reserved) == (5, 0)
    with tenant_context(t.pk):
        fulfilment.deliver(shipment.pk, by=owner)
    order, lines = _state(t, accepted["order"])
    # Delivered, but B still waits on backorder: not completed yet.
    assert (order.status, order.backorder_state) == ("DELIVERED", "OPEN")
    assert lines["A"].qty_delivered == 5
    check_invariants(t)


def test_completed_when_everything_is_delivered_and_nothing_waits(tenant_a):
    shop = make_shop(tenant_a)
    a = make_product(tenant_a)
    add_stock(tenant_a, a, "3")
    owner = make_staff_in(tenant_a, "OWNER")
    order = place(tenant_a, shop, (a, "3"))
    with tenant_context(tenant_a.pk):
        transitions.accept_order(order.pk, by=owner)
        shipment = Fulfilment.objects.get(order=order)
        fulfilment.pack(shipment.pk, {}, by=owner)
        fulfilment.dispatch(shipment.pk, Transport(), by=owner)
        fulfilment.deliver(shipment.pk, by=owner)
    order, _ = _state(tenant_a, order)
    assert order.status == "COMPLETED" and order.closed_at is not None
    assert OutboxEvent.objects.filter(event_type="order.completed").count() == 1


@pytest.mark.parametrize("backorders_on", [True, False])
def test_a_short_pack_goes_back_on_backorder_or_is_cancelled(accepted, backorders_on):
    t, owner, shipment = accepted["tenant"], accepted["owner"], accepted["shipment"]
    if not backorders_on:
        with tenant_context(t.pk):  # the order's snapshot decides, not today's setting
            Order.objects.filter(pk=accepted["order"].pk).update(
                settings_snapshot={
                    **accepted["order"].settings_snapshot,
                    "backorders.enabled": False,
                }
            )
    settings(t, backorders__enabled=not backorders_on)  # the opposite, to prove it is ignored
    with tenant_context(t.pk):
        line = shipment.lines.get()
        with pytest.raises(InvalidFields):
            fulfilment.pack(shipment.pk, {line.pk: D("6")}, by=owner)
        fulfilment.pack(shipment.pk, {line.pk: D("3")}, by=owner)
    _, lines = _state(t, accepted["order"])
    a = lines["A"]
    assert a.qty_allocated == 3
    if backorders_on:
        assert (a.qty_backordered, a.qty_cancelled) == (2, 0)
        assert _level(t, accepted["a"]).quantity_backordered == 2
    else:
        assert (a.qty_backordered, a.qty_cancelled) == (0, 2)
    assert _level(t, accepted["a"]).quantity_reserved == 3
    assert OutboxEvent.objects.filter(event_type="order.short_supplied").count() == 1
    check_invariants(t)


def test_packing_nothing_cancels_the_shipment(accepted):
    t, owner, shipment = accepted["tenant"], accepted["owner"], accepted["shipment"]
    with tenant_context(t.pk):
        line = shipment.lines.get()
        fulfilment.pack(shipment.pk, {line.pk: D("0")}, by=owner)
        shipment.refresh_from_db()
    assert shipment.status == "CANCELLED"
    order, lines = _state(t, accepted["order"])
    assert order.status == "ACCEPTED" and lines["A"].qty_backordered == 5


def test_cancel_a_shipment_or_the_whole_order_before_dispatch(accepted):
    t, owner, shipment = accepted["tenant"], accepted["owner"], accepted["shipment"]
    with tenant_context(t.pk):
        fulfilment.cancel_shipment(shipment.pk, to_backorder=True, reason="Truck full", by=owner)
    _, lines = _state(t, accepted["order"])
    assert (lines["A"].qty_allocated, lines["A"].qty_backordered) == (0, 5)
    with tenant_context(t.pk):
        cancelled = fulfilment.cancel_accepted(accepted["order"].pk, reason="Shop closed", by=owner)
    assert (cancelled.status, cancelled.backorder_state) == ("CANCELLED", "CLOSED")
    _, lines = _state(t, accepted["order"])
    assert all(line.qty_cancelled == line.qty_ordered for line in lines.values())
    level = _level(t, accepted["a"])
    assert (level.quantity_reserved, level.quantity_backordered) == (0, 0)
    check_invariants(t)


def test_nothing_is_cancelled_once_dispatched(accepted):
    t, owner, shipment = accepted["tenant"], accepted["owner"], accepted["shipment"]
    with tenant_context(t.pk):
        fulfilment.pack(shipment.pk, {}, by=owner)
        fulfilment.dispatch(shipment.pk, Transport(), by=owner)
        with pytest.raises(InvalidTransition):
            fulfilment.cancel_accepted(accepted["order"].pk, reason="late", by=owner)
        with pytest.raises(InvalidTransition):
            fulfilment.cancel_shipment(shipment.pk, to_backorder=False, reason="x", by=owner)
