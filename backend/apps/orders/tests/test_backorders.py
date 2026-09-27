"""Backorder allocation (PLAN §4.3, §5.2, ADR-014/021): FIFO over accepted orders, inside the
stock increase's transaction; proposals hold stock; credit re-check; AUTO or CONFIRM; billing
price ORIGINAL or CURRENT with the shop's right to decline a higher price; cancelling what still
waits; manual allocation."""

from decimal import Decimal as D

import pytest
from django.core.cache import cache

from apps.accounts.tests.factories import make_staff_in
from apps.inventory import adjustments, receipts
from apps.inventory.adjustments import AdjustmentInput, AdjustmentLineInput
from apps.inventory.models import StockLevel
from apps.inventory.tests.helpers import make_product
from apps.orders import backorders, fulfilment, transitions
from apps.orders.models import BackorderAllocation, Fulfilment, FulfilmentLine, Order, OrderLine
from apps.orders.services import CreditLimitExceeded
from apps.orders.tests.helpers import (
    add_stock,
    check_order_invariants,
    make_shop,
    place,
    settings,
    shop_user,
)
from apps.orders.transitions import InvalidTransition
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
def ctx(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    a = make_product(tenant_a, "A", base_price=D("100"))
    b = make_product(tenant_a, "B", base_price=D("50"))
    return {"t": tenant_a, "owner": owner, "a": a, "b": b}


def _waiting_order(ctx, shop, *lines, accept=True):
    """An order whose lines all wait (no stock), accepted by default."""
    order = place(ctx["t"], shop, *lines)
    if accept:
        with tenant_context(ctx["t"].pk):
            transitions.accept_order(order.pk, by=ctx["owner"])
    return order


def _receive(ctx, *lines):
    with tenant_context(ctx["t"].pk):
        return receipts.create_and_post(
            receipts.ReceiptInput(lines=[receipts.LineInput(p.pk, D(q)) for p, q in lines]),
            by=ctx["owner"],
        )


def _line(ctx, order, product):
    with tenant_context(ctx["t"].pk):
        return OrderLine.objects.get(order=order, product=product)


def _allocations(ctx, **filters):
    with tenant_context(ctx["t"].pk):
        return list(BackorderAllocation.objects.filter(**filters).order_by("created_at"))


def _level(ctx, product):
    with tenant_context(ctx["t"].pk):
        return StockLevel.objects.get(product=product)


def test_goods_receipt_proposes_to_the_waiting_order_and_holds_the_stock(ctx):
    shop = make_shop(ctx["t"])
    order = _waiting_order(ctx, shop, (ctx["a"], "4"))
    assert _line(ctx, order, ctx["a"]).qty_backordered == 4
    grn = _receive(ctx, (ctx["a"], "10"))

    [proposal] = _allocations(ctx)
    assert (proposal.status, proposal.trigger, proposal.quantity) == ("PROPOSED", "INWARD", 4)
    assert proposal.source_id == grn.pk
    line = _line(ctx, order, ctx["a"])
    assert (line.qty_backordered, line.qty_reserved) == (0, 4)
    level = _level(ctx, ctx["a"])
    assert (level.quantity_on_hand, level.quantity_reserved, level.quantity_backordered) == (
        10,
        4,
        0,
    )
    with tenant_context(ctx["t"].pk):
        assert OutboxEvent.objects.filter(event_type="backorder.proposed").count() == 1
        assert not Fulfilment.objects.filter(kind="BACKORDER").exists()  # CONFIRM mode waits
    check_order_invariants(ctx["t"])

    with tenant_context(ctx["t"].pk):
        [shipment] = backorders.confirm([proposal.pk], by=ctx["owner"])
        order.refresh_from_db()
    assert (shipment.kind, shipment.number) == ("BACKORDER", f"{order.number}/1")
    line = _line(ctx, order, ctx["a"])
    assert (line.qty_reserved, line.qty_allocated) == (0, 4)
    assert (order.status, order.backorder_state) == ("ACCEPTED", "CLOSED")
    with tenant_context(ctx["t"].pk):
        fl = FulfilmentLine.objects.get(fulfilment=shipment)
        assert (fl.unit_price, fl.price_source, fl.price_increased) == (
            D("100.00"),
            "ORDER_SNAPSHOT",
            False,
        )
        assert order.history.filter(event="BACKORDER_ALLOCATED").exists()
        with pytest.raises(InvalidTransition):  # decided once
            backorders.confirm([proposal.pk], by=ctx["owner"])
    check_order_invariants(ctx["t"])


def test_fifo_oldest_accepted_order_first_and_placed_orders_wait(ctx):
    first = _waiting_order(ctx, make_shop(ctx["t"], "9876500061"), (ctx["a"], "3"))
    second = _waiting_order(ctx, make_shop(ctx["t"], "9876500062"), (ctx["a"], "3"))
    not_accepted = _waiting_order(
        ctx, make_shop(ctx["t"], "9876500063"), (ctx["a"], "3"), accept=False
    )
    _receive(ctx, (ctx["a"], "4"))
    assert _line(ctx, first, ctx["a"]).qty_reserved == 3
    second_line = _line(ctx, second, ctx["a"])
    assert (second_line.qty_reserved, second_line.qty_backordered) == (1, 2)
    placed_line = _line(ctx, not_accepted, ctx["a"])
    assert (placed_line.qty_reserved, placed_line.qty_backordered) == (0, 3)
    check_order_invariants(ctx["t"])


def test_auto_mode_makes_one_shipment_per_order(ctx):
    settings(ctx["t"], backorders__allocation_mode="AUTO")
    order = _waiting_order(ctx, make_shop(ctx["t"]), (ctx["a"], "2"), (ctx["b"], "5"))
    _receive(ctx, (ctx["a"], "2"), (ctx["b"], "5"))
    with tenant_context(ctx["t"].pk):
        [shipment] = Fulfilment.objects.filter(order=order, kind="BACKORDER")
        assert shipment.lines.count() == 2
        assert {a.status for a in BackorderAllocation.objects.all()} == {"CONFIRMED"}
        assert OutboxEvent.objects.filter(event_type="backorder.allocated").count() == 1
        order.refresh_from_db()
    assert order.backorder_state == "CLOSED"
    check_order_invariants(ctx["t"])


def test_stock_added_by_adjustment_serves_backorders_but_removal_does_not(ctx):
    order = _waiting_order(ctx, make_shop(ctx["t"]), (ctx["a"], "2"), (ctx["b"], "2"))
    add_stock(ctx["t"], ctx["b"], "5")  # a direct primitive: no allocation
    with tenant_context(ctx["t"].pk):
        adjustments.create_adjustment(
            AdjustmentInput(
                reason_code="COUNT_CORRECTION",
                note="Found in the back",
                lines=[
                    AdjustmentLineInput(ctx["a"].pk, "ADD", D("5")),
                    AdjustmentLineInput(ctx["b"].pk, "REMOVE", D("1")),
                ],
            ),
            by=ctx["owner"],
        )
    [proposal] = _allocations(ctx)
    assert (proposal.product_id, proposal.trigger) == (ctx["a"].pk, "ADJUSTMENT_IN")
    assert _line(ctx, order, ctx["b"]).qty_backordered == 2
    check_order_invariants(ctx["t"])


def test_reject_offers_the_stock_to_the_next_in_line(ctx, django_capture_on_commit_callbacks):
    first = _waiting_order(ctx, make_shop(ctx["t"], "9876500061"), (ctx["a"], "3"))
    second = _waiting_order(ctx, make_shop(ctx["t"], "9876500062"), (ctx["a"], "3"))
    _receive(ctx, (ctx["a"], "3"))
    [proposal] = _allocations(ctx)
    with tenant_context(ctx["t"].pk), django_capture_on_commit_callbacks(execute=True):
        backorders.reject(proposal.pk, by=ctx["owner"])
    first_line = _line(ctx, first, ctx["a"])
    assert (first_line.qty_reserved, first_line.qty_backordered) == (0, 3)  # keeps its place
    assert _line(ctx, second, ctx["a"]).qty_reserved == 3
    assert [a.status for a in _allocations(ctx)] == ["REJECTED", "PROPOSED"]
    check_order_invariants(ctx["t"])


def test_freed_stock_from_a_cancelled_order_serves_the_backorder(
    ctx, django_capture_on_commit_callbacks
):
    add_stock(ctx["t"], ctx["a"], "3")
    holder = place(ctx["t"], make_shop(ctx["t"], "9876500061"), (ctx["a"], "3"))
    waiting = _waiting_order(ctx, make_shop(ctx["t"], "9876500062"), (ctx["a"], "2"))
    assert _line(ctx, waiting, ctx["a"]).qty_backordered == 2
    with tenant_context(ctx["t"].pk), django_capture_on_commit_callbacks(execute=True):
        transitions.reject_order(holder.pk, reason="Duplicate", by=ctx["owner"])
    [proposal] = _allocations(ctx)
    assert (proposal.trigger, proposal.quantity) == ("RELEASE", 2)
    assert _line(ctx, waiting, ctx["a"]).qty_reserved == 2
    check_order_invariants(ctx["t"])


def test_shop_over_credit_limit_is_skipped_and_flagged_once(ctx):
    over = make_shop(ctx["t"], "9876500061")
    fine = make_shop(ctx["t"], "9876500062")
    first = _waiting_order(ctx, over, (ctx["a"], "3"))
    second = _waiting_order(ctx, fine, (ctx["a"], "3"))
    with tenant_context(ctx["t"].pk):
        Retailer.objects.filter(pk=over.pk).update(credit_limit=D("100"))  # exposure 315
    _receive(ctx, (ctx["a"], "3"))
    _receive(ctx, (ctx["a"], "1"))
    skipped = _allocations(ctx, status="SKIPPED_CREDIT")
    assert len(skipped) == 1 and skipped[0].order_line_id == _line(ctx, first, ctx["a"]).pk
    assert _line(ctx, first, ctx["a"]).qty_backordered == 3
    assert _line(ctx, second, ctx["a"]).qty_reserved == 3
    with tenant_context(ctx["t"].pk):
        assert OutboxEvent.objects.filter(event_type="backorder.skipped_credit").count() == 1
    check_order_invariants(ctx["t"])


class TestCurrentBillingPrice:
    @pytest.fixture
    def repriced(self, ctx):
        settings(ctx["t"], backorders__billing_price="CURRENT")
        shop = make_shop(ctx["t"])
        order = _waiting_order(ctx, shop, (ctx["a"], "2"))
        with tenant_context(ctx["t"].pk):
            ctx["a"].base_price = D("120")
            ctx["a"].save(update_fields=["base_price"])
        _receive(ctx, (ctx["a"], "5"))
        [proposal] = _allocations(ctx)
        with tenant_context(ctx["t"].pk):
            [shipment] = backorders.confirm([proposal.pk], by=ctx["owner"])
            fl = FulfilmentLine.objects.get(fulfilment=shipment)
        return {**ctx, "shop": shop, "order": order, "shipment": shipment, "fl": fl}

    def test_higher_price_is_flagged(self, repriced):
        fl = repriced["fl"]
        assert (fl.unit_price, fl.price_source, fl.price_increased) == (
            D("120.00"),
            "REPRICED",
            True,
        )
        with tenant_context(repriced["t"].pk):
            event = OutboxEvent.objects.get(event_type="backorder.allocated")
        assert event.payload["price_increased"] == ["A"]

    def test_shop_declines_the_higher_price(self, repriced, django_capture_on_commit_callbacks):
        other = make_shop(repriced["t"], "9876500099")
        with tenant_context(repriced["t"].pk):
            with pytest.raises(NotFound):
                backorders.cancel_repriced(
                    repriced["fl"].pk, by=shop_user(other), retailer_id=other.pk
                )
            with django_capture_on_commit_callbacks(execute=True):
                backorders.cancel_repriced(
                    repriced["fl"].pk,
                    by=shop_user(repriced["shop"]),
                    retailer_id=repriced["shop"].pk,
                )
            repriced["shipment"].refresh_from_db()
            order = Order.objects.get(pk=repriced["order"].pk)
        assert repriced["shipment"].status == "CANCELLED"
        line = _line(repriced, repriced["order"], repriced["a"])
        assert (line.qty_allocated, line.qty_cancelled) == (0, 2)
        assert order.status == "CANCELLED"  # nothing left to send
        assert _level(repriced, repriced["a"]).quantity_reserved == 0
        with tenant_context(repriced["t"].pk), pytest.raises(InvalidTransition):
            backorders.cancel_repriced(
                repriced["fl"].pk, by=shop_user(repriced["shop"]), retailer_id=repriced["shop"].pk
            )
        check_order_invariants(repriced["t"])

    def test_no_declining_once_packed(self, repriced):
        with tenant_context(repriced["t"].pk):
            fulfilment.pack(repriced["shipment"].pk, {}, by=repriced["owner"])
            with pytest.raises(InvalidTransition):
                backorders.cancel_repriced(
                    repriced["fl"].pk,
                    by=shop_user(repriced["shop"]),
                    retailer_id=repriced["shop"].pk,
                )

    def test_confirm_rechecks_credit_at_todays_price(self, ctx):
        settings(ctx["t"], backorders__billing_price="CURRENT")
        shop = make_shop(ctx["t"])
        _waiting_order(ctx, shop, (ctx["a"], "2"))  # 210 incl. GST
        with tenant_context(ctx["t"].pk):
            # 4.00 more before GST fits; 4.20 with it doesn't
            Retailer.objects.filter(pk=shop.pk).update(credit_limit=D("214.10"))
        _receive(ctx, (ctx["a"], "2"))
        [proposal] = _allocations(ctx)
        with tenant_context(ctx["t"].pk):
            ctx["a"].base_price = D("102")
            ctx["a"].save(update_fields=["base_price"])
            with pytest.raises(CreditLimitExceeded):
                backorders.confirm([proposal.pk], by=ctx["owner"])


def test_original_price_can_not_be_declined(ctx):
    shop = make_shop(ctx["t"])
    _waiting_order(ctx, shop, (ctx["a"], "2"))
    _receive(ctx, (ctx["a"], "2"))
    [proposal] = _allocations(ctx)
    with tenant_context(ctx["t"].pk):
        [shipment] = backorders.confirm([proposal.pk], by=ctx["owner"])
        fl = FulfilmentLine.objects.get(fulfilment=shipment)
        with pytest.raises(InvalidTransition):
            backorders.cancel_repriced(fl.pk, by=shop_user(shop), retailer_id=shop.pk)


def test_cancel_what_still_waits(ctx):
    add_stock(ctx["t"], ctx["a"], "2")
    shop = make_shop(ctx["t"])
    order = _waiting_order(ctx, shop, (ctx["a"], "5"))
    line = _line(ctx, order, ctx["a"])
    assert (line.qty_backordered, _level(ctx, ctx["a"]).quantity_backordered) == (3, 3)
    other = make_shop(ctx["t"], "9876500099")
    with tenant_context(ctx["t"].pk):
        with pytest.raises(NotFound):
            backorders.cancel_backorder(line.pk, by=shop_user(other), retailer_id=other.pk)
        backorders.cancel_backorder(line.pk, by=shop_user(shop), retailer_id=shop.pk)
        with pytest.raises(InvalidFields):
            backorders.cancel_backorder(line.pk, by=ctx["owner"])
        order.refresh_from_db()
        assert order.history.filter(event="BACKORDER_CANCELLED").exists()
    line = _line(ctx, order, ctx["a"])
    assert (line.qty_backordered, line.qty_cancelled, line.qty_allocated) == (0, 3, 2)
    assert order.backorder_state == "CLOSED"
    assert _level(ctx, ctx["a"]).quantity_backordered == 0
    check_order_invariants(ctx["t"])


def test_manual_allocation_in_any_order(ctx):
    first = _waiting_order(ctx, make_shop(ctx["t"], "9876500061"), (ctx["a"], "3"))
    second = _waiting_order(ctx, make_shop(ctx["t"], "9876500062"), (ctx["a"], "3"))
    add_stock(ctx["t"], ctx["a"], "4")  # no allocation run: the stock is free
    second_line = _line(ctx, second, ctx["a"])
    with tenant_context(ctx["t"].pk):
        with pytest.raises(InvalidFields):  # more than is free
            backorders.allocate_manually(
                ctx["a"].pk,
                {second_line.pk: D("3"), _line(ctx, first, ctx["a"]).pk: D("3")},
                by=ctx["owner"],
            )
        with pytest.raises(InvalidFields):  # more than the line waits for
            backorders.allocate_manually(ctx["a"].pk, {second_line.pk: D("4")}, by=ctx["owner"])
        [shipment] = backorders.allocate_manually(
            ctx["a"].pk, {second_line.pk: D("3")}, by=ctx["owner"]
        )
    assert shipment.order_id == second.pk
    [allocation] = _allocations(ctx)
    assert (allocation.trigger, allocation.status) == ("MANUAL", "CONFIRMED")
    assert _line(ctx, second, ctx["a"]).qty_allocated == 3
    assert _line(ctx, first, ctx["a"]).qty_backordered == 3
    check_order_invariants(ctx["t"])


def test_backorder_shipment_goes_through_to_completion(ctx):
    add_stock(ctx["t"], ctx["a"], "2")
    order = _waiting_order(ctx, make_shop(ctx["t"]), (ctx["a"], "5"))
    _receive(ctx, (ctx["a"], "3"))
    [proposal] = _allocations(ctx)
    with tenant_context(ctx["t"].pk):
        backorders.confirm([proposal.pk], by=ctx["owner"])
        for shipment in Fulfilment.objects.filter(order=order).order_by("number"):
            fulfilment.pack(shipment.pk, {}, by=ctx["owner"])
            fulfilment.dispatch(shipment.pk, fulfilment.Transport("", "", ""), by=ctx["owner"])
            fulfilment.deliver(shipment.pk, by=ctx["owner"])
        order.refresh_from_db()
    assert order.status == "COMPLETED"
    check_order_invariants(ctx["t"])


def test_other_tenants_backorders_are_untouched(ctx, tenant_b):
    order = _waiting_order(ctx, make_shop(ctx["t"]), (ctx["a"], "2"))
    b_owner = make_staff_in(tenant_b, "OWNER")
    b_product = make_product(tenant_b, "A", base_price=D("100"))
    with tenant_context(tenant_b.pk):
        receipts.create_and_post(
            receipts.ReceiptInput(lines=[receipts.LineInput(b_product.pk, D("5"))]), by=b_owner
        )
    assert _line(ctx, order, ctx["a"]).qty_backordered == 2
    with tenant_context(tenant_b.pk):
        assert not BackorderAllocation.objects.exists()
    [proposal] = [*_allocations(ctx)] or [None]
    assert proposal is None
    with tenant_context(tenant_b.pk), pytest.raises(NotFound):
        backorders.cancel_backorder(_line(ctx, order, ctx["a"]).pk, by=b_owner)


def test_cancelling_an_accepted_order_ends_its_proposals(ctx):
    order = _waiting_order(ctx, make_shop(ctx["t"]), (ctx["a"], "3"))
    _receive(ctx, (ctx["a"], "3"))
    [proposal] = _allocations(ctx)
    with tenant_context(ctx["t"].pk):
        fulfilment.cancel_accepted(order.pk, reason="Shop closed", by=ctx["owner"])
        proposal.refresh_from_db()
        assert proposal.status == "REJECTED"
        with pytest.raises(InvalidTransition):
            backorders.confirm([proposal.pk], by=ctx["owner"])
    assert _level(ctx, ctx["a"]).quantity_reserved == 0
    check_order_invariants(ctx["t"])


# --- Product-owner decisions of 2026-09-28 -------------------------------------------------------


def _approved_over_limit(ctx, shop, *lines):
    """A shop over its limit whose held order was approved, accepted, and now waits."""
    with tenant_context(ctx["t"].pk):
        Retailer.objects.filter(pk=shop.pk).update(credit_limit=D("100"))
    order = place(ctx["t"], shop, *lines)
    assert order.status == "ON_HOLD"
    with tenant_context(ctx["t"].pk):
        transitions.approve_hold(order.pk, by=ctx["owner"])
        transitions.accept_order(order.pk, by=ctx["owner"])
        order.refresh_from_db()
    return order


class TestApprovedFromACreditHold:
    def test_approval_records_the_value_and_covers_the_backorders(self, ctx):
        order = _approved_over_limit(ctx, make_shop(ctx["t"]), (ctx["a"], "2"))
        assert order.credit_approved_value == D("210.00")  # 2 x 100 + 5%, all waiting
        _receive(ctx, (ctx["a"], "2"))
        [allocation] = _allocations(ctx)
        assert allocation.status == "PROPOSED"  # not skipped: the approval covers it
        check_order_invariants(ctx["t"])

    def test_a_higher_current_price_is_checked_against_the_limit(self, ctx):
        settings(ctx["t"], backorders__billing_price="CURRENT")
        order = _approved_over_limit(ctx, make_shop(ctx["t"]), (ctx["a"], "2"))
        with tenant_context(ctx["t"].pk):
            ctx["a"].base_price = D("110")
            ctx["a"].save(update_fields=["base_price"])
        _receive(ctx, (ctx["a"], "2"))
        [allocation] = _allocations(ctx)
        assert allocation.status == "SKIPPED_CREDIT"  # the extra 21.00 wasn't approved
        assert _line(ctx, order, ctx["a"]).qty_backordered == 2

    def test_other_orders_of_the_shop_are_still_checked(self, ctx):
        shop = make_shop(ctx["t"])
        _approved_over_limit(ctx, shop, (ctx["a"], "1"))
        with tenant_context(ctx["t"].pk):
            Retailer.objects.filter(pk=shop.pk).update(credit_limit=None)
        other = _waiting_order(ctx, shop, (ctx["b"], "2"))
        with tenant_context(ctx["t"].pk):
            Retailer.objects.filter(pk=shop.pk).update(credit_limit=D("100"))
        _receive(ctx, (ctx["b"], "2"))
        [allocation] = _allocations(ctx, product=ctx["b"])
        assert allocation.status == "SKIPPED_CREDIT"
        assert _line(ctx, other, ctx["b"]).qty_backordered == 2


class TestBlockedShops:
    def _block(self, ctx, shop):
        from apps.retailers.services import block_retailer

        with tenant_context(ctx["t"].pk):
            block_retailer(shop.pk, reason="Overdue", by=ctx["owner"])

    def test_skipped_and_flagged_once_and_the_next_shop_served(self, ctx):
        blocked = make_shop(ctx["t"], "9876500061")
        first = _waiting_order(ctx, blocked, (ctx["a"], "2"))
        second = _waiting_order(ctx, make_shop(ctx["t"], "9876500062"), (ctx["a"], "2"))
        self._block(ctx, blocked)
        _receive(ctx, (ctx["a"], "2"))
        _receive(ctx, (ctx["a"], "1"))
        skipped = _allocations(ctx, status="SKIPPED_BLOCKED")
        assert [a.order_line_id for a in skipped] == [_line(ctx, first, ctx["a"]).pk]
        assert _line(ctx, second, ctx["a"]).qty_reserved == 2
        with tenant_context(ctx["t"].pk):
            assert OutboxEvent.objects.filter(event_type="backorder.skipped_blocked").count() == 1
        check_order_invariants(ctx["t"])

    def test_never_by_hand_or_by_confirming_an_older_proposal(self, ctx):
        from apps.orders.services import RetailerOnHold

        shop = make_shop(ctx["t"])
        order = _waiting_order(ctx, shop, (ctx["a"], "4"))
        _receive(ctx, (ctx["a"], "2"))
        [proposal] = _allocations(ctx)
        self._block(ctx, shop)
        add_stock(ctx["t"], ctx["a"], "2")
        line = _line(ctx, order, ctx["a"])
        with tenant_context(ctx["t"].pk):
            with pytest.raises(RetailerOnHold) as refused:
                backorders.confirm([proposal.pk], by=ctx["owner"])
            assert refused.value.status_code == 409
            with pytest.raises(RetailerOnHold):
                backorders.allocate_manually(
                    ctx["a"].pk, {line.pk: D("2")}, by=ctx["owner"], override_reason="Urgent"
                )
        check_order_invariants(ctx["t"])


class TestManualAllocationCredit:
    def _over_limit(self, ctx):
        shop = make_shop(ctx["t"])
        order = _waiting_order(ctx, shop, (ctx["a"], "2"))  # 210 waiting
        with tenant_context(ctx["t"].pk):
            Retailer.objects.filter(pk=shop.pk).update(credit_limit=D("100"))
        add_stock(ctx["t"], ctx["a"], "2")
        return order, _line(ctx, order, ctx["a"])

    def test_refused_without_credit_manage(self, ctx):
        order, line = self._over_limit(ctx)
        warehouse = make_staff_in(ctx["t"], "WAREHOUSE")
        with tenant_context(ctx["t"].pk), pytest.raises(CreditLimitExceeded) as refused:
            backorders.allocate_manually(
                ctx["a"].pk, {line.pk: D("2")}, by=warehouse, override_reason="Please"
            )
        assert refused.value.details["can_override"] is False
        assert "Someone who manages credit" in refused.value.message
        assert _line(ctx, order, ctx["a"]).qty_backordered == 2

    def test_credit_manage_overrides_with_a_reason_audited(self, ctx):
        from apps.audit.models import AuditLog

        order, line = self._over_limit(ctx)
        with tenant_context(ctx["t"].pk):
            with pytest.raises(CreditLimitExceeded) as refused:
                backorders.allocate_manually(ctx["a"].pk, {line.pk: D("2")}, by=ctx["owner"])
            assert refused.value.details["can_override"] is True
            [shipment] = backorders.allocate_manually(
                ctx["a"].pk,
                {line.pk: D("2")},
                by=ctx["owner"],
                override_reason="Paid in cash today",
            )
            audit = AuditLog.objects.get(action="credit.override_applied")
        assert shipment.order_id == order.pk
        assert audit.metadata == {
            "reason": "Paid in cash today",
            "action": "backorder_allocation",
        }
        [allocation] = _allocations(ctx)
        assert allocation.note == "Credit override: Paid in cash today"
        check_order_invariants(ctx["t"])

    def test_an_order_approved_from_a_hold_needs_no_override(self, ctx):
        order = _approved_over_limit(ctx, make_shop(ctx["t"]), (ctx["a"], "2"))
        add_stock(ctx["t"], ctx["a"], "2")
        warehouse = make_staff_in(ctx["t"], "WAREHOUSE")
        with tenant_context(ctx["t"].pk):
            [shipment] = backorders.allocate_manually(
                ctx["a"].pk, {_line(ctx, order, ctx["a"]).pk: D("2")}, by=warehouse
            )
        assert shipment.order_id == order.pk
