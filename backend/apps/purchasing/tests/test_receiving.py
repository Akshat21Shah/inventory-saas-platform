"""Receiving against a purchase order (ADR-053 items 6 and 7): a draft with what is still due and
the order's costs (no "cost pending" for staff who can't see costs), partial and full receipts
moving the order on, the over-receipt tolerance and its confirmation, the supplier's last cost,
and what is on order (quantities and dates only)."""

from datetime import timedelta
from decimal import Decimal as D
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.catalog.models import Unit
from apps.compliance.tests.conftest import switch_on
from apps.inventory.models import StockInwardLine, StockLevel
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import client_for, settings
from apps.purchasing.models import PurchaseOrder, SupplierProduct
from common.dates import today_ist
from common.storage import InMemoryStorage
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    InMemoryStorage.objects.clear()
    yield
    InMemoryStorage.objects.clear()


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


def key() -> dict[str, str]:
    return {"HTTP_IDEMPOTENCY_KEY": f"k-{uuid4().hex}"}


@pytest.fixture
def world(tenant_a, tenant_b, run):
    switch_on(tenant_a, "purchasing")
    switch_on(tenant_b, "purchasing")
    owner = client_for(tenant_a, make_staff_in(tenant_a, "OWNER"))
    tea = make_product(tenant_a, "TEA", name="Tata Tea Gold")
    with tenant_context(tenant_a.pk):
        box = Unit.objects.get(code="BOX")
    biscuit = make_product(tenant_a, "BISCUIT", name="Parle-G", pack_unit=box, pack_size=D("12"))
    supplier = owner.post(f"{API}/suppliers/", {"name": "Hindustan Traders"}, format="json").json()
    order = run(
        owner.post,
        f"{API}/purchase-orders/",
        {
            "supplier_id": supplier["id"],
            "expected_date": str(today_ist() + timedelta(days=3)),
            "lines": [
                {"product_id": str(tea.pk), "entered_qty": "10", "entered_cost": "80"},
                {
                    "product_id": str(biscuit.pk),
                    "entered_unit": "PACK",
                    "entered_qty": "2",
                    "entered_cost": "60",
                },
            ],
        },
        format="json",
    ).json()
    run(owner.post, f"{API}/purchase-orders/{order['id']}/send/", **key())
    return {
        "t": tenant_a,
        "b": tenant_b,
        "owner": owner,
        "warehouse": client_for(tenant_a, make_staff_in(tenant_a, "WAREHOUSE")),
        "sales": client_for(tenant_a, make_staff_in(tenant_a, "SALES")),
        "other": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
        "tea": tea,
        "biscuit": biscuit,
        "supplier": supplier,
        "order": order,
    }


def receive(world: dict[str, Any], run: Any, client: str = "warehouse") -> dict[str, Any]:
    response = run(world[client].post, f"{API}/purchase-orders/{world['order']['id']}/receive/")
    assert response.status_code == 201, response.json()
    body: dict[str, Any] = response.json()
    return body


def post(
    world: dict[str, Any], run: Any, receipt_id: str, client: str = "warehouse", **body: Any
) -> Any:
    return run(
        world[client].post, f"{API}/stock/inwards/{receipt_id}/post/", body, format="json", **key()
    )


def order(world: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = (
        world["owner"].get(f"{API}/purchase-orders/{world['order']['id']}/").json()
    )
    return found


def on_hand(world: dict[str, Any], product: Any) -> D:
    with tenant_context(world["t"].pk):
        return StockLevel.objects.get(product=product).quantity_on_hand


@covers("purchase-order-receive")
def test_receiving_everything_due_with_the_orders_costs(world, run):
    draft = receive(world, run)
    assert (draft["status"], draft["purchase_order_number"], draft["supplier_name"]) == (
        "DRAFT",
        world["order"]["number"],
        "Hindustan Traders",
    )
    tea, biscuit = draft["lines"]
    assert (tea["entered_unit"], tea["entered_qty"], tea["ordered"], tea["received_before"]) == (
        "BASE",
        "10.000",
        "10.000",
        "0.000",
    )
    assert (biscuit["entered_unit"], biscuit["entered_qty"], biscuit["quantity"]) == (
        "PACK",
        "2.000",
        "24.000",
    )
    assert tea["unit_cost"] is None  # the warehouse doesn't see costs, but they are there
    assert receive(world, run)["id"] == draft["id"]  # the draft being entered, not a second one
    posted = post(world, run, draft["id"])
    assert posted.status_code == 200, posted.json()
    assert posted.json()["cost_pending_lines"] == 0
    assert (on_hand(world, world["tea"]), on_hand(world, world["biscuit"])) == (D("10"), D("24"))
    done = order(world)
    assert (done["status"], done["actions"]) == ("RECEIVED", [])
    assert [(line["qty_received"], line["due"]) for line in done["lines"]] == [
        ("10.000", "0.000"),
        ("24.000", "0.000"),
    ]
    assert [r["number"] for r in done["receipts"]] == [posted.json()["number"]]
    with tenant_context(world["t"].pk):
        costs = dict(SupplierProduct.objects.values_list("product_id", "last_unit_cost"))
    assert costs == {world["tea"].pk: D("80.0000"), world["biscuit"].pk: D("5.0000")}
    refused = run(world["warehouse"].post, f"{API}/purchase-orders/{world['order']['id']}/receive/")
    assert refused.status_code == 409  # nothing more is due


def test_part_now_the_rest_later(world, run):
    draft = receive(world, run)
    tea, biscuit = draft["lines"]
    edited = run(
        world["warehouse"].patch,
        f"{API}/stock/inwards/{draft['id']}/",
        {
            "lines": [
                {"id": tea["id"], "product_id": str(world["tea"].pk), "entered_qty": "4"},
                {
                    "id": biscuit["id"],
                    "product_id": str(world["biscuit"].pk),
                    "entered_unit": "PACK",
                    "entered_qty": "2",
                },
            ]
        },
        format="json",
    )
    assert edited.status_code == 200, edited.json()
    with tenant_context(world["t"].pk):  # the order's link and costs are kept through the edit
        kept = list(StockInwardLine.objects.filter(inward_id=draft["id"]).order_by("line_no"))
        assert [(line.purchase_order_line_id is not None, line.unit_cost) for line in kept] == [
            (True, D("80.0000")),
            (True, D("5.0000")),
        ]
    assert post(world, run, draft["id"]).status_code == 200
    partly = order(world)
    assert (partly["status"], partly["actions"]) == ("PARTLY_RECEIVED", ["receive", "close"])
    assert partly["lines"][0]["due"] == "6.000"
    rest = receive(world, run)
    assert [(line["product"]["code"], line["entered_qty"]) for line in rest["lines"]] == [
        ("TEA", "6.000")
    ]
    assert post(world, run, rest["id"]).status_code == 200
    assert order(world)["status"] == "RECEIVED"


def test_over_the_order_within_the_tolerance_and_beyond_it(world, run):
    draft = receive(world, run)
    tea, biscuit = draft["lines"]

    def lines(tea_qty: str) -> dict[str, Any]:
        return {
            "lines": [
                {"id": tea["id"], "product_id": str(world["tea"].pk), "entered_qty": tea_qty},
                {
                    "id": biscuit["id"],
                    "product_id": str(world["biscuit"].pk),
                    "entered_unit": "PACK",
                    "entered_qty": "2",
                },
            ]
        }

    run(world["warehouse"].patch, f"{API}/stock/inwards/{draft['id']}/", lines("12"), format="json")
    refused = post(world, run, draft["id"])
    assert refused.status_code == 409
    error = refused.json()["error"]
    assert (
        error["code"],
        error["details"]["tolerance_percent"],
        error["details"]["can_confirm"],
    ) == (
        "OVER_RECEIPT",
        10,
        False,
    )
    assert error["details"]["lines"] == [
        {
            "line_id": tea["purchase_order_line_id"],
            "product_code": "TEA",
            "ordered": "10.000",
            "received_before": "0.000",
            "receiving": "12.000",
            "beyond_tolerance": True,
        }
    ]
    assert post(world, run, draft["id"], confirm_over_receipt=True).status_code == 409  # not theirs
    confirmed = post(world, run, draft["id"], client="owner", confirm_over_receipt=True)
    assert confirmed.status_code == 200, confirmed.json()
    assert order(world)["lines"][0]["qty_received"] == "12.000"
    with tenant_context(world["t"].pk):
        assert AuditLog.objects.filter(action="purchasing.over_receipt_confirmed").count() == 1


def test_a_little_over_is_accepted_and_the_tolerance_is_a_setting(world, run):
    draft = receive(world, run)
    tea, biscuit = draft["lines"]
    body = {
        "lines": [
            {"id": tea["id"], "product_id": str(world["tea"].pk), "entered_qty": "11"},
            {
                "id": biscuit["id"],
                "product_id": str(world["biscuit"].pk),
                "entered_unit": "PACK",
                "entered_qty": "2",
            },
        ]
    }
    run(world["warehouse"].patch, f"{API}/stock/inwards/{draft['id']}/", body, format="json")
    settings(world["t"], purchasing__over_receipt_tolerance_percent=0)
    assert post(world, run, draft["id"]).status_code == 409
    settings(world["t"], purchasing__over_receipt_tolerance_percent=10)
    assert post(world, run, draft["id"]).status_code == 200  # 11 of 10: within 10%
    assert order(world)["status"] == "RECEIVED"


def test_an_order_being_received_cant_be_closed_or_cancelled(world, run):
    draft = receive(world, run)
    url = f"{API}/purchase-orders/{world['order']['id']}"
    assert (
        run(world["owner"].post, f"{url}/cancel/", {"reason": "x"}, format="json").status_code
        == 409
    )
    assert run(world["owner"].delete, f"{API}/stock/inwards/{draft['id']}/").status_code == 204
    assert (
        run(world["owner"].post, f"{url}/cancel/", {"reason": "x"}, format="json").status_code
        == 200
    )


@covers("product-on-order")
def test_what_is_on_order_without_suppliers_or_prices(world, run):
    url = f"{API}/products/{world['tea'].pk}/on-order/"
    body = world["sales"].get(url).json()  # sales staff see it too
    expected = str(today_ist() + timedelta(days=3))
    assert body == {
        "quantity": "10.000",
        "expected_date": expected,
        "late": False,
        "orders": [{"quantity": "10.000", "expected_date": expected, "late": False}],
    }
    draft = receive(world, run)
    tea, _biscuit = draft["lines"]
    run(
        world["warehouse"].patch,
        f"{API}/stock/inwards/{draft['id']}/",
        {"lines": [{"id": tea["id"], "product_id": str(world["tea"].pk), "entered_qty": "4"}]},
        format="json",
    )
    post(world, run, draft["id"])
    with tenant_context(world["t"].pk):
        PurchaseOrder.objects.filter(pk=world["order"]["id"]).update(
            expected_date=today_ist() - timedelta(days=1)
        )
    late = world["warehouse"].get(url).json()
    assert (late["quantity"], late["late"]) == ("6.000", True)
    biscuits = world["warehouse"].get(f"{API}/products/{world['biscuit'].pk}/on-order/").json()
    assert biscuits["quantity"] == "24.000"
    assert world["other"].get(url).status_code == 404
    shop = APIClient()
    assert shop.get(url).status_code == 401


def test_receiving_belongs_to_one_distributor_and_needs_the_permission(world, run):
    url = f"{API}/purchase-orders/{world['order']['id']}/receive/"
    assert run(world["other"].post, url).status_code == 404
    assert run(world["sales"].post, url).status_code == 403  # no stock.inward


def test_a_receipt_from_a_supplier_records_its_last_cost(world, run):
    product = make_product(world["t"], "SALT")
    response = run(
        world["owner"].post,
        f"{API}/stock/inwards/",
        {
            "supplier_id": world["supplier"]["id"],
            "post": True,
            "lines": [{"product_id": str(product.pk), "entered_qty": "5", "entered_cost": "20"}],
        },
        format="json",
        **key(),
    )
    assert response.status_code == 201, response.json()
    with tenant_context(world["t"].pk):
        link = SupplierProduct.objects.get(product=product)
    assert (link.last_unit_cost, link.is_preferred) == (D("20.0000"), False)
