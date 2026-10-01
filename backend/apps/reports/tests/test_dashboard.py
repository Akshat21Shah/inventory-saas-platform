"""The distributor's dashboard (ADR-050 item 11): what needs action today, today's "Orders
received" and "Billed", and trends, each part only with its permission; sales staff limited to
their own shops get their own shops' figures."""

from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing.tests.helpers import ship_invoice
from apps.catalog.models import Product
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_stock, client_for, make_shop, place, settings
from apps.payments import services as payments
from apps.payments.services import PaymentInput
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"


@pytest.fixture
def world(tenant_a, tenant_b, monkeypatch):
    owner = make_staff_in(tenant_a, "OWNER")
    sales = make_staff_in(tenant_a, "SALES")
    tea = make_product(tenant_a, "TEA", base_price=D("100"))
    soap = make_product(tenant_a, "SOAP", base_price=D("10"))
    add_stock(tenant_a, tea, "100")
    add_stock(tenant_a, soap, "3")
    with tenant_context(tenant_a.pk):
        Product.objects.filter(pk=soap.pk).update(reorder_level=D("5"))
    mine = make_shop(tenant_a, "9876500101", shop_name="Mine Stores")
    theirs = make_shop(tenant_a, "9876500102", shop_name="Their Stores")
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=mine.pk).update(salesperson=sales, payment_terms_days=30)
    today = today_ist()
    monkeypatch.setattr("apps.billing.invoicing.today_ist", lambda: today - timedelta(days=40))
    old = ship_invoice(tenant_a, mine, owner, (tea, "2"))  # ₹210, 10 days overdue
    monkeypatch.setattr("apps.billing.invoicing.today_ist", lambda: today)
    new = ship_invoice(tenant_a, theirs, owner, (tea, "1"))  # ₹105 today
    place(tenant_a, theirs, (tea, "1"))  # waiting to be accepted
    with tenant_context(tenant_a.pk):
        payments.collect_payment(PaymentInput(mine.pk, D("50"), "CASH", today), by=sales)
    return {
        "t": tenant_a,
        "owner": client_for(tenant_a, owner),
        "warehouse": client_for(tenant_a, make_staff_in(tenant_a, "WAREHOUSE")),
        "sales": client_for(tenant_a, sales),
        "other": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
        "old": old,
        "new": new,
    }


def board(client: Any) -> dict[str, Any]:
    response = client.get(f"{API}/dashboard/")
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()
    return body


@covers("dashboard")
def test_the_owner_sees_everything_that_needs_action(world):
    body = board(world["owner"])
    action = body["action"]
    assert (action["new_orders"], action["on_hold"]) == (1, 0)
    assert action["handover"] == {"count": 1, "amount": "50.00"}
    assert action["overdue"] == {"shops": 1, "amount": "160.00"}  # 210 - 50 collected
    assert action["low_stock"] == {"low": 1, "out": 0}
    assert (action["failed_irns"], action["failed_ewaybills"]) == (None, None)  # modules off
    assert body["today"]["orders_received"] == {"count": 3, "amount": "420.00"}
    assert body["today"]["billed"] == "105.00"
    trends = body["trends"]
    assert len(trends["days"]) == 30 and trends["days"][-1]["billed"] == "105.00"
    assert (trends["billed_30_days"], trends["billed_previous_30_days"]) == ("105.00", "210.00")
    assert [s["name"] for s in trends["top_shops"]] == ["Their Stores"]
    assert (trends["new_shops"], trends["repeat_shops"]) == (2, 0)


def test_the_warehouse_sees_orders_and_stock_but_no_money(world):
    body = board(world["warehouse"])
    assert body["action"]["low_stock"] == {"low": 1, "out": 0}
    assert body["action"]["new_orders"] == 1
    assert (body["action"]["overdue"], body["action"]["handover"]) == (None, None)
    assert (body["today"]["billed"], body["trends"]) == (None, None)


def test_sales_staff_see_their_own_shops(world):
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    body = board(world["sales"])
    assert body["own_shops"] is True
    assert body["action"]["new_orders"] == 0  # the waiting order is another shop's
    assert body["action"]["overdue"] == {"shops": 1, "amount": "160.00"}
    assert body["today"]["billed"] == "0.00"
    assert body["trends"]["billed_previous_30_days"] == "210.00"
    assert body["trends"]["top_shops"] == []


def test_compliance_failures_once_the_modules_are_on(world):
    from apps.compliance.tests.conftest import switch_on

    switch_on(world["t"], "einvoice")
    switch_on(world["t"], "ewaybill")
    action = board(world["owner"])["action"]
    assert (action["failed_irns"], action["failed_ewaybills"]) == (0, 0)


def test_another_business_sees_none_of_it(world):
    body = board(world["other"])
    assert body["action"]["new_orders"] == 0
    assert body["today"]["orders_received"] == {"count": 0, "amount": "0.00"}
    assert body["trends"]["billed_30_days"] == "0.00"
