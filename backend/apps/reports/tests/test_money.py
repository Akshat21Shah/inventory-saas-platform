"""Money reports (ADR-050): receivables ageing, collections and salesperson collections, for the
office and for sales staff limited to their own shops."""

from decimal import Decimal as D
from typing import Any

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_stock, client_for, make_shop, settings
from apps.payments import services as payments
from apps.payments.services import PaymentInput
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
API = "/api/v1"


@pytest.fixture
def world(tenant_a, tenant_b):
    owner = make_staff_in(tenant_a, "OWNER")
    ravi, sita = make_staff_in(tenant_a, "SALES"), make_staff_in(tenant_a, "SALES")
    product = make_product(tenant_a, base_price=D("100"))
    add_stock(tenant_a, product, "100")
    anand = make_shop(tenant_a, "9876500081", shop_name="Anand Stores")
    balaji = make_shop(tenant_a, "9876500082", shop_name="Balaji Mart")
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=anand.pk).update(salesperson=ravi)
        Retailer.objects.filter(pk=balaji.pk).update(salesperson=sita)
    ship_invoice(tenant_a, anand, owner, (product, "10"))  # ₹1,050
    ship_invoice(tenant_a, balaji, owner, (product, "5"))  # ₹525
    today = today_ist()
    with tenant_context(tenant_a.pk):
        cash = payments.collect_payment(PaymentInput(anand.pk, D("100"), "CASH", today), by=ravi)
        upi = payments.collect_payment(PaymentInput(anand.pk, D("50"), "UPI", today), by=ravi)
        payments.hand_over([upi.pk], by=owner)
        payments.record_payment(
            PaymentInput(anand.pk, D("200"), "BANK_TRANSFER", today, reference_no="UTR1"),
            by=owner,
        )
        payments.collect_payment(
            PaymentInput(
                balaji.pk, D("70"), "CHEQUE", today, cheque_number="004512", bank_name="SBI"
            ),
            by=sita,
        )
    return {
        "t": tenant_a,
        "owner": client_for(tenant_a, owner),
        "ravi": client_for(tenant_a, ravi),
        "ravi_user": ravi,
        "sita_user": sita,
        "warehouse": client_for(tenant_a, make_staff_in(tenant_a, "WAREHOUSE")),
        "other": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
        "cash": cash,
        "period": f"date_from={today.isoformat()}&date_to={today.isoformat()}",
    }


def report(client: Any, code: str, query: str = "") -> dict[str, Any]:
    response = client.get(f"{API}/reports/{code}/?{query}")
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()
    return body


def test_receivables_ageing_per_shop(world):
    body = report(world["owner"], "receivables_ageing")
    rows = {r["name"]: r for r in body["rows"]}
    # Aged from the bill date: today's bills are 0-30 days old.
    assert (rows["Anand Stores"]["owed"], rows["Anand Stores"]["d0_30"]) == ("700.00", "700.00")
    assert rows["Balaji Mart"]["net"] == "455.00"  # the cheque is credited when received
    assert rows["Anand Stores"]["salesperson"] == world["ravi_user"].full_name
    assert body["totals"]["owed"] == "1155.00"
    assert body["notes"] == ["Aged from the bill date."]
    assert report(world["owner"], "receivables_ageing", "overdue_only=true")["rows"] == []
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    mine = report(world["ravi"], "receivables_ageing")
    assert [r["name"] for r in mine["rows"]] == ["Anand Stores"]
    assert world["warehouse"].get(f"{API}/reports/receivables_ageing/").status_code == 403


def test_collections_in_the_period(world):
    body = report(world["owner"], "collections", world["period"])
    assert len(body["rows"]) == 4
    assert body["totals"]["amount"] == "420.00"
    assert body["notes"][0] == (
        "By mode: Bank transfer ₹200.00, Cash ₹100.00, Cheque ₹70.00, UPI ₹50.00."
    )
    cash = report(world["owner"], "collections", f"{world['period']}&mode=CASH")
    [row] = cash["rows"]
    assert (row["number"], row["collector"], row["handover"]) == (
        world["cash"].number,
        world["ravi_user"].full_name,
        "With salesman",
    )
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    mine = report(world["ravi"], "collections", world["period"])
    assert {r["shop"] for r in mine["rows"]} == {"Anand Stores"}


def test_salesperson_collections(world):
    body = report(world["owner"], "salesperson_collections", world["period"])
    rows = {r["user_id"]: r for r in body["rows"]}
    ravi = rows[str(world["ravi_user"].pk)]
    assert (ravi["count"], ravi["cash"], ravi["upi"], ravi["total"]) == (
        2,
        "100.00",
        "50.00",
        "150.00",
    )
    assert (ravi["handed_over"], ravi["with_salesman"], ravi["from_shops"]) == (
        "50.00",
        "100.00",
        "350.00",  # every payment from Anand Stores, the bank transfer included
    )
    sita = rows[str(world["sita_user"].pk)]
    assert (sita["cheque"], sita["with_salesman"]) == ("70.00", "70.00")
    assert body["totals"]["total"] == "220.00"
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    mine = report(world["ravi"], "salesperson_collections", world["period"])
    assert [r["user_id"] for r in mine["rows"]] == [str(world["ravi_user"].pk)]


def test_another_business_sees_none_of_it(world):
    assert report(world["other"], "receivables_ageing")["rows"] == []
    assert report(world["other"], "collections", world["period"])["rows"] == []
    assert report(world["other"], "salesperson_collections", world["period"])["rows"] == []
