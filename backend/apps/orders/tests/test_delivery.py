"""The shop confirms delivery, and the delivery code (ADR-057 items 1-2): the same effect as staff
marking it delivered, a code only the shop sees and gets in the dispatch message, wrong codes
counted and locked, delivery without the code with a reason (audited), settings, isolation."""

from decimal import Decimal as D
from typing import Any

import pytest
from django.core.cache import cache

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.inventory.tests.helpers import make_product
from apps.notifications.models import Notification
from apps.orders import fulfilment, transitions
from apps.orders.fulfilment import DeliveryCodeLocked, Transport, WrongDeliveryCode
from apps.orders.models import Fulfilment, Order
from apps.orders.tests.helpers import (
    add_stock,
    client_for,
    make_shop,
    place,
    settings,
    shop_client,
)
from common.errors import InvalidFields
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
SHOP, API = "/api/v1/shop", "/api/v1"


@pytest.fixture
def world(tenant_a, tenant_b, django_capture_on_commit_callbacks):
    cache.clear()
    settings(
        tenant_a, notifications__quiet_hours_start="00:00", notifications__quiet_hours_end="00:00"
    )
    owner = make_staff_in(tenant_a, "OWNER")
    product = make_product(tenant_a, "P-1", base_price=D("50"))
    add_stock(tenant_a, product, "20")
    shop = make_shop(tenant_a, "9876500111", shop_name="Laxmi Stores")
    yield {
        "t": tenant_a,
        "owner": owner,
        "product": product,
        "shop": shop,
        "other_shop": make_shop(tenant_a, "9876500112", shop_name="Om Stores"),
        "staff": client_for(tenant_a, owner),
        "b": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
        "run": lambda: django_capture_on_commit_callbacks(execute=True),
    }
    cache.clear()


def dispatched(world: dict[str, Any]) -> Fulfilment:
    t, owner = world["t"], world["owner"]
    order = place(t, world["shop"], (world["product"], "2"))
    with world["run"](), tenant_context(t.pk):
        transitions.accept_order(order.pk, by=owner)
        shipment: Fulfilment = Fulfilment.objects.get(order=order)
        fulfilment.pack(shipment.pk, {}, by=owner)
        fulfilment.dispatch(shipment.pk, Transport("", "", ""), by=owner)
        shipment.refresh_from_db()
    return shipment


@covers("shop-fulfilment-received")
def test_the_shop_marks_a_shipment_received(world):
    shipment = dispatched(world)
    url = f"{SHOP}/fulfilments/{shipment.pk}/received/"
    assert shop_client(world["t"], world["other_shop"]).post(url).status_code == 404
    order = shop_client(world["t"], world["shop"]).get(f"{SHOP}/orders/{shipment.order_id}/")
    [mine] = order.json()["fulfilments"]
    assert (mine["can_confirm"], mine["delivery_code"]) == (True, "")
    with world["run"]():
        done = shop_client(world["t"], world["shop"]).post(url)
    assert done.status_code == 200 and done.json()["status"] == "COMPLETED"
    with tenant_context(world["t"].pk):
        shipment.refresh_from_db()
        history = Order.objects.get(pk=shipment.order_id).history.get(event="DELIVER")
    assert (shipment.status, shipment.delivered_via) == ("DELIVERED", "SHOP")
    assert (history.actor_type, history.payload["via"]) == ("RETAILER", "SHOP")
    # Once delivered, nothing more to confirm.
    assert shop_client(world["t"], world["shop"]).post(url).status_code == 409


def test_switched_off_the_shop_cannot_confirm(world):
    settings(world["t"], orders__shop_confirms_delivery=False)
    shipment = dispatched(world)
    client = shop_client(world["t"], world["shop"])
    [mine] = client.get(f"{SHOP}/orders/{shipment.order_id}/").json()["fulfilments"]
    assert mine["can_confirm"] is False
    refused = client.post(f"{SHOP}/fulfilments/{shipment.pk}/received/")
    assert refused.status_code == 403


def test_the_delivery_code_only_the_shop_sees(world):
    settings(world["t"], orders__delivery_code=True)
    shipment = dispatched(world)
    assert len(shipment.delivery_code) == 4 and shipment.delivery_code.isdigit()
    shop = shop_client(world["t"], world["shop"]).get(f"{SHOP}/orders/{shipment.order_id}/")
    assert shop.json()["fulfilments"][0]["delivery_code"] == shipment.delivery_code
    staff = world["staff"].get(f"{API}/fulfilments/{shipment.pk}/").json()
    assert "delivery_code" not in staff and staff["needs_delivery_code"] is True
    staff_order = world["staff"].get(f"{API}/orders/{shipment.order_id}/").json()
    assert "delivery_code" not in staff_order["fulfilments"][0]
    # The shop's dispatch message carries it; the office's doesn't.
    with tenant_context(world["t"].pk):
        texts = {
            n.recipient.user_type: n.body
            for n in Notification.objects.filter(event_code="order.dispatched").select_related(
                "recipient"
            )
        }
    assert f"Delivery code: {shipment.delivery_code}." in texts["RETAILER"]
    assert all("Delivery code" not in body for kind, body in texts.items() if kind != "RETAILER")


def test_delivering_with_the_code_without_it_and_wrong_codes(world):
    settings(world["t"], orders__delivery_code=True)
    t, owner = world["t"], world["owner"]
    first, second = dispatched(world), dispatched(world)
    wrong = "0000" if first.delivery_code != "0000" else "1111"
    with tenant_context(t.pk):
        with pytest.raises(InvalidFields):
            fulfilment.deliver(first.pk, by=owner)  # neither the code nor a reason
        for _ in range(4):
            with pytest.raises(WrongDeliveryCode):
                fulfilment.deliver(first.pk, by=owner, code=wrong)
        first.refresh_from_db()
        assert first.delivery_code_failures == 4  # counted although each try was refused
        with pytest.raises(WrongDeliveryCode):
            fulfilment.deliver(first.pk, by=owner, code=wrong)
        with pytest.raises(DeliveryCodeLocked):  # the fifth locked it, even the right code
            fulfilment.deliver(first.pk, by=owner, code=first.delivery_code)
        fulfilment.deliver(first.pk, by=owner, reason="Shop closed; left with the neighbour")
        first.refresh_from_db()
        assert (first.status, first.delivered_via) == ("DELIVERED", "NO_CODE")
        assert AuditLog.objects.filter(action="orders.delivered_without_code").count() == 1
        fulfilment.deliver(second.pk, by=owner, code=second.delivery_code)
        second.refresh_from_db()
        assert (second.status, second.delivered_via) == ("DELIVERED", "CODE")


def test_the_api_takes_the_code_and_names_the_error(world):
    settings(world["t"], orders__delivery_code=True)
    shipment = dispatched(world)
    wrong = "0000" if shipment.delivery_code != "0000" else "1111"
    url = f"{API}/fulfilments/{shipment.pk}/deliver/"
    refused = world["staff"].post(url, {"code": wrong}, format="json")
    assert (refused.status_code, refused.json()["error"]["code"]) == (422, "WRONG_DELIVERY_CODE")
    done = world["staff"].post(url, {"code": shipment.delivery_code}, format="json")
    assert done.status_code == 200 and done.json()["delivered_via"] == "CODE"
    assert world["b"].post(url, {"code": shipment.delivery_code}, format="json").status_code == 404


def test_wrong_codes_through_the_api_are_kept_and_lock_the_code(world):
    """The refusal must not roll back the counted try (the request runs in one transaction), or
    the lock after five wrong codes would never come through the app."""
    settings(world["t"], orders__delivery_code=True)
    shipment = dispatched(world)
    wrong = "0000" if shipment.delivery_code != "0000" else "1111"
    url = f"{API}/fulfilments/{shipment.pk}/deliver/"
    refused = world["staff"].post(url, {"code": wrong}, format="json")
    assert refused.status_code == 422
    with tenant_context(world["t"].pk):
        shipment.refresh_from_db()
        assert shipment.delivery_code_failures == 1
    for _ in range(4):
        world["staff"].post(url, {"code": wrong}, format="json")
    locked = world["staff"].post(url, {"code": shipment.delivery_code}, format="json")
    assert (locked.status_code, locked.json()["error"]["code"]) == (429, "DELIVERY_CODE_LOCKED")
    with tenant_context(world["t"].pk):
        shipment.refresh_from_db()
        assert shipment.status == "DISPATCHED"
        assert shipment.delivery_code_locked_until is not None


def test_without_codes_staff_deliver_as_before(world):
    shipment = dispatched(world)
    assert shipment.delivery_code == ""
    with tenant_context(world["t"].pk):
        fulfilment.deliver(shipment.pk, by=world["owner"])
        shipment.refresh_from_db()
    assert (shipment.status, shipment.delivered_via) == ("DELIVERED", "STAFF")
