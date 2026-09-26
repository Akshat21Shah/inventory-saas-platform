"""Catalog API (PLAN §3.5): behaviour, audit, and tenant isolation for every route."""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.audit.models import AuditLog
from apps.catalog import selectors
from apps.catalog.models import Category, Product, ProductTaxRate, Unit
from apps.platform.models import HsnRateHint
from common.dates import today_ist
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def _client(tenant, role="OWNER"):
    user = make_staff_in(tenant, role)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


@pytest.fixture
def a(tenant_a):
    return _client(tenant_a)


@pytest.fixture
def b(tenant_b):
    return _client(tenant_b)


def _unit(tenant, code="PCS"):
    with tenant_context(tenant.pk):
        return Unit.objects.get(code=code)


def _create(client, tenant, **overrides):
    body = {
        "code": "PG-100",
        "name": "Parle-G 100g",
        "unit": str(_unit(tenant).pk),
        "hsn_code": "1905",
        "base_price": "9.00",
        "mrp": "10.00",
        "gst_rate": "5",
    }
    body.update(overrides)
    return client.post(f"{API}/products/", body, format="json")


def _fields(response):
    assert response.status_code == 400, response.json()
    return response.json()["error"]["details"]["fields"]


# --- Categories ---------------------------------------------------------------------------------


@covers("catalog-categories", "catalog-category-tree", "catalog-category-detail")
def test_categories_three_levels_tree_moves_and_isolation(a, b):
    food = a.post(f"{API}/categories/", {"name": "Food"}, format="json").json()
    snacks = a.post(
        f"{API}/categories/", {"name": "Snacks", "parent_id": food["id"]}, format="json"
    ).json()
    chips = a.post(
        f"{API}/categories/", {"name": "Chips", "parent_id": snacks["id"]}, format="json"
    ).json()
    assert (food["level"], snacks["level"], chips["level"]) == (1, 2, 3)
    too_deep = a.post(f"{API}/categories/", {"name": "X", "parent_id": chips["id"]}, format="json")
    assert too_deep.json()["error"]["code"] == "CATEGORY_TOO_DEEP"
    dup = a.post(f"{API}/categories/", {"name": "snacks", "parent_id": food["id"]}, format="json")
    assert "name" in _fields(dup)

    tree = a.get(f"{API}/categories/tree/").json()
    assert tree[0]["name"] == "Food" and tree[0]["children"][0]["children"][0]["name"] == "Chips"

    # Moving "Snacks" (with a child) under a level-2 category would make Chips level 4.
    drinks = a.post(f"{API}/categories/", {"name": "Drinks"}, format="json").json()
    juice = a.post(
        f"{API}/categories/", {"name": "Juice", "parent_id": drinks["id"]}, format="json"
    ).json()
    moved = a.patch(f"{API}/categories/{snacks['id']}/", {"parent_id": juice["id"]}, format="json")
    assert moved.json()["error"]["code"] == "CATEGORY_TOO_DEEP"
    to_top = a.patch(f"{API}/categories/{snacks['id']}/", {"parent_id": None}, format="json")
    assert to_top.json()["level"] == 1
    assert a.get(f"{API}/categories/{chips['id']}/").json()["level"] == 2
    self_loop = a.patch(
        f"{API}/categories/{snacks['id']}/", {"parent_id": chips["id"]}, format="json"
    )
    assert "parent" in _fields(self_loop)

    assert a.delete(f"{API}/categories/{snacks['id']}/").json()["error"]["code"] == "IN_USE"
    assert a.delete(f"{API}/categories/{chips['id']}/").status_code == 204

    # Tenant B sees nothing of A's and cannot touch it.
    assert b.get(f"{API}/categories/").json()["results"] == []
    assert b.get(f"{API}/categories/tree/").json() == []
    assert b.get(f"{API}/categories/{food['id']}/").status_code == 404
    rename = b.patch(f"{API}/categories/{food['id']}/", {"name": "Z"}, format="json")
    assert rename.status_code == 404
    assert b.delete(f"{API}/categories/{food['id']}/").status_code == 404
    parent_from_a = b.post(
        f"{API}/categories/", {"name": "Mine", "parent_id": food["id"]}, format="json"
    )
    assert "parent" in _fields(parent_from_a)


# --- Brands and units ---------------------------------------------------------------------------


@covers("catalog-brands", "catalog-brand-detail", "catalog-units", "catalog-unit-detail")
def test_brands_and_units_with_isolation(a, b, tenant_a):
    brand = a.post(f"{API}/brands/", {"name": "Parle"}, format="json").json()
    assert "name" in _fields(a.post(f"{API}/brands/", {"name": "PARLE"}, format="json"))
    assert a.get(f"{API}/brands/", {"search": "par"}).json()["results"][0]["id"] == brand["id"]
    renamed = a.patch(f"{API}/brands/{brand['id']}/", {"name": "Parle Agro"}, format="json")
    assert renamed.json()["name"] == "Parle Agro"

    unit = a.post(
        f"{API}/units/", {"code": "trays", "name": "Tray", "uqc": "oth"}, format="json"
    ).json()
    assert (unit["code"], unit["uqc"]) == ("TRAYS", "OTH")
    codes = {u["code"] for u in a.get(f"{API}/units/", {"page_size": 100}).json()["results"]}
    assert {"PCS", "KG", "TRAYS"} <= codes

    _create(a, tenant_a, brand=brand["id"])
    assert a.delete(f"{API}/brands/{brand['id']}/").json()["error"]["code"] == "IN_USE"
    pcs = str(_unit(tenant_a).pk)
    assert a.delete(f"{API}/units/{pcs}/").json()["error"]["code"] == "IN_USE"
    assert a.delete(f"{API}/units/{unit['id']}/").status_code == 204

    assert b.get(f"{API}/brands/").json()["results"] == []
    assert b.patch(f"{API}/brands/{brand['id']}/", {"name": "X"}, format="json").status_code == 404
    assert b.delete(f"{API}/brands/{brand['id']}/").status_code == 404
    assert "TRAYS" not in {u["code"] for u in b.get(f"{API}/units/").json()["results"]}
    assert b.patch(f"{API}/units/{pcs}/", {"name": "X"}, format="json").status_code == 404
    assert b.delete(f"{API}/units/{pcs}/").status_code == 404


# --- Products -----------------------------------------------------------------------------------


@covers("catalog-products", "catalog-product-detail")
def test_product_create_starts_with_todays_rate_and_is_audited(a, tenant_a):
    response = _create(a, tenant_a, barcodes=["8901719101038"], tags=[" Glucose ", "glucose"])
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["current_rate"]["gst_rate"] == "5.000"
    assert body["current_rate"]["effective_from"] == today_ist().isoformat()
    assert body["current_rate"]["state"] == "CURRENT"
    assert [b["barcode"] for b in body["barcodes"]] == ["8901719101038"]
    assert body["tags"] == ["glucose"]
    assert body["show_in_shop"] is True and body["warnings"] == []
    assert AuditLog.objects.filter(action="catalog.product_created").exists()
    with tenant_context(tenant_a.pk):
        assert selectors.is_sellable(Product.objects.get().pk)


def test_product_validation_messages(a, tenant_a):
    fields = _fields(
        _create(
            a,
            tenant_a,
            hsn_code="19A",
            gst_rate="12",
            min_order_qty="1.5",
            base_price="-1",
            pack_size="12",
        )
    )
    assert "HSN code of 4 to 8 digits" in fields["hsn_code"][0]  # tax.hsn_min_digits = 4
    assert "GST rates in use" in fields["gst_rate"][0]  # 12% is no longer active
    assert "whole numbers" in fields["min_order_qty"][0]
    assert "base_price" in fields and "pack_size" in fields
    assert _create(a, tenant_a).status_code == 201
    assert "code" in _fields(_create(a, tenant_a, code="pg-100"))


def test_price_above_mrp_and_hsn_hint_are_warnings_not_errors(a, tenant_a):
    HsnRateHint.objects.create(
        hsn_prefix="1905", gst_rate=Decimal("18"), effective_from="2025-09-22"
    )
    response = _create(a, tenant_a, base_price="10.00", mrp="10.00", gst_rate="5")
    assert response.status_code == 201
    codes = {w["code"]: w for w in response.json()["warnings"]}
    assert codes["PRICE_ABOVE_MRP"]["details"] == {"price_with_gst": "10.50", "mrp": "10.00"}
    assert codes["HSN_RATE_DIFFERS"]["details"]["suggested_rate"] == "18.000"
    hint = a.get(f"{API}/products/hsn-hint/", {"hsn": "19059020"}).json()["hint"]
    assert hint["gst_rate"] == "18.000"


@covers("catalog-hsn-hint")
def test_hsn_hint_is_platform_reference_data(b):
    HsnRateHint.objects.create(hsn_prefix="30", gst_rate=Decimal("5"), effective_from="2025-09-22")
    assert b.get(f"{API}/products/hsn-hint/", {"hsn": "3004"}).json()["hint"]["hsn_prefix"] == "30"
    assert b.get(f"{API}/products/hsn-hint/", {"hsn": "9999"}).json() == {"hint": None}


@covers("catalog-tax-options")
def test_tax_options_are_the_platform_rates_in_use(a, b):
    options = a.get(f"{API}/products/tax-options/").json()
    rates = [r["rate"] for r in options["gst_rates"]]
    assert "18.000" in rates and "12.000" not in rates  # 12% is no longer in use
    assert options == b.get(f"{API}/products/tax-options/").json()  # the same for every tenant


def test_price_changes_are_audited_separately(a, tenant_a):
    product = _create(a, tenant_a).json()
    response = a.patch(
        f"{API}/products/{product['id']}/",
        {"base_price": "9.50", "name": "Parle G"},
        format="json",
    )
    assert response.status_code == 200
    change = AuditLog.objects.get(action="catalog.product_price_changed")
    assert change.changes == {"base_price": ["9.00", "9.50"]}


def test_list_filters_include_sub_categories_and_search(a, tenant_a):
    food = a.post(f"{API}/categories/", {"name": "Food"}, format="json").json()
    biscuits = a.post(
        f"{API}/categories/", {"name": "Biscuits", "parent_id": food["id"]}, format="json"
    ).json()
    _create(a, tenant_a, category=biscuits["id"])
    _create(a, tenant_a, code="MG-1", name="Maggi Noodles", show_in_shop=False)
    listing = a.get(f"{API}/products/", {"category": food["id"]}).json()["results"]
    assert [p["code"] for p in listing] == ["PG-100"]
    assert listing[0]["gst_rate"] == "5.000"
    assert [p["code"] for p in a.get(f"{API}/products/", {"search": "magi"}).json()["results"]] == [
        "MG-1"
    ]  # a typo still finds it (trigram)
    assert [
        p["code"] for p in a.get(f"{API}/products/", {"show_in_shop": "false"}).json()["results"]
    ] == ["MG-1"]


@covers("catalog-product-lookup", "catalog-product-barcodes", "catalog-product-barcode-detail")
def test_lookup_barcodes_and_soft_delete(a, b, tenant_a):
    product = _create(a, tenant_a, barcodes=["111"]).json()
    added = a.post(f"{API}/products/{product['id']}/barcodes/", {"barcode": "222"}, format="json")
    assert added.status_code == 201
    other = _create(a, tenant_a, code="X-1").json()
    dup = a.post(f"{API}/products/{other['id']}/barcodes/", {"barcode": "222"}, format="json")
    assert "barcode" in _fields(dup)
    assert a.get(f"{API}/products/lookup/", {"barcode": "222"}).json()["id"] == product["id"]
    assert a.get(f"{API}/products/lookup/", {"code": "pg-100"}).json()["id"] == product["id"]
    removed = a.delete(f"{API}/products/{product['id']}/barcodes/{added.json()['id']}/")
    assert removed.status_code == 204

    assert b.get(f"{API}/products/lookup/", {"barcode": "111"}).status_code == 404
    assert (
        b.post(
            f"{API}/products/{product['id']}/barcodes/", {"barcode": "9"}, format="json"
        ).status_code
        == 404
    )
    barcode_id = a.get(f"{API}/products/{product['id']}/").json()["barcodes"][0]["id"]
    assert b.delete(f"{API}/products/{product['id']}/barcodes/{barcode_id}/").status_code == 404

    assert a.delete(f"{API}/products/{product['id']}/").status_code == 204
    assert a.get(f"{API}/products/{product['id']}/").status_code == 404
    # The deleted product's barcode is free again; its code is not.
    assert _create(a, tenant_a, code="NEW-1", barcodes=["111"]).status_code == 201
    assert "code" in _fields(_create(a, tenant_a, code="PG-100"))


def test_products_are_isolated(a, b, tenant_a):
    product = _create(a, tenant_a).json()
    assert b.get(f"{API}/products/").json()["results"] == []
    assert b.get(f"{API}/products/{product['id']}/").status_code == 404
    edit = b.patch(f"{API}/products/{product['id']}/", {"name": "X"}, format="json")
    assert edit.status_code == 404
    assert b.delete(f"{API}/products/{product['id']}/").status_code == 404
    # B cannot point its product at A's unit either.
    assert "unit" in _fields(_create(b, tenant_a, code="B-1"))


@covers("catalog-products-bulk")
def test_bulk_actions_only_touch_own_products(a, b, tenant_a, tenant_b):
    ids = [_create(a, tenant_a, code=f"A-{i}").json()["id"] for i in range(3)]
    response = a.post(
        f"{API}/products/bulk/", {"product_ids": ids, "action": "hide_from_shop"}, format="json"
    )
    assert response.json() == {"changed": 3}
    b_id = _create(b, tenant_b, code="B-1").json()["id"]
    cross = b.post(
        f"{API}/products/bulk/",
        {"product_ids": [*ids, b_id], "action": "deactivate"},
        format="json",
    )
    assert cross.json() == {"changed": 1}
    with tenant_context(tenant_a.pk):
        assert Product.objects.filter(is_active=True).count() == 3


# --- GST rate changes ---------------------------------------------------------------------------


@covers("catalog-product-tax-rates", "catalog-product-tax-rate-cancel")
def test_schedule_and_cancel_rate_changes(a, b, tenant_a):
    product = _create(a, tenant_a).json()
    url = f"{API}/products/{product['id']}/tax-rates/"
    day = today_ist() + timedelta(days=10)
    scheduled = a.post(url, {"gst_rate": "18", "effective_from": day.isoformat()}, format="json")
    assert scheduled.status_code == 201
    rows = {r["state"]: r for r in a.get(url).json()}
    assert rows["SCHEDULED"]["gst_rate"] == "18.000" and rows["CURRENT"]["gst_rate"] == "5.000"
    same_day = a.post(url, {"gst_rate": "40", "effective_from": day.isoformat()}, format="json")
    assert "effective_from" in _fields(same_day)
    past = a.post(
        url,
        {"gst_rate": "18", "effective_from": (today_ist() - timedelta(days=1)).isoformat()},
        format="json",
    )
    assert "in the past" in _fields(past)["effective_from"][0]

    cancel = f"{url}{rows['SCHEDULED']['id']}/cancel/"
    assert b.post(cancel, {"reason": "x"}, format="json").status_code == 404
    assert b.get(url).status_code == 404
    foreign = b.post(url, {"gst_rate": "18", "effective_from": day.isoformat()}, format="json")
    assert foreign.status_code == 404
    assert "reason" in _fields(a.post(cancel, {"reason": " "}, format="json"))
    assert a.post(cancel, {"reason": "Wrong date"}, format="json").status_code == 200
    states = sorted(r["state"] for r in a.get(url).json())
    assert states == ["CANCELLED", "CURRENT"]
    current = f"{url}{rows['CURRENT']['id']}/cancel/"
    assert a.post(current, {"reason": "x"}, format="json").json()["error"]["code"] == (
        "TAX_RATE_NOT_CANCELLABLE"
    )
    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {"catalog.tax_rate_scheduled", "catalog.tax_rate_cancelled"} <= actions


def test_rate_on_any_day_around_a_change(a, tenant_a):
    product_id = UUID(_create(a, tenant_a).json()["id"])
    change = today_ist() + timedelta(days=3)
    a.post(
        f"{API}/products/{product_id}/tax-rates/",
        {"gst_rate": "18", "effective_from": change.isoformat()},
        format="json",
    )
    with tenant_context(tenant_a.pk):

        def rate(day):
            row = selectors.tax_rate_on(product_id, day)
            assert row is not None
            return row.gst_rate

        assert rate(change - timedelta(days=1)) == Decimal("5")
        assert rate(change) == Decimal("18")
        assert rate(change + timedelta(days=30)) == Decimal("18")
        assert selectors.tax_rate_on(product_id, today_ist() - timedelta(days=1)) is None
        assert selectors.tax_rates_on([product_id], change)[product_id].gst_rate == Decimal("18")


@covers("catalog-tax-rate-schedule")
def test_bulk_schedule_preview_then_commit(a, b, tenant_a, tenant_b):
    for i, hsn in enumerate(["1905", "190590", "2106"]):
        _create(a, tenant_a, code=f"P-{i}", hsn_code=hsn)
    _create(b, tenant_b, code="B-1", hsn_code="1905")
    day = (today_ist() + timedelta(days=7)).isoformat()
    body = {"hsn_prefix": "1905", "gst_rate": "18", "effective_from": day}
    preview = a.post(f"{API}/products/tax-rates/schedule/", body, format="json").json()
    assert (preview["count"], preview["committed"]) == (2, False)
    stale = a.post(
        f"{API}/products/tax-rates/schedule/",
        {**body, "preview": False, "expected_count": 3},
        format="json",
    )
    assert stale.json()["error"]["code"] == "PREVIEW_OUT_OF_DATE"
    done = a.post(
        f"{API}/products/tax-rates/schedule/",
        {**body, "preview": False, "expected_count": 2},
        format="json",
    ).json()
    assert done == {"count": 2, "committed": True}
    again = a.post(f"{API}/products/tax-rates/schedule/", body, format="json").json()
    assert (again["count"], again["skipped"]) == (0, 2)
    # Tenant B's matching product was never touched.
    with tenant_context(tenant_b.pk):
        assert ProductTaxRate.objects.count() == 1
    no_filter = a.post(
        f"{API}/products/tax-rates/schedule/",
        {"gst_rate": "18", "effective_from": day},
        format="json",
    )
    assert "filter" in _fields(no_filter)


def test_category_filter_covers_descendants(tenant_a):
    with tenant_context(tenant_a.pk):
        top = Category.objects.create(name="A", slug="a")
        mid = Category.objects.create(name="B", slug="b", parent=top, level=2)
        low = Category.objects.create(name="C", slug="c", parent=mid, level=3)
        assert selectors.descendant_ids(top.pk) == {top.pk, mid.pk, low.pk}


def test_service_accepts_model_defaults_for_quantities(tenant_a):
    """Imports and the seed call the service without every field; defaults must validate."""
    from apps.accounts.models import User
    from apps.catalog import services

    owner = User.objects.create_user(
        "svc@example.com", "a-strong-password", user_type=User.UserType.STAFF
    )
    with tenant_context(tenant_a.pk):
        product, _ = services.create_product(
            {
                "code": "SVC-1",
                "name": "Service default",
                "unit_id": _unit(tenant_a).pk,
                "hsn_code": "3401",
                "base_price": Decimal("5"),
            },
            gst_rate=Decimal("18"),
            by=owner,
        )
        assert product.min_order_qty == Decimal("1")
