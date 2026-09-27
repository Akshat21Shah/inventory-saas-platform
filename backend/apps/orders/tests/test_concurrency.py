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
