"""What shops see of stock (PLAN §5.3, ADR-041 item 12): labels, the exact quantity only when the
distributor allows it, and hidden out-of-stock products when chosen."""

from decimal import Decimal as D
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.db import transaction
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.tokens import issue_tokens
from apps.catalog.models import Category
from apps.inventory import services
from apps.inventory.availability import Label, ShopStockRules, availability
from apps.inventory.tests.helpers import make_product
from apps.platform.services import set_tenant_settings
from apps.retailers.services import create_retailer
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
API = "/api/v1/shop"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.parametrize(
    ("available", "reorder", "rules", "expected"),
    [
        ("20", "5", {}, (Label.IN_STOCK, None)),
        ("5", "5", {}, (Label.LOW_STOCK, None)),
        ("5", "5", {"show_low_stock_label": False}, (Label.IN_STOCK, None)),
        ("3", "0", {}, (Label.IN_STOCK, None)),
        ("0", "5", {}, (Label.BACKORDER, None)),
        ("0", "5", {"backorders_enabled": False}, (Label.OUT_OF_STOCK, None)),
        ("7", "5", {"show_exact_quantity": True}, (Label.IN_STOCK, D("7"))),
        ("0", "5", {"show_exact_quantity": True}, (Label.BACKORDER, D("0"))),
    ],
)
def test_labels(available, reorder, rules, expected):
    found = availability(D(available), D(reorder), ShopStockRules(**rules))
    assert (found.status, found.quantity) == expected


def _stock(tenant, product, qty):
    with tenant_context(tenant.pk), transaction.atomic():
        level = services.lock_levels([product.pk], services.default_warehouse())[product.pk]
        services.add(level, D(qty), services.Ref("ADJUSTMENT", uuid4()), by=None)


def _shop(tenant):
    with tenant_context(tenant.pk):
        retailer = create_retailer(shop_name="Corner", phone="9876500011", send_welcome=False)
    user = User.objects.get(tenant=tenant, phone=retailer.mobile)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


def _settings(tenant, **values):
    with tenant_context(tenant.pk):
        set_tenant_settings(values, user=None)
    cache.clear()


def _seen(client):
    rows = client.get(f"{API}/products/").json()["results"]
    return {row["code"]: row["availability"] for row in rows}


def test_shop_sees_labels_not_stock(tenant_a):
    with tenant_context(tenant_a.pk):
        food = Category.objects.create(name="Food", slug="food")
    plenty = make_product(tenant_a, "PLENTY", reorder_level=D("5"), category=food)
    low = make_product(tenant_a, "LOW", reorder_level=D("5"), category=food)
    make_product(tenant_a, "NONE", category=food)
    _stock(tenant_a, plenty, "50")
    _stock(tenant_a, low, "3")
    client = _shop(tenant_a)
    assert _seen(client) == {
        "PLENTY": {"status": "IN_STOCK", "quantity": None},
        "LOW": {"status": "LOW_STOCK", "quantity": None},
        "NONE": {"status": "BACKORDER", "quantity": None},  # backorders are on by default
    }
    detail = client.get(f"{API}/products/{low.pk}/").json()
    assert detail["availability"] == {"status": "LOW_STOCK", "quantity": None}

    _settings(tenant_a, **{"stock.show_exact_quantity": True, "backorders.enabled": False})
    seen = _seen(client)
    assert seen["PLENTY"] == {"status": "IN_STOCK", "quantity": "50.000"}
    assert seen["NONE"] == {"status": "OUT_OF_STOCK", "quantity": "0.000"}

    _settings(tenant_a, **{"stock.show_out_of_stock_in_shop": False})
    assert set(_seen(client)) == {"PLENTY", "LOW"}
    assert client.get(f"{API}/products/{make_product(tenant_a, 'NEW').pk}/").status_code == 404
    tree = client.get(f"{API}/categories/").json()
    assert tree[0]["product_count"] == 2  # counts follow what the shop can see

    _settings(tenant_a, **{"backorders.enabled": True})  # the hide setting needs backorders off
    assert set(_seen(client)) == {"PLENTY", "LOW", "NONE", "NEW"}


def test_reserved_stock_is_not_available_to_shops(tenant_a):
    product = make_product(tenant_a, "RES")
    _stock(tenant_a, product, "2")
    with tenant_context(tenant_a.pk), transaction.atomic():
        level = services.lock_levels([product.pk], services.default_warehouse())[product.pk]
        services.reserve(level, D("2"), services.Ref("ORDER", uuid4()), by=None)
    assert _seen(_shop(tenant_a))["RES"]["status"] == "BACKORDER"
