"""Placing an order (spec 5.8, PLAN §4.1, ADR-013/044): idempotent, stock reserved or
backordered under the lock, prices and settings snapshotted, credit checked."""

from decimal import Decimal as D
from uuid import uuid4

import pytest
from django.core.cache import cache

from apps.accounts.tests.factories import make_staff_in
from apps.inventory.models import StockLevel, StockMovement
from apps.inventory.tests.helpers import check_invariants, make_product
from apps.orders.models import Cart, Order, OrderLine, OrderLineDiscount, OrderStatusHistory
from apps.orders.tests.helpers import add_address, add_stock, make_shop, settings, shop_client
from apps.pricing.models import DiscountRule
from apps.retailers.models import Retailer
from common.models import OutboxEvent
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1/shop"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def _key():
    return f"k{uuid4().hex}"


def _cart(client, *lines):
    for product, qty in lines:
        response = client.put(f"{API}/cart/lines/{product.pk}/", {"quantity": qty}, format="json")
        assert response.status_code == 200, response.content
    return client.get(f"{API}/cart/").json()


def _place(client, cart, key=None, **extra):
    body = {"expected_total": cart["expected_total"], **extra}
    return client.post(f"{API}/orders/", body, format="json", HTTP_IDEMPOTENCY_KEY=key or _key())


def _level(tenant, product):
    with tenant_context(tenant.pk):
        return StockLevel.objects.get(product=product)


def test_in_stock_and_out_of_stock_items(tenant_a):
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("100"))
    b = make_product(tenant_a, "B", base_price=D("20"))
    add_stock(tenant_a, a, "3")
    client = shop_client(tenant_a, shop)
    cart = _cart(client, (a, "5"), (b, "2"))
    response = _place(client, cart, note="Near the temple, after 4 pm")
    assert response.status_code == 201, response.content
    order = response.json()
    assert order["status"] == "PLACED" and order["number"].startswith("ORD-")
    assert order["number"].endswith("-000001") and order["grand_total"] == cart["expected_total"]
    assert order["retailer_note"] == "Near the temple, after 4 pm"
    assert order["placed_via"] == "RETAILER_APP" and order["placed_by_label"] == ""
    lines = {line["product_code"]: line for line in order["lines"]}
    assert (lines["A"]["qty_reserved"], lines["A"]["qty_backordered"]) == ("3.000", "2.000")
    assert (lines["B"]["qty_reserved"], lines["B"]["qty_backordered"]) == ("0.000", "2.000")
    assert [h["event"] for h in order["history"]] == ["PLACE"]
    level_a, level_b = _level(tenant_a, a), _level(tenant_a, b)
    assert (level_a.quantity_reserved, level_a.quantity_backordered) == (3, 2)
    assert (level_b.quantity_reserved, level_b.quantity_backordered) == (0, 2)
    with tenant_context(tenant_a.pk):
        placed = Order.objects.get()
        assert placed.settings_snapshot["backorders.enabled"] is True
        assert placed.shipping_address["city"] == "Pune"  # the default billing address
        move = StockMovement.objects.get(movement_type="RESERVE")
        assert (move.reference_type, move.reference_number) == ("ORDER_LINE", placed.number)
        assert not Cart.objects.get().lines.exists()  # the cart is emptied
    assert OutboxEvent.objects.filter(event_type="order.placed").count() == 1
    check_invariants(tenant_a)


def test_a_retry_with_the_same_key_returns_the_same_order(tenant_a):
    shop = make_shop(tenant_a)
    product = make_product(tenant_a)
    client = shop_client(tenant_a, shop)
    cart = _cart(client, (product, "2"))
    key = _key()
    first = _place(client, cart, key)
    again = _place(client, cart, key)  # a retry after a dropped connection
    assert first.status_code == again.status_code == 201
    assert again.json()["id"] == first.json()["id"] and again["Idempotent-Replayed"] == "true"
    with tenant_context(tenant_a.pk):
        assert Order.objects.count() == 1
    other_body = _place(client, {"expected_total": "1.00"}, key)
    assert other_body.status_code == 422
    assert other_body.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    missing = client.post(f"{API}/orders/", {"expected_total": "1"}, format="json")
    assert missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_a_price_change_is_caught_and_nothing_is_saved(tenant_a):
    shop = make_shop(tenant_a)
    product = make_product(tenant_a, base_price=D("10"))
    client = shop_client(tenant_a, shop)
    cart = _cart(client, (product, "1"))
    with tenant_context(tenant_a.pk):
        type(product).objects.filter(pk=product.pk).update(base_price=D("12"))
    response = _place(client, cart)
    assert response.status_code == 409
    error = response.json()["error"]
    assert (
        error["code"] == "PRICE_CHANGED" and error["details"]["now"] == "13.00"
    )  # 12.60, to the rupee
    with tenant_context(tenant_a.pk):
        assert not Order.objects.exists()
        assert Cart.objects.get().lines.count() == 1  # the cart is kept


def test_cart_problems_and_empty_carts(tenant_a):
    shop = make_shop(tenant_a)
    product = make_product(tenant_a, min_order_qty=D("6"))
    client = shop_client(tenant_a, shop)
    empty = _place(client, {"expected_total": "0.00"})
    assert empty.status_code == 422
    assert empty.json()["error"]["details"]["problems"][0]["code"] == "CART_EMPTY"
    cart = _cart(client, (product, "2"))
    response = _place(client, cart)
    assert response.status_code == 422 and response.json()["error"]["code"] == "CART_NOT_READY"
    assert response.json()["error"]["details"]["problems"][0]["code"] == "QTY_BELOW_MINIMUM"


def test_backorders_off(tenant_a):
    shop = make_shop(tenant_a)
    product = make_product(tenant_a)
    add_stock(tenant_a, product, "2")
    settings(tenant_a, backorders__enabled=False)
    client = shop_client(tenant_a, shop)
    cart = _cart(client, (product, "5"))
    refused = _place(client, cart)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    settings(tenant_a, orders__insufficient_stock_action="PLACE_AVAILABLE")
    cart = client.get(f"{API}/cart/").json()
    line = _place(client, cart).json()["lines"][0]
    assert (line["qty_reserved"], line["qty_backordered"], line["qty_cancelled"]) == (
        "2.000",
        "0.000",
        "3.000",
    )


def test_credit_hold_block_and_blocked_shops(tenant_a):
    shop = make_shop(tenant_a)
    product = make_product(tenant_a, base_price=D("100"))
    add_stock(tenant_a, product, "10")
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop.pk).update(credit_limit=D("300"))
    client = shop_client(tenant_a, shop)
    held = _place(client, _cart(client, (product, "4"))).json()  # 420 > 300
    assert held["status"] == "ON_HOLD" and held["hold_reason"] == "CREDIT_LIMIT"
    assert held["lines"][0]["qty_reserved"] == "4.000"  # holds reserve stock by default
    assert [h["event"] for h in held["history"]] == ["HOLD"]

    settings(tenant_a, credit__hold_reserves_stock=False)
    parked = _place(client, _cart(client, (product, "1"))).json()  # 420 open + 105 > 300
    assert parked["lines"][0]["qty_pending"] == "1.000"
    assert parked["lines"][0]["qty_reserved"] == "0.000"
    assert _level(tenant_a, product).quantity_reserved == 4

    settings(tenant_a, credit__breach_action="BLOCK")
    blocked = _place(client, _cart(client, (product, "1")))
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "CREDIT_LIMIT_EXCEEDED"
    with tenant_context(tenant_a.pk):
        assert Order.objects.count() == 2
        Retailer.objects.filter(pk=shop.pk).update(credit_limit=None, status="BLOCKED")
    on_hold = _place(client, client.get(f"{API}/cart/").json())
    assert on_hold.status_code == 403 and on_hold.json()["error"]["code"] == "RETAILER_ON_HOLD"
    check_invariants(tenant_a)


def test_every_discount_rule_and_the_address_are_snapshotted(tenant_a):
    from apps.pricing.services import save_discount_rule

    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    product = make_product(tenant_a, base_price=D("100"))
    gujarat = add_address(tenant_a, shop, "24")
    settings(tenant_a, pricing__discount_combination="ADD")
    with tenant_context(tenant_a.pk):
        for name, value in (("Ten off", "10"), ("Two more", "2")):
            save_discount_rule(
                None,
                {
                    "name": name,
                    "discount_type": "PERCENT",
                    "value": D(value),
                    "scope_type": "ALL",
                    "audience_type": "ALL",
                },
                [],
                by=owner,
            )
    client = shop_client(tenant_a, shop)
    cart = _cart(client, (product, "1"))
    order = _place(client, cart, address=str(gujarat.pk)).json()
    assert order["lines"][0]["unit_price"] == "100.00"
    assert order["discount_total"] == "12.00" and order["grand_total"] == "92.00"  # 88 + 5%
    with tenant_context(tenant_a.pk):
        discounts = OrderLineDiscount.objects.order_by("position")
        rows = list(discounts.values_list("rule_name", "amount"))
        # In the order applied: equally specific, so the newest first (ADR-038).
        assert rows == [("Two more", D("2.00")), ("Ten off", D("10.00"))]
        placed = Order.objects.get()
        assert (placed.place_of_supply_id, placed.supply_type) == ("24", "INTER")
        DiscountRule.objects.all().delete()  # later changes never alter the order
        placed.refresh_from_db()
        assert OrderLine.objects.get().discounts.count() == 2
    settings(tenant_a, backorders__enabled=False)
    with tenant_context(tenant_a.pk):
        assert Order.objects.get().settings_snapshot["backorders.enabled"] is True


@covers("shop-orders")
def test_tenant_isolation(tenant_a, tenant_b):
    shop_a = make_shop(tenant_a)
    shop_b = make_shop(tenant_b, "9876500052")
    b_product = make_product(tenant_b, "B-ONLY")
    _cart(shop_client(tenant_b, shop_b), (b_product, "1"))
    client = shop_client(tenant_a, shop_a)
    response = _place(client, {"expected_total": "0.00"})
    assert response.status_code == 422  # shop A's own, empty cart: B's cart is never used
    with tenant_context(tenant_b.pk):
        assert not Order.objects.exists()
    with tenant_context(tenant_a.pk):
        assert not OrderStatusHistory.objects.exists()
