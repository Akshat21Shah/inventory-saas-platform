"""The order state machine before dispatch (PLAN §4.1, B5/B6, ADR-022)."""

from decimal import Decimal as D

import pytest
from django.core.cache import cache

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.inventory.models import StockLevel
from apps.inventory.tests.helpers import check_invariants, make_product
from apps.orders import transitions
from apps.orders.models import Fulfilment, OrderLine
from apps.orders.services import CreditLimitExceeded
from apps.orders.tests.helpers import add_stock, make_shop, place, settings
from apps.orders.transitions import InvalidTransition, Modification
from apps.retailers.models import Retailer
from common.errors import InvalidFields, NotFound
from common.models import OutboxEvent
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def world(tenant_a):
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("100"))
    b = make_product(tenant_a, "B", base_price=D("20"))
    add_stock(tenant_a, a, "3")
    return {
        "tenant": tenant_a,
        "shop": shop,
        "a": a,
        "b": b,
        "owner": make_staff_in(tenant_a, "OWNER"),
    }


def _level(tenant, product):
    with tenant_context(tenant.pk):
        return StockLevel.objects.get(product=product)


def _lines(tenant, order):
    with tenant_context(tenant.pk):
        return {line.product_code: line for line in OrderLine.objects.filter(order=order)}


def test_accept_makes_the_first_shipment_from_reserved_stock(world):
    t, owner = world["tenant"], world["owner"]
    order = place(t, world["shop"], (world["a"], "5"), (world["b"], "2"))
    with tenant_context(t.pk):
        accepted = transitions.accept_order(order.pk, by=owner)
        shipment = Fulfilment.objects.get(order=order)
        assert (shipment.number, shipment.kind, shipment.status) == (
            f"{order.number}/1",
            "INITIAL",
            "ALLOCATED",
        )
        assert [(fl.product.code, fl.quantity) for fl in shipment.lines.all()] == [("A", 3)]
        with pytest.raises(InvalidTransition):
            transitions.accept_order(order.pk, by=owner)
    assert (accepted.status, accepted.backorder_state) == ("ACCEPTED", "OPEN")
    lines = _lines(t, order)
    assert (lines["A"].qty_allocated, lines["A"].qty_reserved, lines["A"].qty_backordered) == (
        3,
        0,
        2,
    )
    assert _level(t, world["a"]).quantity_reserved == 3  # stock stays reserved until dispatch
    assert OutboxEvent.objects.filter(event_type="order.accepted").count() == 1
    check_invariants(t)


def test_an_all_backordered_order_is_accepted_without_a_shipment(world):
    t = world["tenant"]
    order = place(t, world["shop"], (world["b"], "4"))
    with tenant_context(t.pk):
        accepted = transitions.accept_order(order.pk, by=None)  # automatic
        assert not Fulfilment.objects.exists()
    assert accepted.backorder_state == "OPEN"


def test_automatic_acceptance(world, django_capture_on_commit_callbacks):
    t = world["tenant"]
    settings(t, orders__acceptance_mode="AUTO")
    with django_capture_on_commit_callbacks(execute=True):
        order = place(t, world["shop"], (world["a"], "1"))
    with tenant_context(t.pk):
        order.refresh_from_db()
        assert order.status == "ACCEPTED" and order.accepted_by is None
        assert [h.actor_type for h in order.history.all()] == ["RETAILER", "SYSTEM"]


def test_reject_releases_everything(world):
    t, owner = world["tenant"], world["owner"]
    order = place(t, world["shop"], (world["a"], "5"))
    with tenant_context(t.pk):
        with pytest.raises(InvalidFields):
            transitions.reject_order(order.pk, reason=" ", by=owner)
        rejected = transitions.reject_order(order.pk, reason="Wrong item", by=owner)
    assert (rejected.status, rejected.rejection_reason) == ("REJECTED", "Wrong item")
    line = _lines(t, order)["A"]
    assert (line.qty_reserved, line.qty_backordered, line.qty_cancelled) == (0, 0, 5)
    level = _level(t, world["a"])
    assert (level.quantity_reserved, level.quantity_backordered) == (0, 0)
    check_invariants(t)


def test_shops_cancel_only_their_own_orders_before_acceptance(world, tenant_a):
    t, owner = world["tenant"], world["owner"]
    other_shop = make_shop(t, "9876500059")
    order = place(t, world["shop"], (world["a"], "2"))
    with tenant_context(t.pk):
        with pytest.raises(NotFound):
            transitions.cancel_order(order.pk, by=owner, retailer_id=other_shop.pk)
        cancelled = transitions.cancel_order(order.pk, by=owner, retailer_id=world["shop"].pk)
        assert cancelled.status == "CANCELLED"
        second = place(t, world["shop"], (world["a"], "1"))
        transitions.accept_order(second.pk, by=owner)
        with pytest.raises(InvalidTransition):
            transitions.cancel_order(second.pk, by=owner, retailer_id=world["shop"].pk)
    check_invariants(t)


def test_reduce_only_edits(world):
    t, owner = world["tenant"], world["owner"]
    order = place(t, world["shop"], (world["a"], "5"), (world["b"], "2"))
    lines = _lines(t, order)
    with tenant_context(t.pk):
        with pytest.raises(InvalidFields, match="Some fields"):
            transitions.modify_order(order.pk, Modification({lines["B"].pk: D("3")}, []), by=owner)
        changed = transitions.modify_order(
            order.pk, Modification({lines["A"].pk: D("2"), lines["B"].pk: D("0")}, []), by=owner
        )
        with pytest.raises(InvalidFields):
            transitions.modify_order(order.pk, Modification({lines["A"].pk: D("0")}, []), by=owner)
    lines = _lines(t, order)
    # A: 3 reserved + 2 backordered, cut to 2: the waiting quantity goes first, then held stock
    # (PLAN §4.1), so the shop keeps 2 ready to send.
    assert (lines["A"].qty_reserved, lines["A"].qty_backordered, lines["A"].qty_cancelled) == (
        D("2"),
        D("0"),
        D("3"),
    )
    assert lines["B"].qty_cancelled == 2
    assert changed.grand_total == D("210.00")  # 2 x 100 + 5%
    with tenant_context(t.pk):
        history = changed.history.last()
    assert history is not None and history.event == "MODIFY"
    assert history.payload["changes"] == [
        {"product": "A", "from": "5.000", "to": "2"},
        {"product": "B", "from": "2.000", "to": "0"},
    ]
    assert OutboxEvent.objects.filter(event_type="order.modified").count() == 1
    check_invariants(t)


def test_a_small_reduction_only_cancels_waiting_quantity(world):
    t, owner = world["tenant"], world["owner"]
    order = place(t, world["shop"], (world["a"], "5"))  # 3 held, 2 waiting
    line = _lines(t, order)["A"]
    with tenant_context(t.pk):
        transitions.modify_order(order.pk, Modification({line.pk: D("4")}, []), by=owner)
    line = _lines(t, order)["A"]
    assert (line.qty_reserved, line.qty_backordered, line.qty_cancelled) == (
        D("3"),
        D("1"),
        D("1"),
    )
    check_invariants(t)


def test_full_edit_adds_lines_at_todays_price_and_checks_credit(world):
    t, owner = world["tenant"], world["owner"]
    settings(t, orders__pre_acceptance_edit_mode="FULL_EDIT")
    order = place(t, world["shop"], (world["a"], "1"))
    line = _lines(t, order)["A"]
    with tenant_context(t.pk):
        type(world["a"]).objects.filter(pk=world["a"].pk).update(base_price=D("110"))
        changed = transitions.modify_order(
            order.pk, Modification({line.pk: D("2")}, [(world["b"].pk, D("1"))]), by=owner
        )
        rows = list(OrderLine.objects.filter(order=order).order_by("line_no"))
    assert [(r.product_code, r.qty_ordered, r.unit_price) for r in rows] == [
        ("A", D("1"), D("100")),  # keeps the price it was ordered at
        ("A", D("1"), D("110")),  # the increase: today's price
        ("B", D("1"), D("20")),
    ]
    assert changed.grand_total == D("242.00")  # (100 + 110 + 20) + 5% = 241.50, to the rupee
    with tenant_context(t.pk):
        Retailer.objects.filter(pk=world["shop"].pk).update(credit_limit=D("300"))
        with pytest.raises(CreditLimitExceeded):
            transitions.modify_order(
                order.pk, Modification({}, [(world["b"].pk, D("5"))]), by=owner
            )
        sales = make_staff_in(t, "SALES")  # no credit.manage: an override reason isn't enough
        with pytest.raises(CreditLimitExceeded):
            transitions.modify_order(
                order.pk, Modification({}, [(world["b"].pk, D("5"))], "Regular"), by=sales
            )
        transitions.modify_order(
            order.pk, Modification({}, [(world["b"].pk, D("5"))], "Pays on Friday"), by=owner
        )
        assert AuditLog.objects.filter(action="credit.override_applied").count() == 1
    check_invariants(t)


def test_approving_a_hold_that_parked_its_quantities(world):
    t, owner = world["tenant"], world["owner"]
    settings(t, credit__hold_reserves_stock=False)
    with tenant_context(t.pk):
        Retailer.objects.filter(pk=world["shop"].pk).update(credit_limit=D("0"))
    order = place(t, world["shop"], (world["a"], "5"))
    assert order.status == "ON_HOLD"
    assert _level(t, world["a"]).quantity_reserved == 0
    with tenant_context(t.pk):
        approved = transitions.approve_hold(order.pk, by=owner)
        with pytest.raises(InvalidTransition):
            transitions.approve_hold(order.pk, by=owner)
    assert approved.status == "PLACED"
    line = _lines(t, order)["A"]
    assert (line.qty_pending, line.qty_reserved, line.qty_backordered) == (0, 3, 2)
    assert AuditLog.objects.filter(action="credit.hold_approved").exists()
    check_invariants(t)
