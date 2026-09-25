"""Price lists, special prices and discount rules (spec 5.6, PLAN §3.6): validation, audit, and
tenant isolation for every route."""

from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.audit.models import AuditLog
from apps.catalog.models import Brand, Category, Product, ProductTaxRate, Unit
from apps.retailers.services import create_retailer
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
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {issue_tokens(make_staff_in(tenant, role), tenant.pk).access}"
    )
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


def product(tenant, code="P-1", price="10.00"):
    with tenant_context(tenant.pk):
        row = Product.objects.create(
            code=code,
            name=f"Product {code}",
            unit=Unit.objects.get(code="PCS"),
            hsn_code="1905",
            base_price=Decimal(price),
        )
        ProductTaxRate.objects.create(
            product=row, gst_rate=Decimal("5"), effective_from=today_ist()
        )
        return row


def shop(tenant, phone="9876500001"):
    with tenant_context(tenant.pk):
        return create_retailer(shop_name="Ganesh Kirana", phone=phone, send_welcome=False)


def _fields(response):
    assert response.status_code == 400, response.json()
    return response.json()["error"]["details"]["fields"]


@covers("price-lists", "price-list-detail")
def test_price_lists_and_deleting_one_in_use(tenant_a, tenant_b):
    a, b = _client(tenant_a), _client(tenant_b)
    gold = a.post(f"{API}/price-lists/", {"name": "Gold"}, format="json").json()
    assert "name" in _fields(a.post(f"{API}/price-lists/", {"name": "gold"}, format="json"))
    renamed = a.patch(
        f"{API}/price-lists/{gold['id']}/", {"name": "Gold retailers"}, format="json"
    ).json()
    assert renamed["name"] == "Gold retailers"
    retailer = shop(tenant_a)
    a.patch(f"{API}/retailers/{retailer.pk}/", {"price_list": gold["id"]}, format="json")
    assert a.get(f"{API}/price-lists/{gold['id']}/").json()["shop_count"] == 1
    in_use = a.delete(f"{API}/price-lists/{gold['id']}/")
    assert in_use.json()["error"]["code"] == "IN_USE"
    a.patch(f"{API}/retailers/{retailer.pk}/", {"price_list": None}, format="json")
    assert a.delete(f"{API}/price-lists/{gold['id']}/").status_code == 204

    silver = a.post(f"{API}/price-lists/", {"name": "Silver"}, format="json").json()
    assert b.get(f"{API}/price-lists/").json()["results"] == []
    assert b.get(f"{API}/price-lists/{silver['id']}/").status_code == 404
    assert (
        b.patch(f"{API}/price-lists/{silver['id']}/", {"name": "X"}, format="json").status_code
        == 404
    )
    assert b.delete(f"{API}/price-lists/{silver['id']}/").status_code == 404
    other_shop = shop(tenant_b)
    wrong = b.patch(
        f"{API}/retailers/{other_shop.pk}/", {"price_list": silver["id"]}, format="json"
    )
    assert "price_list" in _fields(wrong)


@covers("price-list-items", "price-list-item-detail")
def test_bulk_prices_are_audited_as_one_change_with_old_and_new(tenant_a, tenant_b):
    a, b = _client(tenant_a), _client(tenant_b)
    p1, p2 = product(tenant_a, "P-1"), product(tenant_a, "P-2")
    foreign = product(tenant_b, "B-1")
    gold = a.post(f"{API}/price-lists/", {"name": "Gold"}, format="json").json()
    url = f"{API}/price-lists/{gold['id']}/items/"
    first = a.put(
        url,
        {
            "items": [
                {"product": str(p1.pk), "price": "9.50"},
                {"product": str(p2.pk), "price": "19.00"},
            ]
        },
        format="json",
    )
    assert first.json() == {"changed": 2}
    again = a.put(
        url,
        {
            "items": [
                {"product": str(p1.pk), "price": "9.00"},
                {"product": str(p2.pk), "price": "19.00"},
            ]
        },
        format="json",
    )
    assert again.json() == {"changed": 1}
    last = (
        AuditLog.objects.filter(action="pricing.price_list_prices_changed")
        .order_by("created_at")
        .last()
    )
    assert last is not None
    assert last.changes == {"P-1": ["9.50", "9.00"]}

    rows = a.get(url, {"search": "p-2"}).json()["results"]
    assert [(r["product"]["code"], r["price"], r["base_price"]) for r in rows] == [
        ("P-2", "19.00", "10.00")
    ]
    errors = _fields(
        a.put(
            url,
            {
                "items": [
                    {"product": str(foreign.pk), "price": "1"},
                    {"product": str(p1.pk), "price": "-1"},
                    {"product": str(p1.pk), "price": "2"},
                ]
            },
            format="json",
        )
    )
    assert errors["items.0.product"] == ["Choose an existing product."]
    assert errors["items.1.price"] == ["Enter 0 or more."]
    assert errors["items.2.product"] == ["This product is listed twice."]

    assert b.get(url).status_code == 404
    assert b.put(url, {"items": []}, format="json").status_code == 404
    assert b.delete(f"{url}{p1.pk}/").status_code == 404
    assert a.delete(f"{url}{p1.pk}/").status_code == 204
    assert [r["product"]["code"] for r in a.get(url).json()["results"]] == ["P-2"]


@covers("retailer-prices", "retailer-price-detail")
def test_special_prices(tenant_a, tenant_b):
    a, b = _client(tenant_a), _client(tenant_b)
    p1, retailer = product(tenant_a), shop(tenant_a)
    created = a.post(
        f"{API}/retailer-prices/",
        {"retailer": str(retailer.pk), "product": str(p1.pk), "price": "8.75", "note": "Deal"},
        format="json",
    )
    assert created.status_code == 201
    row = created.json()
    duplicate = a.post(
        f"{API}/retailer-prices/",
        {"retailer": str(retailer.pk), "product": str(p1.pk), "price": "8"},
        format="json",
    )
    assert "product" in _fields(duplicate)
    updated = a.patch(f"{API}/retailer-prices/{row['id']}/", {"price": "8.50"}, format="json")
    assert updated.json()["price"] == "8.50"
    assert AuditLog.objects.filter(action="pricing.retailer_price_changed").count() == 2
    assert a.get(f"{API}/retailer-prices/", {"retailer": str(retailer.pk)}).json()["results"]

    assert b.get(f"{API}/retailer-prices/").json()["results"] == []
    assert (
        b.patch(f"{API}/retailer-prices/{row['id']}/", {"price": "1"}, format="json").status_code
        == 404
    )
    assert b.delete(f"{API}/retailer-prices/{row['id']}/").status_code == 404
    cross = b.post(
        f"{API}/retailer-prices/",
        {"retailer": str(retailer.pk), "product": str(p1.pk), "price": "1"},
        format="json",
    )
    assert set(_fields(cross)) == {"retailer", "product"}
    assert a.delete(f"{API}/retailer-prices/{row['id']}/").status_code == 204


@covers("discount-rules", "discount-rule-detail")
def test_discount_rules_validation_slabs_and_isolation(tenant_a, tenant_b):
    a, b = _client(tenant_a), _client(tenant_b)
    with tenant_context(tenant_a.pk):
        category = Category.objects.create(name="Food", slug="food")
        Brand.objects.create(name="Parle")
    base = {
        "name": "Diwali",
        "discount_type": "PERCENT",
        "value": "5",
        "scope_type": "ALL",
        "audience_type": "ALL",
    }
    assert "value" in _fields(
        a.post(f"{API}/discount-rules/", {**base, "value": "120"}, format="json")
    )
    assert "value" in _fields(
        a.post(
            f"{API}/discount-rules/",
            {**base, "discount_type": "FLAT_PER_UNIT", "value": "0"},
            format="json",
        )
    )
    assert _fields(
        a.post(f"{API}/discount-rules/", {**base, "scope_type": "PRODUCT"}, format="json")
    )["product"] == ["Choose the product."]
    assert _fields(
        a.post(f"{API}/discount-rules/", {**base, "audience_type": "RETAILER"}, format="json")
    )["retailer"] == ["Choose the shop."]
    assert "valid_to" in _fields(
        a.post(
            f"{API}/discount-rules/",
            {**base, "valid_from": "2026-10-10", "valid_to": "2026-10-01"},
            format="json",
        )
    )
    assert "slabs" in _fields(
        a.post(
            f"{API}/discount-rules/",
            {**base, "slabs": [{"min_qty": "10", "value": "2"}, {"min_qty": "10", "value": "3"}]},
            format="json",
        )
    )

    rule = a.post(
        f"{API}/discount-rules/",
        {
            **base,
            "name": "Bulk biscuits",
            "scope_type": "CATEGORY",
            "category": str(category.pk),
            "slabs": [{"min_qty": "24", "value": "5"}, {"min_qty": "12", "value": "2.5"}],
        },
        format="json",
    )
    assert rule.status_code == 201, rule.json()
    body = rule.json()
    assert [(s["min_qty"], s["value"]) for s in body["slabs"]] == [
        ("12.000", "2.50"),
        ("24.000", "5.00"),
    ]
    assert body["category"]["name"] == "Food" and body["value"] == "0.00"
    changed = a.patch(f"{API}/discount-rules/{body['id']}/", {"is_active": False}, format="json")
    assert changed.json()["is_active"] is False and len(changed.json()["slabs"]) == 2
    no_slabs = a.patch(
        f"{API}/discount-rules/{body['id']}/", {"slabs": [], "value": "3"}, format="json"
    ).json()
    assert (no_slabs["slabs"], no_slabs["value"]) == ([], "3.00")

    foreign_product = product(tenant_b, "B-1")
    cross = a.post(
        f"{API}/discount-rules/",
        {**base, "scope_type": "PRODUCT", "product": str(foreign_product.pk)},
        format="json",
    )
    assert _fields(cross)["product"] == ["Choose an existing product."]
    assert b.get(f"{API}/discount-rules/").json()["results"] == []
    assert b.get(f"{API}/discount-rules/{body['id']}/").status_code == 404
    assert (
        b.patch(f"{API}/discount-rules/{body['id']}/", {"name": "X"}, format="json").status_code
        == 404
    )
    assert b.delete(f"{API}/discount-rules/{body['id']}/").status_code == 404
    assert a.delete(f"{API}/discount-rules/{body['id']}/").status_code == 204
    assert {
        "pricing.discount_rule_created",
        "pricing.discount_rule_updated",
        "pricing.discount_rule_deleted",
    } <= set(AuditLog.objects.values_list("action", flat=True))


def test_price_lists_are_assigned_in_bulk_and_by_import(tenant_a):
    a = _client(tenant_a)
    gold = a.post(f"{API}/price-lists/", {"name": "Gold"}, format="json").json()
    shops = [shop(tenant_a, f"98765000{n:02d}") for n in (1, 2)]
    bulk = a.post(
        f"{API}/retailers/bulk/",
        {
            "retailer_ids": [str(s.pk) for s in shops],
            "action": "assign_price_list",
            "value": gold["id"],
        },
        format="json",
    )
    assert bulk.json() == {"changed": 2}
    assert (
        a.get(f"{API}/retailers/", {"price_list": gold["id"]}).json()["results"][0]["price_list"][
            "name"
        ]
        == "Gold"
    )
