"""The shop's orders (PLAN §3.9, ADR-044): list, detail, cancel, repeat, cancelling what still
waits or a higher backorder price, checkout attempts after a dropped connection, and home.
Another shop, in this tenant or another, sees and changes nothing."""

from decimal import Decimal as D
from uuid import uuid4

import pytest
from django.core.cache import cache

from apps.accounts.tests.factories import make_staff_in
from apps.inventory import receipts
from apps.inventory.tests.helpers import make_product
from apps.orders import backorders, transitions
from apps.orders.models import FulfilmentLine, Order, OrderLine
from apps.orders.tests.helpers import (
    add_stock,
    check_order_invariants,
    make_shop,
    place,
    settings,
    shop_client,
    staff_client,
)
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


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("100"))
    b = make_product(tenant_a, "B", base_price=D("50"))
    add_stock(tenant_a, a, "10")
    client = shop_client(tenant_a, shop)
    client.default_format = "json"
    return {"t": tenant_a, "owner": owner, "shop": shop, "a": a, "b": b, "client": client}


def _accept(world, order):
    with tenant_context(world["t"].pk):
        transitions.accept_order(order.pk, by=world["owner"])


def test_list_and_detail(world):
    first = place(world["t"], world["shop"], (world["a"], "1"))
    second = place(world["t"], world["shop"], (world["a"], "2"), (world["b"], "1"))
    with tenant_context(world["t"].pk):
        transitions.reject_order(first.pk, reason="Duplicate", by=world["owner"])
    client = world["client"]
    rows = client.get(f"{API}/orders/").json()["results"]
    assert [row["id"] for row in rows] == [str(second.pk), str(first.pk)]  # newest first
    assert rows[0]["line_count"] == 2
    assert [r["id"] for r in client.get(f"{API}/orders/?state=open").json()["results"]] == [
        str(second.pk)
    ]
    assert [r["id"] for r in client.get(f"{API}/orders/?state=closed").json()["results"]] == [
        str(first.pk)
    ]
    assert client.get(f"{API}/orders/?state=soon").status_code == 400
    body = client.get(f"{API}/orders/{first.pk}/").json()
    assert (body["status"], body["rejection_reason"]) == ("REJECTED", "Duplicate")
    assert [h["event"] for h in body["history"]] == ["PLACE", "REJECT"]
    assert "by" not in body["history"][1]  # the shop isn't told which staff member did it


def test_staff_placed_orders_say_who(world):
    sales = make_staff_in(world["t"], "SALES")
    sales.full_name = "Priya"
    sales.save(update_fields=["full_name"])
    order = place(world["t"], world["shop"], (world["a"], "1"), via="STAFF", by=sales)
    row = world["client"].get(f"{API}/orders/").json()["results"][0]
    assert (row["id"], row["placed_by_label"]) == (str(order.pk), "Priya (Sales)")


def test_cancel_before_acceptance_only(world):
    placed = place(world["t"], world["shop"], (world["a"], "2"))
    accepted = place(world["t"], world["shop"], (world["a"], "2"))
    _accept(world, accepted)
    client = world["client"]
    body = client.post(f"{API}/orders/{placed.pk}/cancel/", {"reason": "Ordered twice"}).json()
    assert (body["status"], body["cancellation_reason"]) == ("CANCELLED", "Ordered twice")
    refused = client.post(f"{API}/orders/{accepted.pk}/cancel/", {})
    assert (refused.status_code, refused.json()["error"]["code"]) == (
        409,
        "INVALID_STATE_TRANSITION",
    )
    check_order_invariants(world["t"])


def test_repeat_adds_to_the_cart_and_reports_what_is_gone(world):
    order = place(world["t"], world["shop"], (world["a"], "2"), (world["b"], "3"))
    with tenant_context(world["t"].pk):
        type(world["b"]).objects.filter(pk=world["b"].pk).update(show_in_shop=False)
    client = world["client"]
    client.put(f"{API}/cart/lines/{world['a'].pk}/", {"quantity": "1"})
    body = client.post(f"{API}/orders/{order.pk}/repeat/").json()
    assert [(line["product_id"], line["quantity"]) for line in body["cart"]["lines"]] == [
        (str(world["a"].pk), "3.000")
    ]
    assert body["skipped"] == [{"product_id": str(world["b"].pk), "name": "Product B"}]


def test_cancel_what_still_waits(world):
    order = place(world["t"], world["shop"], (world["a"], "1"), (world["b"], "3"))
    _accept(world, order)
    with tenant_context(world["t"].pk):
        line = OrderLine.objects.get(order=order, product=world["b"])
    client = world["client"]
    body = client.post(f"{API}/order-lines/{line.pk}/cancel-backorder/").json()
    assert body["backorder_state"] == "CLOSED"
    [b_line] = [x for x in body["lines"] if x["product_code"] == "B"]
    assert (b_line["qty_backordered"], b_line["qty_cancelled"]) == ("0.000", "3.000")
    assert client.post(f"{API}/order-lines/{line.pk}/cancel-backorder/").status_code == 400


def test_decline_a_higher_backorder_price(world):
    settings(world["t"], backorders__billing_price="CURRENT")
    order = place(world["t"], world["shop"], (world["b"], "2"))
    _accept(world, order)
    with tenant_context(world["t"].pk):
        world["b"].base_price = D("60")
        world["b"].save(update_fields=["base_price"])
        receipts.create_and_post(
            receipts.ReceiptInput(lines=[receipts.LineInput(world["b"].pk, D("2"))]),
            by=world["owner"],
        )
        [proposal] = order.lines.get().allocations.all()
        backorders.confirm([proposal.pk], by=world["owner"])
    client = world["client"]
    detail = client.get(f"{API}/orders/{order.pk}/").json()
    [shipment] = detail["fulfilments"]
    [fl] = shipment["lines"]
    assert (fl["unit_price"], fl["ordered_price"], fl["price_increased"]) == (
        "60.00",
        "50.00",
        True,
    )
    body = client.post(f"{API}/fulfilment-lines/{fl['id']}/cancel-repriced/").json()
    assert body["fulfilments"][0]["status"] == "CANCELLED"
    assert body["status"] == "CANCELLED"
    check_order_invariants(world["t"])


class TestCheckoutAttempts:
    def test_placed_or_not_found(self, world):
        client = world["client"]
        cart = client.put(f"{API}/cart/lines/{world['a'].pk}/", {"quantity": "1"}).json()
        key = f"k{uuid4().hex}"
        missing = client.get(f"{API}/checkout-attempts/{key}/").json()
        assert missing == {"status": "not_found", "order": None, "number": None}
        placed = client.post(
            f"{API}/orders/",
            {"expected_total": cart["expected_total"]},
            HTTP_IDEMPOTENCY_KEY=key,
        ).json()
        found = client.get(f"{API}/checkout-attempts/{key}/").json()
        assert found == {"status": "placed", "order": placed["id"], "number": placed["number"]}
        # A retry with the same key returns the same order, never a second one.
        again = client.post(
            f"{API}/orders/",
            {"expected_total": cart["expected_total"]},
            HTTP_IDEMPOTENCY_KEY=key,
        )
        assert (again.status_code, again.json()["id"]) == (201, placed["id"])
        with tenant_context(world["t"].pk):
            assert Order.objects.count() == 1
        assert client.get(f"{API}/checkout-attempts/not a key/").status_code == 400

    def test_a_refused_attempt_leaves_nothing(self, world):
        client = world["client"]
        client.put(f"{API}/cart/lines/{world['a'].pk}/", {"quantity": "1"})
        key = f"k{uuid4().hex}"
        refused = client.post(
            f"{API}/orders/", {"expected_total": "1.00"}, HTTP_IDEMPOTENCY_KEY=key
        )
        assert refused.json()["error"]["code"] == "PRICE_CHANGED"
        assert client.get(f"{API}/checkout-attempts/{key}/").json()["status"] == "not_found"


def test_home(world):
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=world["shop"].pk).update(credit_limit=D("1000"))
    older = place(world["t"], world["shop"], (world["a"], "1"))
    last = place(world["t"], world["shop"], (world["b"], "4"), (world["a"], "2"))
    _accept(world, last)
    body = world["client"].get(f"{API}/home/").json()
    assert [row["id"] for row in body["recent_orders"]] == [str(last.pk), str(older.pk)]
    assert body["last_order"]["number"] == last.number
    items = body["last_order"]["items"]
    assert [(i["code"], i["last_quantity"]) for i in items] == [("A", "2.000"), ("B", "4.000")]
    assert items[1]["price"]["unit_price"] == "50.00"
    assert items[0]["availability"]["status"]
    assert (body["open_orders"], body["waiting_items"]) == (2, 1)
    # Open orders count against credit: 105 + 420 (GST included).
    assert body["credit"] == {"limit": "1000.00", "available": "475.00"}


def test_home_for_a_new_shop(world):
    body = world["client"].get(f"{API}/home/").json()
    assert body["recent_orders"] == [] and body["last_order"] is None
    assert body["credit"] == {"limit": None, "available": None}


@covers(
    "shop-home",
    "shop-order",
    "shop-order-cancel",
    "shop-order-repeat",
    "shop-order-line-cancel-backorder",
    "shop-fulfilment-line-cancel-repriced",
    "shop-checkout-attempt",
)
def test_other_shops_see_and_change_nothing(world, tenant_b):
    settings(world["t"], backorders__billing_price="CURRENT")
    order = place(world["t"], world["shop"], (world["a"], "1"), (world["b"], "4"))
    _accept(world, order)
    with tenant_context(world["t"].pk):
        world["b"].base_price = D("60")
        world["b"].save(update_fields=["base_price"])
        receipts.create_and_post(
            receipts.ReceiptInput(lines=[receipts.LineInput(world["b"].pk, D("2"))]),
            by=world["owner"],
        )
        line = OrderLine.objects.get(order=order, product=world["b"])
        [proposal] = line.allocations.all()
        backorders.confirm([proposal.pk], by=world["owner"])
        fl = FulfilmentLine.objects.get(order_line=line)
    key = f"k{uuid4().hex}"
    neighbour = shop_client(world["t"], make_shop(world["t"], "9876500098"))
    outsider = shop_client(tenant_b, make_shop(tenant_b, "9876500099"))
    for client in (neighbour, outsider):
        client.default_format = "json"
        assert client.get(f"{API}/orders/").json()["results"] == []
        home = client.get(f"{API}/home/").json()
        assert home["recent_orders"] == [] and home["last_order"] is None
        assert client.get(f"{API}/orders/{order.pk}/").status_code == 404
        for url in (
            f"{API}/orders/{order.pk}/cancel/",
            f"{API}/orders/{order.pk}/repeat/",
            f"{API}/order-lines/{line.pk}/cancel-backorder/",
            f"{API}/fulfilment-lines/{fl.pk}/cancel-repriced/",
        ):
            assert client.post(url, {}).status_code == 404, url
        assert client.get(f"{API}/checkout-attempts/{key}/").json()["status"] == "not_found"
    staff = staff_client(world["t"])
    assert staff.get(f"{API}/orders/{order.pk}/").status_code == 403  # staff use their own API
    with tenant_context(world["t"].pk):
        order.refresh_from_db()
        line.refresh_from_db()
        fl.refresh_from_db()
    assert (order.status, line.qty_backordered, fl.cancelled_by_retailer_at) == (
        "ACCEPTED",
        2,
        None,
    )
