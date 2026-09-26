"""Inventory API (PLAN §3.7, ADR-041): every route, tenant isolation, role limits, hidden costs,
idempotent posting and the reports."""

import io
from decimal import Decimal
from uuid import uuid4

import openpyxl
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.catalog.models import Brand, Category, ProductBarcode
from apps.inventory.models import StockInward, Warehouse
from apps.inventory.tests.helpers import make_product
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"
D = Decimal


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def _client(tenant, role="OWNER"):
    client = APIClient()
    user = make_staff_in(tenant, role)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


def _key():
    return {"HTTP_IDEMPOTENCY_KEY": f"k-{uuid4().hex}"}


def _receive(client, *lines, post=True, **header):
    body = {"lines": [{"product_id": str(p.pk), **extra} for p, extra in lines], "post": post}
    return client.post(f"{API}/stock/inwards/", {**body, **header}, format="json", **_key())


def _adjust(client, *lines, reason="OPENING_STOCK", note="Opening count"):
    body = {
        "reason_code": reason,
        "note": note,
        "lines": [{"product_id": str(p.pk), "mode": m, "quantity": q} for p, m, q in lines],
    }
    return client.post(f"{API}/stock/adjustments/", body, format="json", **_key())


@pytest.fixture
def setup(tenant_a, tenant_b):
    """Tenant A with stock, a receipt awaiting cost and an alert; tenant B with its own."""
    data = {}
    for tenant, prefix in ((tenant_a, "A"), (tenant_b, "B")):
        with tenant_context(tenant.pk):
            brand = Brand.objects.create(name=f"{prefix} brand")
            category = Category.objects.create(name=f"{prefix} food", slug=f"{prefix}-food")
        low = make_product(
            tenant,
            f"{prefix}-LOW",
            reorder_level=D("10"),
            cost_price=D("4.00"),
            brand=brand,
            category=category,
        )
        plain = make_product(tenant, f"{prefix}-PLAIN", category=category)
        with tenant_context(tenant.pk):
            ProductBarcode.objects.create(product=low, barcode=f"890{prefix}0001")
        owner = _client(tenant)
        assert _adjust(owner, (low, "ADD", "5"), (plain, "ADD", "20")).status_code == 201
        warehouse = _client(tenant, "WAREHOUSE")
        pending = _receive(warehouse, (plain, {"entered_qty": "3"})).json()
        data[prefix] = {
            "tenant": tenant,
            "low": low,
            "plain": plain,
            "pending": pending,
            "brand": brand,
            "category": category,
        }
    return data


@covers(
    "warehouses",
    "warehouse-detail",
    "stock",
    "stock-summary",
    "stock-lookup",
    "stock-movements",
    "stock-alerts",
    "stock-inwards",
    "stock-inward-detail",
    "stock-inward-post",
    "stock-inward-complete-costs",
    "stock-adjustments",
    "stock-adjustment-detail",
    "stock-detail",
    "stock-reorder-level",
    "report-low-stock",
    "report-low-stock-summary",
    "report-low-stock-export",
    "report-valuation",
    "report-valuation-products",
    "report-valuation-export",
)
def test_tenant_isolation(setup):
    a, b = setup["A"], setup["B"]
    client = _client(a["tenant"])
    b_ids = {str(b["low"].pk), str(b["plain"].pk)}

    def ids(response, key="id"):
        assert response.status_code == 200, response.content
        return {row[key] if key == "id" else row[key]["id"] for row in response.json()["results"]}

    # Lists only ever show tenant A.
    assert ids(client.get(f"{API}/stock/")) == {str(a["low"].pk), str(a["plain"].pk)}
    assert not ids(client.get(f"{API}/stock/movements/"), "product") & b_ids
    assert not ids(client.get(f"{API}/stock/alerts/"), "product") & b_ids
    assert ids(client.get(f"{API}/stock/inwards/")) == {a["pending"]["id"]}
    assert len(client.get(f"{API}/stock/adjustments/").json()["results"]) == 1
    assert ids(client.get(f"{API}/reports/stock/low-stock/")) == {str(a["low"].pk)}
    assert client.get(f"{API}/reports/stock/low-stock/summary/").json() == {
        "low_stock": 1,
        "without_reorder_level": 1,  # A-PLAIN only; tenant B's products don't count
    }
    assert ids(client.get(f"{API}/reports/stock/valuation/products/")) == {
        str(a["low"].pk),
        str(a["plain"].pk),
    }
    valuation = client.get(f"{API}/reports/stock/valuation/").json()
    assert valuation["total_value"] == "20.00" and valuation["missing_cost"] == 1
    warehouses = client.get(f"{API}/warehouses/").json()
    assert [w["id"] for w in warehouses] == [str(_warehouse(a["tenant"]).pk)]
    summary = client.get(f"{API}/stock/summary/").json()
    assert summary == {
        "alerts": {"LOW_STOCK": 1, "OUT_OF_STOCK": 0, "BACKORDER_DEMAND": 0},
        "receipts_awaiting_cost": 1,
    }
    for path in ("low-stock/export/", "valuation/export/"):
        book = _book(client.get(f"{API}/reports/stock/{path}"))
        codes = {row[0] for row in book.iter_rows(min_row=2, values_only=True)}
        assert not codes & {"B-LOW", "B-PLAIN"}

    # Tenant B's records can't be read or changed by id.
    b_receipt = b["pending"]["id"]
    b_line = b["pending"]["lines"][0]["id"]
    with tenant_context(b["tenant"].pk):
        b_adjustment = str(_b_adjustment())
    not_found = [
        client.get(f"{API}/stock/{b['low'].pk}/"),
        client.patch(
            f"{API}/stock/{b['low'].pk}/reorder-level/", {"reorder_level": "1"}, format="json"
        ),
        client.get(f"{API}/stock/lookup/", {"code": "890B0001"}),
        client.get(f"{API}/stock/lookup/", {"code": "B-LOW"}),
        client.get(f"{API}/stock/inwards/{b_receipt}/"),
        client.patch(
            f"{API}/stock/inwards/{b_receipt}/",
            {"lines": [{"product_id": str(a["low"].pk), "entered_qty": "1"}]},
            format="json",
        ),
        client.delete(f"{API}/stock/inwards/{b_receipt}/"),
        client.post(f"{API}/stock/inwards/{b_receipt}/post/", **_key()),
        client.post(
            f"{API}/stock/inwards/{b_receipt}/complete-costs/",
            {"costs": [{"line_id": b_line, "entered_cost": "1"}]},
            format="json",
            **_key(),
        ),
        client.get(f"{API}/stock/adjustments/{b_adjustment}/"),
        client.get(f"{API}/warehouses/{_warehouse(b['tenant']).pk}/"),
        client.patch(
            f"{API}/warehouses/{_warehouse(b['tenant']).pk}/", {"name": "x"}, format="json"
        ),
    ]
    assert [r.status_code for r in not_found] == [404] * len(not_found), [
        (r.request["PATH_INFO"], r.status_code) for r in not_found
    ]
    # Filtering by B's product shows nothing; adjusting or receiving B's product is refused.
    assert (
        client.get(f"{API}/stock/movements/", {"product": str(b["low"].pk)}).json()["results"] == []
    )
    assert _adjust(client, (b["low"], "ADD", "1")).status_code == 400
    assert _receive(client, (b["low"], {"entered_qty": "1"})).status_code == 400
    b_owner = _client(b["tenant"])
    assert b_owner.get(f"{API}/stock/{b['low'].pk}/").json()["on_hand"] == "5.000"
    with tenant_context(b["tenant"].pk):
        assert StockInward.objects.get(pk=b_receipt).cost_pending_lines == 1


def _warehouse(tenant):
    with tenant_context(tenant.pk):
        return Warehouse.objects.get(is_default=True)


def _b_adjustment():
    from apps.inventory.models import StockAdjustment

    return StockAdjustment.objects.get().pk


def _book(response):
    assert response.status_code == 200
    return openpyxl.load_workbook(io.BytesIO(response.content)).active


# --- Costs are hidden without pricing.view -----------------------------------------------------


def test_costs_are_hidden_without_pricing_view(setup):
    a = setup["A"]
    owner = _client(a["tenant"])
    receipt = _receive(owner, (a["low"], {"entered_qty": "2", "entered_cost": "6"})).json()
    assert receipt["total_cost"] == "12.00" and receipt["lines"][0]["unit_cost"] == "6.0000"
    warehouse = _client(a["tenant"], "WAREHOUSE")
    hidden = warehouse.get(f"{API}/stock/inwards/{receipt['id']}/").json()
    assert hidden["total_cost"] is None
    assert {hidden["lines"][0][k] for k in ("entered_cost", "unit_cost", "line_cost")} == {None}
    moves = warehouse.get(f"{API}/stock/movements/", {"reference": receipt["id"]}).json()
    assert moves["results"][0]["unit_cost"] is None and moves["results"][0]["value"] is None
    detail = warehouse.get(f"{API}/stock/{a['low'].pk}/").json()
    assert detail["cost_price"] is None and detail["recent_movements"][0]["value"] is None
    assert warehouse.get(f"{API}/stock/summary/").json()["receipts_awaiting_cost"] is None
    refused = _receive(warehouse, (a["low"], {"entered_qty": "1", "entered_cost": "1"}))
    assert refused.status_code == 400
    shown = owner.get(f"{API}/stock/movements/", {"reference": receipt["id"]}).json()
    assert shown["results"][0]["value"] == "12.00"


def test_pricing_view_users_can_open_receipts_awaiting_cost(setup):
    a = setup["A"]
    accounts = _client(a["tenant"], "ACCOUNTS")  # pricing.view, no stock.inward
    rows = accounts.get(f"{API}/stock/inwards/", {"awaiting_cost": "true"}).json()["results"]
    assert [r["id"] for r in rows] == [a["pending"]["id"]]
    assert accounts.get(f"{API}/stock/inwards/{a['pending']['id']}/").status_code == 200
    assert accounts.post(f"{API}/stock/inwards/", {}, format="json", **_key()).status_code == 403
    line = a["pending"]["lines"][0]["id"]
    body = {"costs": [{"line_id": line, "entered_cost": "2"}]}
    url = f"{API}/stock/inwards/{a['pending']['id']}/complete-costs/"
    assert accounts.post(url, body, format="json", **_key()).status_code == 403  # manage only
    manager = _client(a["tenant"], "MANAGER")
    done = manager.post(url, body, format="json", **_key())
    assert done.status_code == 200 and done.json()["cost_pending_lines"] == 0
    assert manager.get(f"{API}/stock/summary/").json()["receipts_awaiting_cost"] == 0


# --- Receipts through the API ------------------------------------------------------------------


def test_draft_then_post_is_idempotent(setup):
    a = setup["A"]
    owner = _client(a["tenant"])
    draft = _receive(owner, (a["low"], {"entered_qty": "4"}), post=False, supplier_name="Acme")
    assert draft.status_code == 201 and draft.json()["status"] == "DRAFT"
    receipt_id = draft.json()["id"]
    edited = owner.patch(
        f"{API}/stock/inwards/{receipt_id}/",
        {"supplier_name": "Acme", "lines": [{"product_id": str(a["low"].pk), "entered_qty": "6"}]},
        format="json",
    )
    assert edited.json()["lines"][0]["quantity"] == "6.000"
    key = _key()
    first = owner.post(f"{API}/stock/inwards/{receipt_id}/post/", **key)
    again = owner.post(f"{API}/stock/inwards/{receipt_id}/post/", **key)
    assert first.status_code == again.status_code == 200
    assert first.json()["number"] == again.json()["number"]
    assert owner.get(f"{API}/stock/{a['low'].pk}/").json()["on_hand"] == "11.000"
    other_key = owner.post(f"{API}/stock/inwards/{receipt_id}/post/", **_key())
    assert other_key.status_code == 409
    assert other_key.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    missing = owner.post(f"{API}/stock/inwards/{receipt_id}/post/")
    assert missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_pack_entry_and_lookup(setup):
    a = setup["A"]
    owner = _client(a["tenant"])
    from apps.catalog.models import Unit

    with tenant_context(a["tenant"].pk):
        box = Unit.objects.get(code="BOX")
    boxed = make_product(a["tenant"], "A-BOX", pack_unit=box, pack_size=D("12"))
    found = owner.get(f"{API}/stock/lookup/", {"code": " a-box "}).json()
    assert found["id"] == str(boxed.pk) and found["pack_unit"]["code"] == "BOX"
    assert owner.get(f"{API}/stock/lookup/", {"code": "890A0001"}).json()["code"] == "A-LOW"
    missing = owner.get(f"{API}/stock/lookup/", {"code": "nope"})
    assert missing.status_code == 404
    receipt = _receive(owner, (boxed, {"entered_qty": "2", "entered_unit": "PACK"})).json()
    assert receipt["lines"][0]["quantity"] == "24.000"


# --- Adjustments, reorder level, filters ------------------------------------------------------


def test_adjustment_errors_are_plain(setup):
    a = setup["A"]
    owner = _client(a["tenant"])
    response = _adjust(owner, (a["low"], "REMOVE", "9"), reason="DAMAGE", note="Broken")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    counted = _adjust(owner, (a["low"], "COUNTED", "5"), (a["plain"], "COUNTED", "22"))
    body = counted.json()
    assert counted.status_code == 201 and body["unchanged"] == ["A-LOW"]
    assert [line["quantity_change"] for line in body["lines"]] == ["-1.000"]


def test_reorder_level_permissions(setup):
    a = setup["A"]
    url = f"{API}/stock/{a['plain'].pk}/reorder-level/"
    for role, status in (("WAREHOUSE", 200), ("MANAGER", 200), ("SALES", 403), ("ACCOUNTS", 403)):
        response = _client(a["tenant"], role).patch(url, {"reorder_level": "50"}, format="json")
        assert response.status_code == status, role
    assert _client(a["tenant"]).get(f"{API}/stock/{a['plain'].pk}/").json()["status"] == "LOW"


def test_stock_filters(setup):
    a = setup["A"]
    owner = _client(a["tenant"])

    def codes(**params):
        return [r["code"] for r in owner.get(f"{API}/stock/", params).json()["results"]]

    assert codes(status="LOW") == ["A-LOW"]
    assert codes(status="IN_STOCK") == ["A-PLAIN"]
    assert codes(status="OUT") == []
    assert codes(no_reorder_level="true") == ["A-PLAIN"]
    assert codes(search="plain") == ["A-PLAIN"]
    assert codes(brand=str(a["brand"].pk)) == ["A-LOW"]
    assert codes(category=str(a["category"].pk)) == ["A-LOW", "A-PLAIN"]
    assert owner.get(f"{API}/stock/", {"category": "x"}).status_code == 400
    alerts = owner.get(f"{API}/stock/alerts/", {"type": "LOW_STOCK"}).json()["results"]
    assert [x["product"]["code"] for x in alerts] == ["A-LOW"]


def test_valuation_marks_products_without_cost(setup):
    a = setup["A"]
    owner = _client(a["tenant"])
    report = owner.get(f"{API}/reports/stock/valuation/").json()
    assert report["products_valued"] == 1 and report["missing_cost"] == 1
    assert report["by_brand"] == [
        {"name": "A brand", "value": "20.00", "products": 1, "missing_cost": 0},
        {"name": "", "value": "0.00", "products": 1, "missing_cost": 1},
    ]
    missing = owner.get(f"{API}/reports/stock/valuation/products/", {"missing_cost": "true"})
    assert [r["code"] for r in missing.json()["results"]] == ["A-PLAIN"]
    assert missing.json()["results"][0]["value"] is None
    rows = list(_book(owner.get(f"{API}/reports/stock/valuation/export/")).values)
    assert list(rows[1][:2]) == ["A-LOW", "Product A-LOW"] and rows[1][7] == 20
    assert any(r[1] == "Total value" and r[7] == 20 for r in rows)
    assert (
        _client(a["tenant"], "WAREHOUSE").get(f"{API}/reports/stock/valuation/").status_code == 403
    )
    assert (
        _client(a["tenant"], "ACCOUNTS").get(f"{API}/reports/stock/valuation/").status_code == 403
    )


def test_warehouse_can_be_renamed_by_owner_only(setup):
    a = setup["A"]
    warehouse = _warehouse(a["tenant"])
    url = f"{API}/warehouses/{warehouse.pk}/"
    manager = _client(a["tenant"], "MANAGER")
    assert manager.patch(url, {"name": "Godown"}, format="json").status_code == 403
    owner = _client(a["tenant"])
    response = owner.patch(url, {"name": "Godown", "pincode": "411001"}, format="json")
    assert response.status_code == 200 and response.json()["name"] == "Godown"
    assert owner.patch(url, {"pincode": "12"}, format="json").status_code == 400
