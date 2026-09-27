"""Opening stock import (PLAN task 3.7, ADR-041): add to stock or set to a count, optional cost,
posted as "Opening stock" adjustments."""

import io
from decimal import Decimal as D

import openpyxl
import pytest

from apps.catalog.models import Product, Unit
from apps.dataio.tests.helpers import API, _client, commit, messages, upload, xlsx
from apps.inventory.models import StockAdjustment, StockLevel, StockMovement
from apps.inventory.tests.helpers import make_product
from apps.platform.services import set_tenant_settings
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
HEADER = ["Product code", "Quantity", "Cost per unit (before GST)"]


def _on_hand(tenant, code):
    with tenant_context(tenant.pk):
        return StockLevel.objects.get(product__code=code).quantity_on_hand


def _cost(tenant, code):
    with tenant_context(tenant.pk):
        return Product.objects.get(code=code).cost_price


def _rows(response):
    assert response.status_code == 200
    return list(openpyxl.load_workbook(io.BytesIO(response.content)).worksheets[0].values)


def _stock_file(*rows, header=HEADER):
    return xlsx([header, *rows], name="stock.xlsx")


def test_add_to_stock_with_costs(tenant_a, owner, run):
    make_product(tenant_a, "A")
    make_product(tenant_a, "B", cost_price=D("5.00"))
    job = upload(
        owner,
        run,
        _stock_file(["A", "10", "7.5"], ["b", "4", ""]),
        mode="STOCK_ADD",
        kind="OPENING_STOCK",
    )
    assert job["status"] == "VALIDATED" and job["counts"]["update"] == 2
    assert job["changes"][0]["changes"] == {"Stock": ["0", "10"]}
    job = commit(owner, run, job)
    assert job["counts"]["applied"] == 2
    assert (_on_hand(tenant_a, "A"), _on_hand(tenant_a, "B")) == (10, 4)
    assert _cost(tenant_a, "A") == D("7.50") and _cost(tenant_a, "B") == D("5.00")
    with tenant_context(tenant_a.pk):
        adjustment = StockAdjustment.objects.get()  # one document for the file (ADR-042)
        assert adjustment.reason_code == "OPENING_STOCK"
        assert adjustment.note == "Opening stock import: stock.xlsx"
        assert adjustment.lines.count() == 2
        move = StockMovement.objects.get(product__code="A")
        assert (move.movement_type, move.unit_cost, move.value) == (
            "ADJUSTMENT_IN",
            D("7.5"),
            D("75.00"),
        )


def test_set_to_count(tenant_a, owner, run):
    for code in ("A", "B", "C"):
        make_product(tenant_a, code)
    upload_ = upload(owner, run, _stock_file(["A", "10"], ["B", "5"]), "STOCK_ADD", "OPENING_STOCK")
    commit(owner, run, upload_)
    job = upload(
        owner,
        run,
        _stock_file(["A", "7", "9"], ["B", "5"], ["C", "0"]),
        mode="STOCK_SET",
        kind="OPENING_STOCK",
    )
    assert job["counts"] == {**job["counts"], "update": 1, "unchanged": 2, "error": 0}
    assert job["changes"][0]["warnings"] == ["Stock goes down, so the cost is not used."]
    commit(owner, run, job)
    assert [_on_hand(tenant_a, c) for c in "ABC"] == [7, 5, 0]
    assert _cost(tenant_a, "A") is None


@pytest.mark.parametrize(
    ("row", "mode", "message"),
    [
        (["NOPE", "1"], "STOCK_ADD", "No product has the code NOPE"),
        (["A", ""], "STOCK_ADD", "Enter the quantity"),
        (["A", "0"], "STOCK_ADD", "above 0"),
        (["A", "-1"], "STOCK_SET", "negative"),
        (["A", "1.5"], "STOCK_ADD", "whole numbers"),
        (["A", "2", "x"], "STOCK_ADD", "isn't an amount"),
    ],
)
def test_row_errors(tenant_a, owner, run, row, mode, message):
    make_product(tenant_a, "A")
    job = upload(owner, run, _stock_file(row), mode=mode, kind="OPENING_STOCK")
    assert any(message in m for m in messages(job)), messages(job)


def test_duplicates_and_decimal_units(tenant_a, owner, run):
    with tenant_context(tenant_a.pk):
        kg = Unit.objects.get(code="KG")
    make_product(tenant_a, "RICE", unit=kg)
    job = upload(
        owner,
        run,
        _stock_file(["RICE", "2.5"], ["rice", "1"]),
        mode="STOCK_ADD",
        kind="OPENING_STOCK",
    )
    assert job["counts"]["update"] == 1
    assert any("also in row 2" in m for m in messages(job))


def test_costs_need_costs_manage(tenant_a, run):
    make_product(tenant_a, "A")
    warehouse = _client(tenant_a, "WAREHOUSE")
    job = upload(warehouse, run, _stock_file(["A", "3", "2"]), "STOCK_ADD", "OPENING_STOCK")
    assert any("manage costs" in m for m in messages(job))
    ok = upload(warehouse, run, _stock_file(["A", "3"]), "STOCK_ADD", "OPENING_STOCK")
    commit(warehouse, run, ok)
    assert _on_hand(tenant_a, "A") == 3
    header = _rows(warehouse.get(f"{API}/imports/templates/opening_stock/"))[0]
    assert "Cost per unit (before GST)" not in header


def test_manual_cost_method_warns(tenant_a, owner, run):
    with tenant_context(tenant_a.pk):
        set_tenant_settings({"stock.cost_method": "MANUAL"}, user=None)
    make_product(tenant_a, "A", cost_price=D("1.00"))
    job = upload(owner, run, _stock_file(["A", "3", "2"]), "STOCK_ADD", "OPENING_STOCK")
    assert "cost price won't change" in job["changes"][0]["warnings"][0]
    commit(owner, run, job)
    assert _cost(tenant_a, "A") == D("1.00")


def test_modes_are_per_kind(tenant_a, owner):
    from apps.dataio.tests.helpers import xlsx as book

    wrong = owner.post(
        f"{API}/imports/",
        {"kind": "OPENING_STOCK", "mode": "ADD_ONLY", "file": book([HEADER])},
        format="multipart",
    )
    assert wrong.status_code == 400
    assert "Add to stock" in str(wrong.json())
    also_wrong = owner.post(
        f"{API}/imports/",
        {"kind": "PRODUCTS", "mode": "STOCK_ADD", "file": book([["Code"]])},
        format="multipart",
    )
    assert also_wrong.status_code == 400
    sales = _client(tenant_a, "SALES")  # no stock.adjust
    denied = sales.post(
        f"{API}/imports/",
        {"kind": "OPENING_STOCK", "mode": "STOCK_ADD", "file": book([HEADER])},
        format="multipart",
    )
    assert denied.status_code == 403


@covers("stock-count-export")
def test_stock_count_export(tenant_a, tenant_b, owner, run):
    make_product(tenant_a, "A", cost_price=D("2.00"))
    make_product(tenant_b, "B-OTHER")
    commit(owner, run, upload(owner, run, _stock_file(["A", "6"]), "STOCK_ADD", "OPENING_STOCK"))
    rows = _rows(owner.get(f"{API}/stock/export/"))
    assert rows[0] == ("Product code", "Quantity", "Cost per unit (before GST)", "Product name")
    assert rows[1:] == [("A", "6", "2.00", "Product A")]
    assert _client(tenant_a, "SALES").get(f"{API}/stock/export/").status_code == 403
    warehouse_rows = _rows(_client(tenant_a, "WAREHOUSE").get(f"{API}/stock/export/"))
    assert warehouse_rows[0] == ("Product code", "Quantity", "Product name")


def test_rows_that_changed_since_validation_are_reported_and_the_rest_is_one_document(
    tenant_a, owner, run
):
    from uuid import uuid4

    from django.db import transaction

    from apps.inventory import services

    a = make_product(tenant_a, "A")
    make_product(tenant_a, "B")
    first = upload(owner, run, _stock_file(["A", "5"], ["B", "5"]), "STOCK_ADD", "OPENING_STOCK")
    commit(owner, run, first)
    job = upload(owner, run, _stock_file(["A", "1"], ["B", "9"]), "STOCK_SET", "OPENING_STOCK")
    assert job["counts"]["update"] == 2
    # Before the commit, an order reserves 3 of A: setting A to 1 is no longer possible.
    with tenant_context(tenant_a.pk), transaction.atomic():
        level = services.lock_levels([a.pk], services.default_warehouse())[a.pk]
        services.reserve(level, D("3"), services.Ref("ORDER", uuid4()), by=None)
    job = commit(owner, run, job)
    assert (job["counts"]["applied"], job["counts"]["failed"]) == (1, 1)
    assert any("reserved for orders" in m for m in messages(job))
    assert (_on_hand(tenant_a, "A"), _on_hand(tenant_a, "B")) == (5, 9)
    with tenant_context(tenant_a.pk):
        latest = StockAdjustment.objects.order_by("-created_at").first()
        assert latest is not None and latest.lines.count() == 1
        assert StockAdjustment.objects.count() == 2
