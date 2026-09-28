"""The server cart (spec 5.8, PLAN §3.9, §5.3): prices, tax estimate, what can be sent now and
later, problems to fix and the credit note, all from the server."""

from decimal import Decimal as D

import pytest
from django.core.cache import cache

from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_address, add_stock, make_shop, settings, shop_client
from apps.retailers.models import Retailer
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1/shop"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def _set(client, product, qty):
    response = client.put(f"{API}/cart/lines/{product.pk}/", {"quantity": qty}, format="json")
    assert response.status_code == 200, response.content
    return response.json()


def test_prices_tax_and_the_backorder_split_come_from_the_server(tenant_a):
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("100.00"))
    b = make_product(tenant_a, "B", base_price=D("20.00"))
    add_stock(tenant_a, a, "3")
    client = shop_client(tenant_a, shop)
    _set(client, a, "5")
    cart = _set(client, b, "2")
    lines = {line["product"]["code"]: line for line in cart["lines"]}
    assert (lines["A"]["ready_qty"], lines["A"]["later_qty"]) == ("3.000", "2.000")
    assert (lines["B"]["ready_qty"], lines["B"]["later_qty"]) == ("0.000", "2.000")
    assert lines["A"]["unit_price"] == "100.00" and lines["A"]["line_total"] == "525.00"  # 5% GST
    assert cart["totals"] == {
        "gross": "540.00",
        "discount": "0.00",
        "taxable": "540.00",
        "tax": "27.00",
        "round_off": "0.00",
        "grand_total": "567.00",
    }
    assert cart["expected_total"] == "567.00" and cart["item_count"] == 2
    assert cart["can_place"] is True and cart["problems"] == []
    assert cart["credit"] == {"limit": None, "available": None, "outcome": "OK", "reason": ""}
    # 0 removes the line; DELETE does the same; clearing empties the cart.
    assert len(_set(client, b, "0")["lines"]) == 1
    assert client.delete(f"{API}/cart/lines/{a.pk}/").json()["lines"] == []
    _set(client, a, "1")
    assert client.delete(f"{API}/cart/").json()["item_count"] == 0


def test_minimums_multiples_and_unavailable_products_are_reported(tenant_a):
    shop = make_shop(tenant_a)
    boxed = make_product(tenant_a, "BOX", min_order_qty=D("6"), order_multiple=D("6"))
    gone = make_product(tenant_a, "GONE")
    client = shop_client(tenant_a, shop)
    _set(client, gone, "1")
    with tenant_context(tenant_a.pk):
        type(gone).objects.filter(pk=gone.pk).update(show_in_shop=False)

    def codes(cart):
        return {
            line["product"]["code"]: [p["code"] for p in line["problems"]] for line in cart["lines"]
        }

    cart = _set(client, boxed, "4")
    assert codes(cart) == {"BOX": ["QTY_BELOW_MINIMUM"], "GONE": ["PRODUCT_UNAVAILABLE"]}
    assert cart["can_place"] is False
    assert codes(_set(client, boxed, "8"))["BOX"] == ["QTY_NOT_MULTIPLE"]
    assert codes(_set(client, boxed, "12"))["BOX"] == []
    assert (
        client.put(f"{API}/cart/lines/{boxed.pk}/", {"quantity": "1.5"}, format="json").status_code
        == 400
    )


def test_backorders_off_fail_or_place_available(tenant_a):
    shop = make_shop(tenant_a)
    product = make_product(tenant_a)
    add_stock(tenant_a, product, "2")
    settings(tenant_a, backorders__enabled=False)
    client = shop_client(tenant_a, shop)
    cart = _set(client, product, "5")
    assert cart["lines"][0]["problems"] == [
        {"code": "NOT_ENOUGH_STOCK", "details": {"available": "2.000"}, "blocking": True}
    ]
    assert cart["can_place"] is False and cart["backorders_enabled"] is False
    reduced = client.post(f"{API}/cart/reduce-to-available/").json()
    assert reduced["lines"][0]["quantity"] == "2.000" and reduced["can_place"] is True
    settings(tenant_a, orders__insufficient_stock_action="PLACE_AVAILABLE")
    cart = _set(client, product, "5")
    assert cart["lines"][0]["problems"][0]["code"] == "PARTLY_AVAILABLE"
    assert cart["can_place"] is True


def test_minimum_order_value_counts_backordered_items(tenant_a):
    shop = make_shop(tenant_a)
    product = make_product(tenant_a, base_price=D("100"))
    settings(tenant_a, orders__min_order_value="500")
    client = shop_client(tenant_a, shop)
    cart = _set(client, product, "4")  # 420 incl. GST, nothing in stock
    assert cart["problems"][0] == {
        "code": "MIN_ORDER_VALUE",
        "details": {"minimum": "500.00", "basis": "INCL_GST"},
        "blocking": True,
    }
    assert _set(client, product, "5")["can_place"] is True  # 525, all on backorder


def test_credit_note_and_blocked_shops(tenant_a):
    shop = make_shop(tenant_a)
    product = make_product(tenant_a, base_price=D("100"))
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop.pk).update(credit_limit=D("300"))
    client = shop_client(tenant_a, shop)
    cart = _set(client, product, "4")  # 420 > 300
    assert cart["credit"] == {
        "limit": "300.00",
        "available": "300.00",
        "outcome": "NEEDS_APPROVAL",
        "reason": "CREDIT_LIMIT",
    }
    assert cart["problems"] == [
        {"code": "CREDIT_APPROVAL_NEEDED", "details": {"reason": "CREDIT_LIMIT"}, "blocking": False}
    ]
    assert cart["can_place"] is True  # it goes on hold for approval
    settings(tenant_a, credit__breach_action="BLOCK")
    cart = client.get(f"{API}/cart/").json()
    assert cart["credit"]["outcome"] == "BLOCKED" and cart["can_place"] is False
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop.pk).update(credit_limit=None, status="BLOCKED")
    cart = client.get(f"{API}/cart/").json()
    assert [p["code"] for p in cart["problems"]] == ["RETAILER_ON_HOLD"]


def test_the_delivery_address_decides_the_tax_type(tenant_a):
    shop = make_shop(tenant_a)
    product = make_product(tenant_a, base_price=D("100"))
    client = shop_client(tenant_a, shop)
    cart = _set(client, product, "1")
    billing_id = cart["address_id"]
    gujarat = add_address(tenant_a, shop, "24")
    addresses = client.get(f"{API}/addresses/").json()
    assert addresses[0]["id"] == str(gujarat.pk)  # default shipping first
    assert client.get(f"{API}/cart/").json()["address_id"] == str(gujarat.pk)
    maharashtra = client.get(f"{API}/cart/", {"address": billing_id}).json()
    assert maharashtra["address_id"] == billing_id
    # Same total either way at 5%; the split (CGST+SGST vs IGST) is the invoice's business.
    assert maharashtra["totals"]["grand_total"] == "105.00"


@covers("shop-cart", "shop-cart-line", "shop-cart-reduce", "shop-addresses")
def test_tenant_isolation(tenant_a, tenant_b):
    shop_a = make_shop(tenant_a)
    shop_b = make_shop(tenant_b, "9876500052")
    other = make_product(tenant_b, "B-ONLY")
    mine = make_product(tenant_a, "A-ONLY")
    client = shop_client(tenant_a, shop_a)
    foreign = client.put(f"{API}/cart/lines/{other.pk}/", {"quantity": "1"}, format="json")
    assert foreign.status_code == 404
    _set(client, mine, "1")
    b_address = add_address(tenant_b, shop_b, "24")
    assert all(a["id"] != str(b_address.pk) for a in client.get(f"{API}/addresses/").json())
    # Another shop's address is never used: the cart falls back to this shop's own.
    assert client.get(f"{API}/cart/", {"address": str(b_address.pk)}).json()["address_id"] is None
    assert shop_client(tenant_b, shop_b).get(f"{API}/cart/").json()["lines"] == []
    assert client.post(f"{API}/cart/reduce-to-available/").status_code == 200
