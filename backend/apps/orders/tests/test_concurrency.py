"""Real concurrency for orders (PLAN §5.5): threads with their own connections and transactions,
released together. Stock is never oversold or reserved twice, and a duplicate submission never
creates a second order."""

import threading
from collections.abc import Callable
from decimal import Decimal as D
from typing import Any
from uuid import uuid4

import pytest
from django.db import connection

from apps.inventory.availability import ShopStockRules
from apps.inventory.models import StockLevel
from apps.inventory.tests.helpers import check_invariants, make_product
from apps.orders.cart import live_rules
from apps.orders.models import Order, OrderLine
from apps.orders.quote import build_quote
from apps.orders.services import Placement, place_order
from apps.orders.tests.helpers import add_stock, make_shop, shop_client, shop_user
from common.tenancy import tenant_context

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.concurrency]


def parallel(count: int, work: Callable[[int], Any]) -> tuple[list[Any], list[BaseException]]:
    barrier = threading.Barrier(count)
    results: list[Any] = []
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            barrier.wait()
            results.append(work(index))
        except BaseException as exc:  # collected and asserted on by the test
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results, errors


def test_twenty_shops_order_the_last_ten_units(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant, base_price=D("10"))
    add_stock(tenant, product, "10")
    shops = [make_shop(tenant, f"98765{i:05d}") for i in range(20)]
    with tenant_context(tenant.pk):
        quote = build_quote(
            shops[0],
            [(product.pk, D("3"))],
            rules=live_rules(tenant.pk),
            stock_rules=ShopStockRules.for_tenant(tenant.pk),
        )
    total = quote.totals.grand_total

    def order(index: int) -> str:
        shop = shops[index]
        with tenant_context(tenant.pk):
            placed = place_order(
                Placement(
                    retailer=shop,
                    placed_by=shop_user(shop),
                    via="RETAILER_APP",
                    items=[(product.pk, D("3"))],
                    expected_total=total,
                )
            )
        return str(placed.number)

    numbers, errors = parallel(20, order)
    assert errors == []
    assert len(set(numbers)) == 20  # every order its own gap-free number
    with tenant_context(tenant.pk):
        lines = list(OrderLine.objects.all())
        level = StockLevel.objects.get(product=product)
    assert sum(line.qty_reserved for line in lines) == 10  # never oversold
    assert all(line.qty_reserved + line.qty_backordered == 3 for line in lines)
    assert (level.quantity_on_hand, level.quantity_reserved) == (10, 10)
    assert level.quantity_backordered == 50
    check_invariants(tenant)


def test_ten_duplicate_submissions_make_one_order(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    shop = make_shop(tenant)
    clients = [shop_client(tenant, shop) for _ in range(10)]
    cart = (
        clients[0]
        .put(f"/api/v1/shop/cart/lines/{product.pk}/", {"quantity": "2"}, format="json")
        .json()
    )
    key = f"k{uuid4().hex}"

    def submit(index: int) -> tuple[int, str]:
        response = clients[index].post(
            "/api/v1/shop/orders/",
            {"expected_total": cart["expected_total"]},
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        return response.status_code, response.json()["id"]

    results, errors = parallel(10, submit)
    assert errors == []
    assert {status for status, _ in results} == {201}
    assert len({order_id for _, order_id in results}) == 1
    with tenant_context(tenant.pk):
        assert Order.objects.count() == 1


def test_accept_and_cancel_at_the_same_moment(make_tenant):
    """Ten rounds: a shop cancels while staff accept the same order. Exactly one wins; the other
    is told the order moved on, and stock is never left half released."""
    from apps.accounts.tests.factories import make_staff_in
    from apps.orders import transitions
    from apps.orders.tests.helpers import place

    tenant = make_tenant()
    owner = make_staff_in(tenant, "OWNER")
    product = make_product(tenant)
    add_stock(tenant, product, "50")
    shop = make_shop(tenant)
    outcomes = []
    for _ in range(10):
        order = place(tenant, shop, (product, "2"))

        def act(index: int, order_id=order.pk) -> str:
            with tenant_context(tenant.pk):
                if index == 0:
                    transitions.accept_order(order_id, by=owner)
                    return "accepted"
                transitions.cancel_order(order_id, by=shop_user(shop), retailer_id=shop.pk)
                return "cancelled"

        results, errors = parallel(2, act)
        assert len(results) == 1 and len(errors) == 1, (results, errors)
        assert isinstance(errors[0], transitions.InvalidTransition)
        with tenant_context(tenant.pk):
            status = Order.objects.get(pk=order.pk).status
        assert status == {"accepted": "ACCEPTED", "cancelled": "CANCELLED"}[results[0]]
        outcomes.append(results[0])
    with tenant_context(tenant.pk):
        accepted = Order.objects.filter(status="ACCEPTED").count()
        level = StockLevel.objects.get(product=product)
    assert level.quantity_reserved == 2 * accepted  # cancelled orders released theirs
    check_invariants(tenant)


def test_goods_receipt_and_a_new_order_at_the_same_moment(make_tenant):
    """Five rounds (PLAN §5.5, policy B2): a goods receipt arrives while another shop orders the
    same product. Whichever runs first, the accepted order that was waiting gets the stock."""
    from apps.accounts.tests.factories import make_staff_in
    from apps.inventory import receipts
    from apps.orders import transitions
    from apps.orders.tests.helpers import check_order_invariants, place

    tenant = make_tenant()
    owner = make_staff_in(tenant, "OWNER")
    waiting_shop, new_shop = make_shop(tenant, "9876500071"), make_shop(tenant, "9876500072")
    for round_no in range(5):
        product = make_product(tenant, f"R-{round_no}", base_price=D("10"))
        waiting = place(tenant, waiting_shop, (product, "5"))
        with tenant_context(tenant.pk):
            transitions.accept_order(waiting.pk, by=owner)

        def act(index: int, product=product) -> str:
            with tenant_context(tenant.pk):
                if index == 0:
                    receipts.create_and_post(
                        receipts.ReceiptInput(lines=[receipts.LineInput(product.pk, D("5"))]),
                        by=owner,
                    )
                    return "received"
                return str(place(tenant, new_shop, (product, "5")).pk)

        results, errors = parallel(2, act)
        assert errors == [], errors
        new_order_id = next(r for r in results if r != "received")
        with tenant_context(tenant.pk):
            held = OrderLine.objects.get(order=waiting, product=product)
            fresh = OrderLine.objects.get(order_id=new_order_id)
        assert (held.qty_reserved, held.qty_backordered) == (5, 0)
        assert (fresh.qty_reserved, fresh.qty_backordered) == (0, 5)
    check_order_invariants(tenant)


def test_no_deadlock_mixed_operations(make_tenant):
    """PLAN §5.5: for 30 s (MIXED_OPS_SECONDS), six threads place, accept, reject and cancel
    orders, receive goods, confirm and reject backorder proposals, cancel backorders, and pack and
    dispatch shipments, across five products in shuffled order. Only business refusals may
    surface (no deadlocks after retry, no constraint errors), and stock agrees with the orders."""
    import os
    import random
    import time

    from apps.accounts.tests.factories import make_staff_in
    from apps.inventory import receipts
    from apps.orders import backorders, fulfilment, transitions
    from apps.orders.models import BackorderAllocation, Fulfilment
    from apps.orders.tests.helpers import check_order_invariants, place
    from common.errors import DomainError

    seconds = float(os.environ.get("MIXED_OPS_SECONDS", "30"))
    tenant = make_tenant()
    owner = make_staff_in(tenant, "OWNER")
    products = [make_product(tenant, f"M-{i}", base_price=D("10")) for i in range(5)]
    for product in products[:3]:
        add_stock(tenant, product, "8")
    shops = [make_shop(tenant, f"98765001{i:02d}") for i in range(6)]
    done: dict[str, int] = {}
    lock = threading.Lock()

    def pick(queryset: Any) -> Any:
        ids = list(queryset.values_list("pk", flat=True)[:20])
        return random.choice(ids) if ids else None

    def one(index: int, rng: random.Random) -> str:
        shop = shops[index]
        op = rng.choice(
            [
                "place",
                "place",
                "accept",
                "accept",
                "inward",
                "confirm",
                "ship",
                "cancel",
                "reject_order",
                "reject_allocation",
                "cancel_backorder",
            ]
        )
        if op == "place":
            chosen = rng.sample(products, rng.randint(1, 3))
            place(tenant, shop, *[(p, str(rng.randint(1, 4))) for p in chosen])
        elif op == "inward":
            chosen = rng.sample(products, rng.randint(1, 3))
            receipts.create_and_post(
                receipts.ReceiptInput(
                    lines=[receipts.LineInput(p.pk, D(rng.randint(1, 5))) for p in chosen]
                ),
                by=owner,
            )
        elif op in ("accept", "reject_order", "cancel"):
            orders = Order.objects.filter(status="PLACED")
            if op == "cancel":
                orders = orders.filter(retailer=shop)
            order_id = pick(orders)
            if order_id is None:
                return "idle"
            if op == "accept":
                transitions.accept_order(order_id, by=owner)
            elif op == "reject_order":
                transitions.reject_order(order_id, reason="Mixed test", by=owner)
            else:
                transitions.cancel_order(order_id, by=shop_user(shop), retailer_id=shop.pk)
        elif op in ("confirm", "reject_allocation"):
            allocation_id = pick(BackorderAllocation.objects.filter(status="PROPOSED"))
            if allocation_id is None:
                return "idle"
            if op == "confirm":
                backorders.confirm([allocation_id], by=owner)
            else:
                backorders.reject(allocation_id, by=owner)
        elif op == "cancel_backorder":
            line_id = pick(OrderLine.objects.filter(qty_backordered__gt=0))
            if line_id is None:
                return "idle"
            backorders.cancel_backorder(line_id, by=owner)
        else:  # ship
            shipment_id = pick(Fulfilment.objects.filter(status="ALLOCATED"))
            if shipment_id is None:
                return "idle"
            fulfilment.pack(shipment_id, {}, by=owner)
            fulfilment.dispatch(shipment_id, fulfilment.Transport("", "", ""), by=owner)
        return op

    def work(index: int) -> int:
        rng = random.Random(index)
        count = 0
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            with tenant_context(tenant.pk):
                try:
                    op = one(index, rng)
                except DomainError as exc:  # business refusals are fine: the state moved on
                    op = f"refused:{type(exc).__name__}"
            with lock:
                done[op] = done.get(op, 0) + 1
            count += 1
        return count

    results, errors = parallel(6, work)
    assert errors == [], errors
    assert sum(results) > 50, done
    for op in ("place", "accept", "inward", "confirm", "ship"):
        assert done.get(op, 0) > 0, done
    check_order_invariants(tenant)
