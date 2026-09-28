"""Payment APIs (PLAN §3.10, ADR-046 items 6 and 10): recording with an Idempotency-Key and
chosen dues, cheques, reversals, receipts, salesman collections and handover, reallocation;
roles, sales visibility, and another tenant seeing and changing nothing."""

from decimal import Decimal as D
from typing import Any
from uuid import uuid4

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.ledger.models import Allocation
from apps.orders.tests.helpers import add_stock, client_for, make_shop, settings
from apps.payments.models import Payment
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
TODAY = str(today_ist())


def key() -> dict[str, Any]:
    return {"HTTP_IDEMPOTENCY_KEY": f"k{uuid4().hex}"}


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("123.45"))
    add_stock(tenant_a, a, "100")
    first = ship_invoice(tenant_a, shop, owner, (a, "2"))  # ₹259
    second = ship_invoice(tenant_a, shop, owner, (a, "1"))  # ₹130
    return {"t": tenant_a, "owner": owner, "shop": shop, "first": first, "second": second,
            "client": client_for(tenant_a, owner)}  # fmt: skip


def _body(world, amount, mode="CASH", **extra):
    return {
        "retailer": str(world["shop"].pk),
        "amount": amount,
        "mode": mode,
        "payment_date": TODAY,
        **extra,
    }


@covers("payments", "payment", "payment-receipt", "payment-regenerate-receipt")
def test_record_list_and_receipt(world, django_capture_on_commit_callbacks):
    c = world["client"]
    body = _body(
        world,
        "200.00",
        "UPI",
        reference_no="UTR123",
        pay_first=[
            {"target_type": "INVOICE", "target_id": str(world["second"].pk), "amount": "130.00"}
        ],
    )
    headers = key()
    with django_capture_on_commit_callbacks(execute=True):
        made = c.post("/api/v1/payments/", body, format="json", **headers)
    assert made.status_code == 201, made.json()
    payment = made.json()
    assert c.post("/api/v1/payments/", body, format="json", **headers).json()["id"] == payment["id"]
    assert payment["number"].startswith("RCT/") and payment["status"] == "RECEIVED"
    assert [(u["target_number"], u["amount"], u["automatic"]) for u in payment["used_for"]] == [
        (world["second"].number, "130.00", False),
        (world["first"].number, "70.00", True),
    ]
    assert c.get("/api/v1/payments/?mode=UPI").json()["results"][0]["id"] == payment["id"]
    assert c.get("/api/v1/payments/?search=UTR123").json()["results"]
    assert c.get("/api/v1/payments/?mode=CARD").status_code == 400
    assert c.get(f"/api/v1/payments/{payment['id']}/").json()["recorded_by_name"] is not None
    receipt = c.get(f"/api/v1/payments/{payment['id']}/receipt/").json()
    assert receipt["status"] == "READY" and receipt["url"]
    assert c.post(f"/api/v1/payments/{payment['id']}/regenerate-receipt/").status_code == 202
    advances_off = client_for(world["t"], world["owner"])
    settings(world["t"], payments__hold_advances=False)
    refused = advances_off.post("/api/v1/payments/", _body(world, "500.00"), format="json", **key())
    assert refused.json()["error"]["code"] == "PAYMENT_EXCEEDS_OUTSTANDING"


@covers(
    "payment-clear",
    "payment-bounce",
    "payment-reverse",
    "payment-allocate",
    "payment-allocation-reverse",
)
def test_cheques_reversal_and_allocation(world):
    c = world["client"]
    settings(world["t"], payments__cheque_credit_timing="ON_CLEARANCE")
    cheque = c.post(
        "/api/v1/payments/", _body(world, "259.00", "CHEQUE", cheque_number="000777"),
        format="json", **key(),
    ).json()  # fmt: skip
    assert (cheque["status"], cheque["credited"]) == ("PENDING_CLEARANCE", False)
    cleared = c.post(f"/api/v1/payments/{cheque['id']}/clear/", {}, format="json").json()
    assert (cleared["status"], cleared["used_for"][0]["target_number"]) == (
        "CLEARED",
        world["first"].number,
    )
    again = c.post(f"/api/v1/payments/{cheque['id']}/clear/", {}, format="json")
    assert again.status_code == 409
    reversed_ = c.post(
        f"/api/v1/payments/{cheque['id']}/reverse/", {"reason": "Wrong shop"}, format="json"
    ).json()
    assert (reversed_["status"], reversed_["reversal_reason"]) == ("REVERSED", "Wrong shop")
    settings(world["t"], payments__cheque_credit_timing="ON_RECEIPT")
    bouncy = c.post(
        "/api/v1/payments/", _body(world, "100.00", "CHEQUE", cheque_number="000778"),
        format="json", **key(),
    ).json()  # fmt: skip
    bounced = c.post(
        f"/api/v1/payments/{bouncy['id']}/bounce/", {"reason": "No funds"}, format="json"
    ).json()
    assert bounced["status"] == "BOUNCED"
    cash = c.post("/api/v1/payments/", _body(world, "500.00"), format="json", **key()).json()
    assert cash["unapplied_amount"] == "111.00"  # ₹389 owed in all
    with tenant_context(world["t"].pk):
        auto = Allocation.objects.filter(payment_id=cash["id"], invoice=world["second"]).get()
    moved = c.post(
        f"/api/v1/payment-allocations/{auto.pk}/reverse/",
        {"reason": "Hold for the next bill"},
        format="json",
    )
    assert moved.status_code == 200, moved.json()
    allocated = c.post(
        f"/api/v1/payments/{cash['id']}/allocate/",
        {"to": [{"target_type": "INVOICE", "target_id": str(world["second"].pk), "amount": "30"}]},
        format="json",
    ).json()
    assert allocated["unapplied_amount"] == "211.00"


@covers("payments-collect", "payments-handover", "collections-pending-handover")
def test_salesman_collections_and_handover(world):
    salesman = make_staff_in(world["t"], "SALES")
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    sales = client_for(world["t"], salesman)
    body = _body(world, "100.00")
    assert sales.post("/api/v1/payments/collect/", body, format="json", **key()).status_code == 404
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=world["shop"].pk).update(salesperson=salesman)
    made = sales.post("/api/v1/payments/collect/", body, format="json", **key())
    assert made.status_code == 201, made.json()
    assert made.json()["handover_status"] == "WITH_SALESMAN"
    assert sales.post("/api/v1/payments/", body, format="json", **key()).status_code == 403
    assert sales.get("/api/v1/reports/collections-pending-handover/").status_code == 403
    c = world["client"]
    [row] = c.get("/api/v1/reports/collections-pending-handover/").json()
    assert (row["salesman_id"], row["count"], row["amount"]) == (str(salesman.pk), 1, "100.00")
    handed = c.post(
        "/api/v1/payments/handover/", {"payments": [made.json()["id"]]}, format="json"
    ).json()
    assert handed["payments"][0]["handover_status"] == "HANDED_OVER"
    assert c.get("/api/v1/reports/collections-pending-handover/").json() == []
    settings(world["t"], payments__sales_can_collect=False)
    off = sales.post("/api/v1/payments/collect/", body, format="json", **key())
    assert off.status_code == 403


def test_roles(world):
    warehouse = client_for(world["t"], make_staff_in(world["t"], "WAREHOUSE"))
    sales = client_for(world["t"], make_staff_in(world["t"], "SALES"))
    assert warehouse.get("/api/v1/payments/").status_code == 403
    assert sales.get("/api/v1/payments/").status_code == 200
    cash = (
        world["client"]
        .post("/api/v1/payments/", _body(world, "10.00"), format="json", **key())
        .json()
    )
    for url, body in (
        (f"/api/v1/payments/{cash['id']}/reverse/", {"reason": "x"}),
        (f"/api/v1/payments/{cash['id']}/clear/", {}),
        ("/api/v1/payments/handover/", {"payments": [cash["id"]]}),
    ):
        assert sales.post(url, body, format="json").status_code == 403, url


def test_another_tenant_sees_and_changes_nothing(world, tenant_b):
    c = world["client"]
    cash = c.post("/api/v1/payments/", _body(world, "300.00"), format="json", **key()).json()
    with tenant_context(world["t"].pk):
        allocation = Allocation.objects.filter(payment_id=cash["id"]).first()
    assert allocation is not None
    outsider = client_for(tenant_b, make_staff_in(tenant_b, "OWNER"))
    assert outsider.get("/api/v1/payments/").json()["results"] == []
    assert outsider.get("/api/v1/reports/collections-pending-handover/").json() == []
    for url in (f"/api/v1/payments/{cash['id']}/", f"/api/v1/payments/{cash['id']}/receipt/"):
        assert outsider.get(url).status_code == 404, url
    due = {"target_type": "INVOICE", "target_id": str(world["first"].pk), "amount": "1"}
    for url, body, keyed in (
        ("/api/v1/payments/", _body(world, "1.00"), True),
        (f"/api/v1/payments/{cash['id']}/allocate/", {"to": [due]}, False),
        (f"/api/v1/payments/{cash['id']}/clear/", {}, False),
        (f"/api/v1/payments/{cash['id']}/bounce/", {"reason": "x"}, False),
        (f"/api/v1/payments/{cash['id']}/reverse/", {"reason": "x"}, False),
        (f"/api/v1/payments/{cash['id']}/regenerate-receipt/", {}, False),
        ("/api/v1/payments/handover/", {"payments": [cash["id"]]}, False),
        (f"/api/v1/payment-allocations/{allocation.pk}/reverse/", {"reason": "x"}, False),
    ):
        response = outsider.post(url, body, format="json", **(key() if keyed else {}))
        assert response.status_code == 404, (url, response.status_code)
    outside_sales = client_for(tenant_b, make_staff_in(tenant_b, "SALES"))
    collect = outside_sales.post(
        "/api/v1/payments/collect/", _body(world, "1.00"), format="json", **key()
    )
    assert collect.status_code == 404
    with tenant_context(world["t"].pk):
        assert Payment.objects.count() == 1
        assert Payment.objects.get().status == "RECEIVED"
        assert Allocation.objects.filter(reverses__isnull=False).count() == 0
