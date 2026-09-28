"""Receivables, ageing, summary, statements, dues and adjustments (PLAN §3.10): roles, sales
visibility, and another tenant seeing and changing nothing."""

from datetime import timedelta
from decimal import Decimal as D
from typing import Any
from uuid import uuid4

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.ledger import services as ledger
from apps.ledger.models import LedgerAdjustment
from apps.orders.tests.helpers import add_stock, client_for, make_shop, settings
from apps.payments import services as payments
from apps.payments.services import PaymentInput
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
TODAY = today_ist()


def key() -> dict[str, Any]:
    return {"HTTP_IDEMPOTENCY_KEY": f"k{uuid4().hex}"}


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("123.45"))
    add_stock(tenant_a, a, "100")
    with tenant_context(tenant_a.pk):
        ledger.post_adjustment(
            shop.pk,
            "OPENING_DEBIT",
            D("100.00"),
            on=TODAY - timedelta(days=40),
            narration="Old books",
            by=None,
        )
    invoice = ship_invoice(tenant_a, shop, owner, (a, "2"))  # ₹259, due in 30 days
    return {"t": tenant_a, "owner": owner, "shop": shop, "invoice": invoice, "a": a,
            "client": client_for(tenant_a, owner)}  # fmt: skip


@covers("receivables", "receivables-ageing", "receivables-summary")
def test_receivables_ageing_and_summary(world):
    c = world["client"]
    page = c.get("/api/v1/receivables/").json()
    [row] = page["results"]
    assert (row["retailer"]["id"], row["owed"], row["overdue"], row["days_overdue"]) == (
        str(world["shop"].pk),
        "359.00",
        "100.00",
        10,  # the old bill (40 days ago) was due after the 30-day terms
    )
    assert page["totals"]["owed"] == "359.00" and page["count"] == 1
    assert c.get("/api/v1/receivables/?search=nobody").json()["results"] == []
    ageing = c.get("/api/v1/receivables/ageing/").json()
    assert ageing["basis"] == "INVOICE_DATE"
    assert ageing["results"][0]["buckets"]["d0_30"] == "259.00"
    assert ageing["results"][0]["buckets"]["d31_60"] == "100.00"
    by_due = c.get("/api/v1/receivables/ageing/?basis=DUE_DATE").json()
    assert by_due["results"][0]["buckets"]["not_due"] == "259.00"
    assert c.get("/api/v1/receivables/ageing/?basis=WEEKLY").status_code == 400
    summary = c.get("/api/v1/receivables/summary/").json()
    assert (summary["overdue"], summary["shops_overdue"]) == ("100.00", 1)
    assert summary["collections_pending_handover"] == "0.00"  # the owner records payments
    sales = client_for(world["t"], make_staff_in(world["t"], "SALES"))
    assert sales.get("/api/v1/receivables/summary/").json()["collections_pending_handover"] is None


@covers("retailer-ledger", "retailer-dues")
def test_statement_and_dues(world):
    c, shop = world["client"], world["shop"]
    with tenant_context(world["t"].pk):
        payments.record_payment(
            PaymentInput(shop.pk, D("150.00"), "CASH", TODAY), by=world["owner"]
        )
    statement = c.get(f"/api/v1/retailers/{shop.pk}/ledger/").json()
    assert [line["entry_type"] for line in statement["lines"]] == [
        "OPENING_BALANCE",
        "INVOICE",
        "PAYMENT",
    ]
    assert [line["balance"] for line in statement["lines"]] == ["100.00", "359.00", "209.00"]
    assert (statement["opening_balance"], statement["closing_balance"]) == ("0.00", "209.00")
    recent = c.get(
        f"/api/v1/retailers/{shop.pk}/ledger/?date_from={TODAY - timedelta(days=5)}"
    ).json()
    assert recent["opening_balance"] == "100.00" and len(recent["lines"]) == 2
    assert c.get(f"/api/v1/retailers/{shop.pk}/ledger/?date_from=2020-01-01").status_code == 400
    dues = c.get(f"/api/v1/retailers/{shop.pk}/dues/").json()
    assert [(d["kind"], d["balance_due"]) for d in dues["dues"]] == [("INVOICE", "209.00")]
    assert dues["unused_money"] == [] and dues["position"]["balance"] == "209.00"


@covers("ledger-adjustments")
def test_adjustments(world):
    c = world["client"]
    body = {
        "retailer": str(world["shop"].pk),
        "kind": "CREDIT",
        "amount": "50.00",
        "date": str(TODAY),
        "narration": "Festival scheme",
    }
    headers = key()
    made = c.post("/api/v1/ledger/adjustments/", body, format="json", **headers)
    assert made.status_code == 201, made.json()
    assert (
        c.post("/api/v1/ledger/adjustments/", body, format="json", **headers).json() == made.json()
    )
    assert made.json()["unapplied_amount"] == "0.00"  # used at once for what is owed
    future = {**body, "date": str(TODAY + timedelta(days=1))}
    assert c.post("/api/v1/ledger/adjustments/", future, format="json", **key()).status_code == 400
    sales = client_for(world["t"], make_staff_in(world["t"], "SALES"))
    assert (
        sales.post("/api/v1/ledger/adjustments/", body, format="json", **key()).status_code == 403
    )
    with tenant_context(world["t"].pk):
        assert LedgerAdjustment.objects.filter(kind="CREDIT").count() == 1


def test_roles_and_sales_visibility(world):
    shop = world["shop"]
    warehouse = client_for(world["t"], make_staff_in(world["t"], "WAREHOUSE"))
    for url in ("/api/v1/receivables/", f"/api/v1/retailers/{shop.pk}/ledger/"):
        assert warehouse.get(url).status_code == 403, url
    salesman = make_staff_in(world["t"], "SALES")
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    c = client_for(world["t"], salesman)
    assert c.get("/api/v1/receivables/").json()["results"] == []
    assert c.get(f"/api/v1/retailers/{shop.pk}/ledger/").status_code == 404
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=shop.pk).update(salesperson=salesman)
    assert c.get(f"/api/v1/retailers/{shop.pk}/ledger/").status_code == 200


def test_another_tenant_sees_and_changes_nothing(world, tenant_b):
    outsider = client_for(tenant_b, make_staff_in(tenant_b, "OWNER"))
    shop = world["shop"]
    assert outsider.get("/api/v1/receivables/").json()["results"] == []
    assert outsider.get("/api/v1/receivables/ageing/").json()["results"] == []
    assert outsider.get("/api/v1/receivables/summary/").json()["owed"] == "0.00"
    for url in (f"/api/v1/retailers/{shop.pk}/ledger/", f"/api/v1/retailers/{shop.pk}/dues/"):
        assert outsider.get(url).status_code == 404, url
    body = {
        "retailer": str(shop.pk),
        "kind": "DEBIT",
        "amount": "10.00",
        "date": str(TODAY),
        "narration": "x",
    }
    assert (
        outsider.post("/api/v1/ledger/adjustments/", body, format="json", **key()).status_code
        == 404
    )
    with tenant_context(world["t"].pk):
        assert LedgerAdjustment.objects.count() == 1
