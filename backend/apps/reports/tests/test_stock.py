"""Stock reports (ADR-050): stock summary, valuation, low stock, movement history, fast / slow /
dead / new, backorder demand and the fulfilment rate, with who may see what."""

from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing.tests.helpers import ship_invoice
from apps.catalog.models import Product
from apps.inventory.tests.helpers import make_product
from apps.orders import fulfilment, transitions
from apps.orders.models import Fulfilment
from apps.orders.tests.helpers import add_stock, client_for, make_shop, place, settings, shop_user
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
API = "/api/v1"


@pytest.fixture
def world(tenant_a, tenant_b):
    owner = make_staff_in(tenant_a, "OWNER")
    sales = make_staff_in(tenant_a, "SALES")
    fast = make_product(tenant_a, "FAST", base_price=D("100"), cost_price=D("60"))
    slow = make_product(tenant_a, "SLOW", base_price=D("50"), cost_price=D("40"))
    idle = make_product(tenant_a, "IDLE", base_price=D("20"))  # in stock, never sold, no cost
    low = make_product(tenant_a, "LOW", base_price=D("10"), cost_price=D("5"))
    add_stock(tenant_a, fast, "100")
    add_stock(tenant_a, slow, "20")
    add_stock(tenant_a, idle, "30")
    add_stock(tenant_a, low, "2")
    with tenant_context(tenant_a.pk):
        Product.objects.filter(pk=low.pk).update(reorder_level=D("5"))
    shop = make_shop(tenant_a, "9876500071", shop_name="Chetan Traders")
    other_shop = make_shop(tenant_a, "9876500072", shop_name="Durga Stores")
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop.pk).update(salesperson=sales)
    ship_invoice(tenant_a, shop, owner, (fast, "10"), (slow, "1"))
    return {
        "t": tenant_a,
        "owner": client_for(tenant_a, owner),
        "owner_user": owner,
        "warehouse": client_for(tenant_a, make_staff_in(tenant_a, "WAREHOUSE")),
        "sales": client_for(tenant_a, sales),
        "other": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
        "shop": shop,
        "other_shop": other_shop,
        "products": {"fast": fast, "slow": slow, "idle": idle, "low": low},
    }


def report(client: Any, code: str, query: str = "") -> dict[str, Any]:
    response = client.get(f"{API}/reports/{code}/?{query}")
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()
    return body


def rows_by(body: dict[str, Any], key: str = "code") -> dict[str, dict[str, Any]]:
    return {r[key]: r for r in body["rows"]}


def test_stock_summary_with_values_only_for_those_who_see_costs(world):
    body = report(world["owner"], "stock_summary")
    rows = rows_by(body)
    assert (rows["FAST"]["on_hand"], rows["FAST"]["status"]) == ("90.000", "In stock")
    assert (rows["LOW"]["status"], rows["LOW"]["value"]) == ("Low", "10.00")
    assert rows["IDLE"]["value"] is None  # no cost price
    assert body["totals"]["value"] == "6170.00"  # 90x60 + 19x40 + 2x5
    low_only = report(world["owner"], "stock_summary", "status=LOW")
    assert [r["code"] for r in low_only["rows"]] == ["LOW"]
    warehouse = report(world["warehouse"], "stock_summary")
    assert "value" not in warehouse["rows"][0] and "cost_price" not in warehouse["rows"][0]


def test_valuation_needs_costs_and_says_what_is_left_out(world):
    body = report(world["owner"], "stock_valuation")
    assert set(rows_by(body)) == {"FAST", "SLOW", "LOW"}
    assert body["totals"]["value"] == "6170.00"
    assert body["notes"] == ["1 product(s) in stock have no cost price and are left out."]
    assert world["warehouse"].get(f"{API}/reports/stock_valuation/").status_code == 403


def test_low_stock_with_products_that_never_show_as_low(world):
    body = report(world["warehouse"], "low_stock")
    assert [(r["code"], r["shortfall"]) for r in body["rows"]] == [("LOW", "3.000")]
    assert body["notes"] == [
        "3 active product(s) have no reorder level, so they never show as low."
    ]


def test_movement_history_for_the_period(world):
    today = today_ist().isoformat()
    body = report(world["owner"], "stock_movements", f"date_from={today}&date_to={today}")
    kinds = {(r["code"], r["type"]) for r in body["rows"]}
    assert {("FAST", "Dispatched"), ("FAST", "Adjustment in")} <= kinds
    dispatched = report(
        world["owner"],
        "stock_movements",
        f"date_from={today}&date_to={today}&movement_type=SALE",
    )
    assert {r["code"] for r in dispatched["rows"]} == {"FAST", "SLOW"}
    too_long = world["owner"].get(
        f"{API}/reports/stock_movements/?date_from=2026-01-01&date_to=2026-06-30"
    )
    assert too_long.status_code == 400  # 92 days at most


def test_fast_slow_and_new_stock(world):
    settings(world["t"], reports__fast_share_percent=50)
    body = report(world["owner"], "stock_movement_class")
    classes = {r["code"]: r["class"] for r in body["rows"]}
    # Of the two that sold, the top half is fast; the rest were stocked today: new, not dead.
    assert classes == {"FAST": "Fast", "SLOW": "Slow", "IDLE": "New", "LOW": "New"}
    assert body["notes"][0].startswith("Over the last 90 days. Fast: the top 50%")
    by_qty = report(world["owner"], "stock_movement_class", "rank_by=quantity&class=fast")
    assert [r["code"] for r in by_qty["rows"]] == ["FAST"]


def test_stock_nothing_sold_since_is_dead(world, monkeypatch):
    later = today_ist() + timedelta(days=200)  # the sale and the first stock are long past
    monkeypatch.setattr("apps.reports.definitions.stock.today_ist", lambda: later)
    classes = {
        r["code"]: r["class"] for r in report(world["owner"], "stock_movement_class")["rows"]
    }
    assert classes == {"FAST": "Dead", "SLOW": "Dead", "IDLE": "Dead", "LOW": "Dead"}


def test_backorder_demand_for_the_warehouse_and_own_shops_for_sales(world):
    low = world["products"]["low"]
    for shop in (world["shop"], world["other_shop"]):
        order = place(world["t"], shop, (low, "3"))
        with tenant_context(world["t"].pk):
            transitions.accept_order(order.pk, by=world["owner_user"])
    body = report(world["warehouse"], "backorder_demand")
    [row] = body["rows"]
    assert (row["code"], row["shops"], row["qty"]) == ("LOW", 2, "4.000")  # 2 in stock, 6 ordered
    assert body["totals"]["value"] == "40.00"
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    assert report(world["warehouse"], "backorder_demand")["rows"][0]["shops"] == 2
    mine = report(world["sales"], "backorder_demand")
    assert (mine["rows"][0]["shops"], mine["own_shops"]) == (1, True)


def test_fulfilment_rate_leaves_out_what_the_shop_cancelled(world):
    today = today_ist().isoformat()
    fast = world["products"]["fast"]
    open_order = place(world["t"], world["other_shop"], (fast, "1"))
    cancelled = place(world["t"], world["other_shop"], (fast, "1"))
    with tenant_context(world["t"].pk):
        shipment = Fulfilment.objects.exclude(order=open_order).get(order__retailer=world["shop"])
        fulfilment.deliver(shipment.pk, by=world["owner_user"])
        transitions.accept_order(open_order.pk, by=world["owner_user"])
        transitions.cancel_order(
            cancelled.pk, by=shop_user(world["other_shop"]), retailer_id=world["other_shop"].pk
        )
    body = report(world["owner"], "fulfilment_rate", f"date_from={today}&date_to={today}")
    [row] = body["rows"]
    assert (row["orders"], row["open"], row["in_full"]) == (2, 1, 1)
    assert (row["in_full_pct"], row["delivered_pct"]) == ("100.0", "100.0")


def test_another_business_sees_none_of_it(world):
    assert report(world["other"], "stock_summary")["rows"] == []
    assert report(world["other"], "backorder_demand")["rows"] == []
