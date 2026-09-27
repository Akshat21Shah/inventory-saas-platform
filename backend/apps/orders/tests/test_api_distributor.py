"""The distributor's order, shipment and backorder APIs (PLAN §3.8, ADR-044): tabs and counts,
actions through the API, roles, sales visibility, ordering on a shop's behalf, and tenant
isolation for every route."""

from decimal import Decimal as D
from uuid import uuid4

import pytest
from django.core.cache import cache

from apps.accounts.tests.factories import make_staff_in
from apps.inventory import receipts
from apps.inventory.tests.helpers import make_product
from apps.orders import transitions
from apps.orders.models import BackorderAllocation, Fulfilment, Order, OrderLine
from apps.orders.tests.helpers import (
    add_stock,
    check_order_invariants,
    client_for,
    make_shop,
    place,
    settings,
    shop_client,
)
from apps.retailers.models import Retailer
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def key() -> dict[str, str]:
    return {"HTTP_IDEMPOTENCY_KEY": f"k{uuid4().hex}"}


def code(response) -> str:
    return str(response.json()["error"]["code"])


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a, shop_name="Ganesh Traders")
    a = make_product(tenant_a, "A", base_price=D("100"))
    b = make_product(tenant_a, "B", base_price=D("50"))
    add_stock(tenant_a, a, "10")
    return {"t": tenant_a, "owner": owner, "shop": shop, "a": a, "b": b}


def staff(world, role: str):
    user = make_staff_in(world["t"], role)
    client = client_for(world["t"], user)
    client.default_format = "json"
    return user, client


def accepted_with_backorder(world, shop=None):
    """A accepted: 2 of A shipped from stock (shipment #1), 3 of B waiting."""
    order = place(world["t"], shop or world["shop"], (world["a"], "2"), (world["b"], "3"))
    with tenant_context(world["t"].pk):
        transitions.accept_order(order.pk, by=world["owner"])
    return order


class TestBoard:
    def test_tabs_and_counts(self, world):
        new = place(world["t"], world["shop"], (world["a"], "1"))
        waiting = accepted_with_backorder(world)
        with tenant_context(world["t"].pk):
            Retailer.objects.filter(pk=world["shop"].pk).update(credit_limit=D("0"))
        held = place(world["t"], world["shop"], (world["a"], "1"))
        rejected = place(world["t"], make_shop(world["t"], "9876500099"), (world["a"], "1"))
        with tenant_context(world["t"].pk):
            transitions.reject_order(rejected.pk, reason="Duplicate", by=world["owner"])
        _, client = staff(world, "OWNER")

        def ids(tab: str) -> set[str]:
            response = client.get(f"/api/v1/orders/?tab={tab}")
            assert response.status_code == 200, response.json()
            return {row["id"] for row in response.json()["results"]}

        assert ids("new") == {str(new.pk)}
        assert ids("on_hold") == {str(held.pk)}
        assert ids("backorders") == {str(waiting.pk)}
        assert ids("in_progress") == {str(waiting.pk)}
        assert ids("completed") == {str(rejected.pk)}
        assert client.get("/api/v1/orders/?tab=nope").status_code == 400
        counts = client.get("/api/v1/orders/counts/").json()
        assert counts == {
            "new": 1,
            "on_hold": 1,
            "backorders": 1,
            "in_progress": 1,
            "proposals": 0,
            "to_pack": 1,
        }
        row = client.get("/api/v1/orders/?tab=new").json()["results"][0]
        assert (row["retailer_name"], row["line_count"], row["number"]) == (
            "Ganesh Traders",
            1,
            new.number,
        )

    def test_filters(self, world):
        other = make_shop(world["t"], "9876500098", shop_name="Laxmi Stores")
        mine = place(world["t"], world["shop"], (world["a"], "1"))
        theirs = place(world["t"], other, (world["a"], "1"))
        _, client = staff(world, "OWNER")
        by_shop = client.get(f"/api/v1/orders/?retailer={other.pk}").json()["results"]
        assert [row["id"] for row in by_shop] == [str(theirs.pk)]
        found = client.get("/api/v1/orders/?search=laxmi").json()["results"]
        assert [row["id"] for row in found] == [str(theirs.pk)]
        found = client.get(f"/api/v1/orders/?search={mine.number}").json()["results"]
        assert [row["id"] for row in found] == [str(mine.pk)]
        day = mine.placed_at.date().isoformat()
        assert len(client.get(f"/api/v1/orders/?placed_from={day}").json()["results"]) == 2
        assert client.get("/api/v1/orders/?placed_to=2020-01-01").json()["results"] == []
        assert client.get("/api/v1/orders/?placed_to=soon").status_code == 400

    def test_detail_has_lines_shipments_and_history(self, world):
        order = accepted_with_backorder(world)
        _, client = staff(world, "WAREHOUSE")
        body = client.get(f"/api/v1/orders/{order.pk}/").json()
        assert [line["product_code"] for line in body["lines"]] == ["A", "B"]
        [shipment] = body["fulfilments"]
        assert (shipment["number"], shipment["kind"], shipment["status"]) == (
            f"{order.number}/1",
            "INITIAL",
            "ALLOCATED",
        )
        assert shipment["lines"][0]["quantity"] == "2.000"
        assert [h["event"] for h in body["history"]] == ["PLACE", "ACCEPT"]


class TestOrderActions:
    def test_accept_is_idempotent_and_needs_orders_manage(self, world):
        order = place(world["t"], world["shop"], (world["a"], "2"))
        _, warehouse = staff(world, "WAREHOUSE")
        assert warehouse.post(f"/api/v1/orders/{order.pk}/accept/", **key()).status_code == 403
        _, sales = staff(world, "SALES")
        assert sales.post(f"/api/v1/orders/{order.pk}/accept/").status_code == 400  # no key
        headers = key()
        first = sales.post(f"/api/v1/orders/{order.pk}/accept/", **headers)
        again = sales.post(f"/api/v1/orders/{order.pk}/accept/", **headers)
        assert first.status_code == again.status_code == 200
        assert again["Idempotent-Replayed"] == "true"
        assert first.json()["status"] == "ACCEPTED"
        refused = sales.post(f"/api/v1/orders/{order.pk}/accept/", **key())
        assert (refused.status_code, code(refused)) == (409, "INVALID_STATE_TRANSITION")

    def test_reject_needs_a_reason(self, world):
        order = place(world["t"], world["shop"], (world["a"], "2"))
        _, client = staff(world, "OWNER")
        assert client.post(f"/api/v1/orders/{order.pk}/reject/", {}).status_code == 400
        response = client.post(f"/api/v1/orders/{order.pk}/reject/", {"reason": "No route"})
        assert (response.json()["status"], response.json()["rejection_reason"]) == (
            "REJECTED",
            "No route",
        )

    def test_cancel_before_and_after_acceptance(self, world):
        placed = place(world["t"], world["shop"], (world["a"], "1"))
        accepted = accepted_with_backorder(world)
        _, client = staff(world, "OWNER")
        for order in (placed, accepted):
            response = client.post(f"/api/v1/orders/{order.pk}/cancel/", {"reason": "Shop asked"})
            assert response.json()["status"] == "CANCELLED", response.json()
        check_order_invariants(world["t"])

    def test_modify_reduces_before_acceptance(self, world):
        order = place(world["t"], world["shop"], (world["a"], "4"), (world["b"], "1"))
        with tenant_context(world["t"].pk):
            line = OrderLine.objects.get(order=order, product=world["a"])
        _, client = staff(world, "OWNER")
        response = client.patch(
            f"/api/v1/orders/{order.pk}/lines/",
            {"lines": [{"line": str(line.pk), "quantity": "1"}]},
            format="json",
        )
        assert response.status_code == 200, response.json()
        [a_line] = [x for x in response.json()["lines"] if x["product_code"] == "A"]
        assert (a_line["qty_cancelled"], a_line["qty_reserved"]) == ("3.000", "1.000")
        refused = client.patch(
            f"/api/v1/orders/{order.pk}/lines/",
            {"additions": [{"product": str(world["b"].pk), "quantity": "1"}]},
            format="json",
        )
        assert refused.status_code == 400  # REDUCE_ONLY by default

    def test_credit_holds_need_credit_manage(self, world):
        with tenant_context(world["t"].pk):
            Retailer.objects.filter(pk=world["shop"].pk).update(credit_limit=D("0"))
        first = place(world["t"], world["shop"], (world["a"], "1"))
        second = place(world["t"], world["shop"], (world["a"], "1"))
        _, sales = staff(world, "SALES")
        assert sales.post(f"/api/v1/orders/{first.pk}/hold/approve/").status_code == 403
        _, accounts = staff(world, "ACCOUNTS")
        assert accounts.post(f"/api/v1/orders/{first.pk}/hold/approve/").json()["status"] in (
            "PLACED",
            "ACCEPTED",
        )
        response = accounts.post(f"/api/v1/orders/{second.pk}/hold/reject/", {"reason": "Overdue"})
        assert response.json()["status"] == "REJECTED"
        again = accounts.post(f"/api/v1/orders/{first.pk}/hold/reject/", {"reason": "x"})
        assert again.status_code == 409


class TestShipments:
    def test_pack_short_dispatch_deliver_by_warehouse(self, world):
        order = place(world["t"], world["shop"], (world["a"], "4"))
        with tenant_context(world["t"].pk):
            transitions.accept_order(order.pk, by=world["owner"])
            shipment = Fulfilment.objects.get(order=order)
        _, sales = staff(world, "SALES")
        assert sales.post(f"/api/v1/fulfilments/{shipment.pk}/pack/", {}).status_code == 403
        _, client = staff(world, "WAREHOUSE")
        queue = client.get("/api/v1/fulfilments/?status=ALLOCATED").json()["results"]
        assert [row["id"] for row in queue] == [str(shipment.pk)]
        line_id = client.get(f"/api/v1/fulfilments/{shipment.pk}/").json()["lines"][0]["id"]
        packed = client.post(
            f"/api/v1/fulfilments/{shipment.pk}/pack/",
            {"lines": [{"line": line_id, "quantity": "3"}]},
            format="json",
        ).json()
        assert (packed["status"], packed["lines"][0]["qty_packed"]) == ("PACKED", "3.000")
        sent = client.post(
            f"/api/v1/fulfilments/{shipment.pk}/dispatch/",
            {"vehicle_number": "MH12AB1234", "transporter_name": "", "lr_number": "LR-1"},
            format="json",
        ).json()
        assert (sent["status"], sent["vehicle_number"]) == ("DISPATCHED", "MH12AB1234")
        done = client.post(f"/api/v1/fulfilments/{shipment.pk}/deliver/").json()
        assert done["status"] == "DELIVERED"
        body = client.get(f"/api/v1/orders/{order.pk}/").json()
        assert (body["status"], body["backorder_state"]) == ("DELIVERED", "OPEN")  # 1 waits
        check_order_invariants(world["t"])

    def test_cancel_a_shipment_back_to_backorder(self, world):
        order = accepted_with_backorder(world)
        with tenant_context(world["t"].pk):
            shipment = Fulfilment.objects.get(order=order)
        _, warehouse = staff(world, "WAREHOUSE")
        body = {"to_backorder": True, "reason": "Damaged in the godown"}
        assert warehouse.post(f"/api/v1/fulfilments/{shipment.pk}/cancel/", body).status_code == 403
        _, client = staff(world, "OWNER")
        response = client.post(f"/api/v1/fulfilments/{shipment.pk}/cancel/", body)
        assert response.json()["status"] == "CANCELLED"
        with tenant_context(world["t"].pk):
            assert OrderLine.objects.get(order=order, product=world["a"]).qty_backordered == 2
        check_order_invariants(world["t"])


class TestBackorders:
    def _receive(self, world, product, quantity):
        with tenant_context(world["t"].pk):
            receipts.create_and_post(
                receipts.ReceiptInput(lines=[receipts.LineInput(product.pk, D(quantity))]),
                by=world["owner"],
            )

    def test_queue_confirm_and_reject(self, world):
        first = accepted_with_backorder(world)
        second = accepted_with_backorder(world, make_shop(world["t"], "9876500098"))
        _, client = staff(world, "WAREHOUSE")
        [group] = client.get("/api/v1/backorders/").json()
        assert (group["product_code"], group["waiting"], group["lines"], group["available"]) == (
            "B",
            "6.000",
            2,
            "0.000",
        )
        waiting = client.get(f"/api/v1/backorders/{world['b'].pk}/").json()
        assert [row["order"] for row in waiting] == [str(first.pk), str(second.pk)]  # FIFO

        self._receive(world, world["b"], "6")
        proposals = client.get("/api/v1/backorders/allocations/?status=PROPOSED").json()
        ids = [row["id"] for row in proposals["results"]]
        assert len(ids) == 2
        assert client.get("/api/v1/orders/counts/").json()["proposals"] == 2
        confirmed = client.post(
            "/api/v1/backorders/allocations/confirm/",
            {"allocations": ids[:1]},
            format="json",
            **key(),
        )
        assert confirmed.status_code == 200, confirmed.json()
        assert confirmed.json()[0]["status"] == "CONFIRMED"
        assert confirmed.json()[0]["fulfilment"] is not None
        rejected = client.post(f"/api/v1/backorders/allocations/{ids[1]}/reject/")
        assert rejected.json()[0]["status"] == "REJECTED"
        again = client.post(f"/api/v1/backorders/allocations/{ids[1]}/reject/")
        assert again.status_code == 409
        check_order_invariants(world["t"])

    def test_manual_and_automatic_allocation(self, world):
        first = accepted_with_backorder(world)
        second = accepted_with_backorder(world, make_shop(world["t"], "9876500098"))
        add_stock(world["t"], world["b"], "4")  # free stock, no run
        with tenant_context(world["t"].pk):
            second_line = OrderLine.objects.get(order=second, product=world["b"])
        _, accounts = staff(world, "ACCOUNTS")
        body = {
            "product": str(world["b"].pk),
            "allocations": [{"order_line": str(second_line.pk), "quantity": "3"}],
        }
        assert (
            accounts.post("/api/v1/backorders/allocate/", body, format="json", **key()).status_code
            == 403
        )
        _, client = staff(world, "WAREHOUSE")
        made = client.post("/api/v1/backorders/allocate/", body, format="json", **key())
        assert made.status_code == 200, made.json()
        assert [(row["order"], row["status"], row["trigger"]) for row in made.json()] == [
            (str(second.pk), "CONFIRMED", "MANUAL")
        ]
        auto = client.post(
            "/api/v1/backorders/allocate/",
            {"product": str(world["b"].pk), "auto": True},
            format="json",
            **key(),
        ).json()
        assert [(row["order"], row["quantity"], row["status"]) for row in auto] == [
            (str(first.pk), "1.000", "PROPOSED")
        ]
        neither = client.post(
            "/api/v1/backorders/allocate/",
            {"product": str(world["b"].pk)},
            format="json",
            **key(),
        )
        assert neither.status_code == 400
        check_order_invariants(world["t"])

    def test_cancel_backorder(self, world):
        order = accepted_with_backorder(world)
        with tenant_context(world["t"].pk):
            line = OrderLine.objects.get(order=order, product=world["b"])
        _, warehouse = staff(world, "WAREHOUSE")
        url = f"/api/v1/order-lines/{line.pk}/cancel-backorder/"
        assert warehouse.post(url).status_code == 403
        _, client = staff(world, "SALES")
        body = client.post(url).json()
        assert body["backorder_state"] == "CLOSED"
        assert client.post(url).status_code == 404  # nothing waits any more


class TestOnBehalf:
    def test_sales_orders_for_a_shop_with_its_own_cart(self, world):
        user, sales = staff(world, "SALES")
        user.full_name = "Priya"
        user.save(update_fields=["full_name"])
        shop_cart = shop_client(world["t"], world["shop"])
        shop_cart.put(f"/api/v1/shop/cart/lines/{world['b'].pk}/", {"quantity": "5"}, format="json")
        base = f"/api/v1/retailers/{world['shop'].pk}/cart/"
        cart = sales.put(f"{base}lines/{world['a'].pk}/", {"quantity": "2"}, format="json").json()
        assert [line["product_id"] for line in cart["lines"]] == [str(world["a"].pk)]
        placed = sales.post(
            "/api/v1/orders/",
            {"retailer": str(world["shop"].pk), "expected_total": cart["expected_total"]},
            format="json",
            **key(),
        )
        assert placed.status_code == 201, placed.json()
        body = placed.json()
        assert (body["placed_via"], body["placed_by_label"]) == ("STAFF", "Priya (Sales)")
        assert sales.get(base).json()["lines"] == []  # the staff cart was used up
        shop_lines = shop_cart.get("/api/v1/shop/cart/").json()["lines"]
        assert [line["product_id"] for line in shop_lines] == [str(world["b"].pk)]  # untouched

    def test_needs_the_permission_and_the_setting(self, world):
        base = f"/api/v1/retailers/{world['shop'].pk}/cart/"
        _, warehouse = staff(world, "WAREHOUSE")
        assert warehouse.get(base).status_code == 403
        _, sales = staff(world, "SALES")
        settings(world["t"], orders__staff_can_place_on_behalf=False)
        refused = sales.get(base)
        assert (refused.status_code, code(refused)) == (403, "PERMISSION_DENIED")


class TestSalesVisibility:
    def test_assigned_retailers_only(self, world):
        user, sales = staff(world, "SALES")
        mine = make_shop(world["t"], "9876500097")
        with tenant_context(world["t"].pk):
            Retailer.objects.filter(pk=mine.pk).update(salesperson=user)
        my_order = accepted_with_backorder(world, mine)
        other_order = accepted_with_backorder(world)
        settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
        rows = sales.get("/api/v1/orders/").json()["results"]
        assert [row["id"] for row in rows] == [str(my_order.pk)]
        assert sales.get(f"/api/v1/orders/{other_order.pk}/").status_code == 404
        assert (
            sales.post(f"/api/v1/orders/{other_order.pk}/cancel/", {"reason": "x"}).status_code
            == 404
        )
        assert sales.get(f"/api/v1/retailers/{world['shop'].pk}/cart/").status_code == 404
        assert sales.get(f"/api/v1/retailers/{mine.pk}/cart/").status_code == 200
        [group] = sales.get("/api/v1/backorders/").json()
        assert group["lines"] == 1
        assert sales.get("/api/v1/orders/counts/").json()["backorders"] == 1
        _, owner = staff(world, "OWNER")
        assert len(owner.get("/api/v1/orders/").json()["results"]) == 2


@covers(
    "orders",
    "orders-counts",
    "order",
    "order-accept",
    "order-reject",
    "order-cancel",
    "order-lines",
    "order-hold-approve",
    "order-hold-reject",
    "order-line-cancel-backorder",
    "fulfilments",
    "fulfilment",
    "fulfilment-pack",
    "fulfilment-dispatch",
    "fulfilment-deliver",
    "fulfilment-cancel",
    "backorders",
    "backorders-allocate",
    "backorder-allocations",
    "backorder-allocations-confirm",
    "backorder-allocation-reject",
    "backorder-product",
    "retailer-cart",
    "retailer-cart-line",
    "retailer-cart-reduce",
)
def test_another_tenant_sees_and_changes_nothing(world, tenant_b):
    order = accepted_with_backorder(world)
    with tenant_context(world["t"].pk):
        shipment = Fulfilment.objects.get(order=order)
        line = OrderLine.objects.get(order=order, product=world["b"])
    add_stock(world["t"], world["b"], "3")
    with tenant_context(world["t"].pk):
        from apps.orders import backorders

        backorders.run_allocation([world["b"].pk], trigger="MANUAL")
        allocation = BackorderAllocation.objects.get()
    outsider = client_for(tenant_b, make_staff_in(tenant_b, "OWNER"))
    outsider.default_format = "json"
    for url in (
        f"/api/v1/orders/{order.pk}/",
        f"/api/v1/fulfilments/{shipment.pk}/",
        f"/api/v1/backorders/{world['b'].pk}/",
    ):
        response = outsider.get(url)
        assert response.status_code == 404 or response.json() == [], url
    for url in ("/api/v1/orders/", "/api/v1/fulfilments/", "/api/v1/backorders/allocations/"):
        assert outsider.get(url).json()["results"] == [], url
    assert outsider.get("/api/v1/backorders/").json() == []
    posts = [
        (f"/api/v1/orders/{order.pk}/accept/", {}, True),
        (f"/api/v1/orders/{order.pk}/reject/", {"reason": "x"}, False),
        (f"/api/v1/orders/{order.pk}/cancel/", {"reason": "x"}, False),
        (f"/api/v1/orders/{order.pk}/hold/approve/", {}, False),
        (f"/api/v1/orders/{order.pk}/hold/reject/", {"reason": "x"}, False),
        (f"/api/v1/order-lines/{line.pk}/cancel-backorder/", {}, False),
        (f"/api/v1/fulfilments/{shipment.pk}/pack/", {}, False),
        (f"/api/v1/fulfilments/{shipment.pk}/dispatch/", {}, False),
        (f"/api/v1/fulfilments/{shipment.pk}/deliver/", {}, False),
        (
            f"/api/v1/fulfilments/{shipment.pk}/cancel/",
            {"to_backorder": True, "reason": "x"},
            False,
        ),
        ("/api/v1/backorders/allocations/confirm/", {"allocations": [str(allocation.pk)]}, True),
        (f"/api/v1/backorders/allocations/{allocation.pk}/reject/", {}, False),
        (
            "/api/v1/backorders/allocate/",
            {
                "product": str(world["b"].pk),
                "allocations": [{"order_line": str(line.pk), "quantity": "1"}],
            },
            True,
        ),
        (
            "/api/v1/orders/",
            {"retailer": str(world["shop"].pk), "expected_total": "0.00"},
            True,
        ),
    ]
    for url, body, keyed in posts:
        headers = key() if keyed else {}
        response = outsider.post(url, body, format="json", **headers)  # type: ignore[arg-type]
        assert response.status_code == 404, (url, response.status_code, response.json())
    assert (
        outsider.patch(
            f"/api/v1/orders/{order.pk}/lines/", {"lines": []}, format="json"
        ).status_code
        == 404
    )
    cart = f"/api/v1/retailers/{world['shop'].pk}/cart/"
    assert outsider.get(cart).status_code == 404
    assert outsider.delete(cart).status_code == 404
    line_url = f"{cart}lines/{world['a'].pk}/"
    assert outsider.put(line_url, {"quantity": "1"}, format="json").status_code == 404
    assert outsider.delete(line_url).status_code == 404
    assert outsider.post(f"{cart}reduce-to-available/").status_code == 404
    counts = outsider.get("/api/v1/orders/counts/").json()
    assert set(counts.values()) == {0}
    with tenant_context(world["t"].pk):
        order.refresh_from_db()
        shipment.refresh_from_db()
        assert (order.status, shipment.status) == ("ACCEPTED", "ALLOCATED")
        assert BackorderAllocation.objects.get().status == "PROPOSED"
        assert Order.objects.count() == 1
