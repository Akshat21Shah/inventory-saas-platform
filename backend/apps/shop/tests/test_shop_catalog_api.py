"""Shop catalog (PLAN §3.9, task 2.13; ADR-034 visibility, ADR-036 prices): what a shop sees, at
its own prices, only from its own distributor."""

from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.catalog.models import Brand, Category, Product, ProductImage, ProductTaxRate, Unit
from apps.platform.models import TenantSetting
from apps.pricing.models import DiscountRule, DiscountSlab, PriceList, PriceListItem, RetailerPrice
from apps.retailers.services import block_retailer, create_retailer
from common.dates import today_ist
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1/shop"
TODAY = today_ist()


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def _client(tenant, user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


def _shop(tenant, phone, **extra):
    with tenant_context(tenant.pk):
        retailer = create_retailer(
            shop_name=f"Shop {phone[-2:]}", phone=phone, send_welcome=False, extra=extra
        )
    user = User.objects.get(tenant=tenant, phone=retailer.mobile)
    return retailer, _client(tenant, user)


def _product(code, *, base="10.00", rate_from=None, **fields: Any) -> Product:
    product: Product = Product.objects.create(
        code=code,
        name=fields.pop("name", f"Item {code}"),
        unit=Unit.objects.get(code="PCS"),
        hsn_code="2106",
        base_price=D(base),
        **fields,
    )
    ProductTaxRate.objects.create(
        product=product, gst_rate=D("18"), effective_from=rate_from or TODAY - timedelta(days=10)
    )
    return product


@pytest.fixture
def catalog(tenant_a, tenant_b):
    with tenant_context(tenant_a.pk):
        food = Category.objects.create(name="Food", slug="food")
        snacks = Category.objects.create(name="Snacks", slug="snacks", parent=food, level=2)
        chips = Category.objects.create(name="Chips", slug="chips", parent=snacks, level=3)
        drinks = Category.objects.create(name="Drinks", slug="drinks")
        Category.objects.create(name="Empty", slug="empty")
        lays = Brand.objects.create(name="Lays")
        Brand.objects.create(name="Unused")
        chips_item = _product("P1", name="Lays Magic Masala", category=chips, brand=lays)
        ProductImage.objects.create(
            product=chips_item,
            original_key="o",
            status=ProductImage.Status.READY,
            variants={"thumb": {"key": "t/p1.webp"}, "medium": {"key": "m/p1.webp"}},
        )
        ProductImage.objects.create(product=chips_item, original_key="o2")  # still processing
        _product("HID", category=chips, show_in_shop=False)
        _product("OFF", category=chips, is_active=False)
        _product("DEL", category=chips, deleted_at=timezone.now(), is_active=False)
        _product("FUT", category=chips, rate_from=TODAY + timedelta(days=3))
        zero = _product("ZERO", base="0.00", category=drinks)
        free = _product("FREE")
        juice = _product(
            "P8",
            name="Mango Juice",
            base="10.00",
            category=drinks,
            min_order_qty=D("6"),
            order_multiple=D("6"),
            mrp=D("12.00"),
        )
        DiscountRule.objects.create(
            name="Free sample",
            discount_type="PERCENT",
            value=D("100"),
            scope_type="PRODUCT",
            product=free,
            audience_type="ALL",
        )
        bulk = DiscountRule.objects.create(
            name="Juice bulk",
            discount_type="PERCENT",
            value=D("0"),
            scope_type="CATEGORY",
            category=drinks,
            audience_type="ALL",
        )
        DiscountSlab.objects.create(rule=bulk, min_qty=D("24"), value=D("5"))
        DiscountSlab.objects.create(rule=bulk, min_qty=D("48"), value=D("10"))
        DiscountSlab.objects.create(rule=bulk, min_qty=D("3"), value=D("1"))  # below the minimum
        gold = PriceList.objects.create(name="Gold")
        PriceListItem.objects.create(price_list=gold, product=chips_item, price=D("9.00"))
        PriceListItem.objects.create(price_list=gold, product=zero, price=D("5.00"))
    with tenant_context(tenant_b.pk):
        _product("B1")
    return {
        "chips_item": chips_item,
        "juice": juice,
        "gold": gold,
        "food": food,
        "drinks": drinks,
        "lays": lays,
        "zero": zero,
    }


def _codes(response):
    assert response.status_code == 200, response.json()
    return [row["code"] for row in response.json()["results"]]


@covers("shop-products", "shop-product", "shop-categories", "shop-brands")
def test_what_a_shop_sees_and_isolation(tenant_a, tenant_b, catalog):
    _, shop = _shop(tenant_a, "9876500001")
    assert _codes(shop.get(f"{API}/products/")) == ["P1", "P8"]  # by name; hidden ones left out

    row = shop.get(f"{API}/products/").json()["results"][0]
    assert row["price"] == {
        "qty": "1.000",
        "unit_price": "10.00",
        "discount": None,
        "net_unit_price": "10.00",
        "gst_rate": "18.000",
        "prices_include_gst": False,
    }
    assert row["thumbnail_url"].endswith("t/p1.webp")
    assert (row["brand"]["name"], row["category"]["name"], row["unit"]["code"]) == (
        "Lays",
        "Chips",
        "PCS",
    )
    assert "base_price" not in row and "price_source" not in row["price"]

    # Browse and search the other distributor's catalog: nothing of A's leaks.
    _, other = _shop(tenant_b, "9876500009")
    assert _codes(other.get(f"{API}/products/")) == ["B1"]
    assert other.get(f"{API}/products/{catalog['chips_item'].pk}/").status_code == 404
    assert _codes(other.get(f"{API}/products/", {"search": "lays"})) == []
    assert other.get(f"{API}/categories/").json() == []
    assert other.get(f"{API}/brands/").json() == []
    assert _codes(other.get(f"{API}/products/", {"category": str(catalog["food"].pk)})) == []

    # Staff can't use the shop API, and shops can't use the staff API.
    staff = _client(tenant_a, make_staff_in(tenant_a, "OWNER"))
    for path in ("products/", f"products/{catalog['chips_item'].pk}/", "categories/", "brands/"):
        assert staff.get(f"{API}/{path}").status_code == 403
    assert shop.get("/api/v1/products/").status_code == 403


def test_price_lists_and_special_prices(tenant_a, catalog):
    retailer, shop = _shop(tenant_a, "9876500002", price_list_id=catalog["gold"].pk)
    with tenant_context(tenant_a.pk):
        RetailerPrice.objects.create(retailer=retailer, product=catalog["juice"], price=D("8.00"))
    rows = {r["code"]: r["price"] for r in shop.get(f"{API}/products/").json()["results"]}
    # ZERO has no base price but the Gold list gives it one, so this shop sees it.
    assert {code: p["unit_price"] for code, p in rows.items()} == {
        "P1": "9.00",
        "P8": "8.00",
        "ZERO": "5.00",
    }
    assert rows["P8"]["qty"] == "6.000"


def test_filters_search_and_categories(tenant_a, catalog):
    _, shop = _shop(tenant_a, "9876500003")
    assert _codes(shop.get(f"{API}/products/", {"category": str(catalog["food"].pk)})) == ["P1"]
    assert _codes(shop.get(f"{API}/products/", {"brand": str(catalog["lays"].pk)})) == ["P1"]
    found = shop.get(f"{API}/products/", {"search": "juice"}).json()
    assert ([r["code"] for r in found["results"]], found["next"]) == (["P8"], None)
    assert _codes(shop.get(f"{API}/products/", {"search": "HID"})) == []
    assert shop.get(f"{API}/products/", {"brand": "nope"}).status_code == 400

    tree = shop.get(f"{API}/categories/").json()
    simple = [(n["name"], n["product_count"], [c["name"] for c in n["children"]]) for n in tree]
    assert simple == [("Drinks", 1, []), ("Food", 1, ["Snacks"])]  # "Empty" is left out
    assert tree[1]["children"][0]["children"][0]["name"] == "Chips"
    assert [b["name"] for b in shop.get(f"{API}/brands/").json()] == ["Lays"]
    drinks_brands = shop.get(f"{API}/brands/", {"category": str(catalog["drinks"].pk)}).json()
    assert drinks_brands == []


def test_detail_with_images_and_slab_hints(tenant_a, catalog):
    _, shop = _shop(tenant_a, "9876500004")
    juice = shop.get(f"{API}/products/{catalog['juice'].pk}/").json()
    assert (juice["min_order_qty"], juice["order_multiple"], juice["mrp"]) == (
        "6.000",
        "6.000",
        "12.00",
    )
    assert juice["price"]["discount"]["value"] == "1.00"  # the 3+ slab applies at 6
    assert juice["price"]["net_unit_price"] == "9.90"
    assert juice["slab_hints"] == [
        {"min_qty": "24.000", "net_unit_price": "9.50"},
        {"min_qty": "48.000", "net_unit_price": "9.00"},
    ]
    chips = shop.get(f"{API}/products/{catalog['chips_item'].pk}/").json()
    assert [i["urls"]["medium"].endswith("m/p1.webp") for i in chips["images"]] == [True]
    assert chips["slab_hints"] == []
    with tenant_context(tenant_a.pk):
        hidden = Product.objects.filter(code__in=["HID", "OFF", "DEL", "FUT", "FREE", "ZERO"])
        ids = list(hidden.values_list("pk", flat=True))
    for product_id in ids:
        assert shop.get(f"{API}/products/{product_id}/").status_code == 404


@pytest.mark.parametrize("allowed", [True, False])
def test_shops_on_hold(tenant_a, catalog, allowed):
    with tenant_context(tenant_a.pk):
        TenantSetting.objects.update_or_create(
            key="retailers.blocked_can_sign_in", defaults={"value": allowed}
        )
    cache.clear()
    retailer, shop = _shop(tenant_a, "9876500005")
    with tenant_context(tenant_a.pk):
        block_retailer(retailer.pk, reason="Overdue", by=make_staff_in(tenant_a, "OWNER"))
    response = shop.get(f"{API}/products/")
    if allowed:
        assert _codes(response) == ["P1", "P8"]
    else:
        assert response.json()["error"]["code"] == "RETAILER_ON_HOLD"


def test_a_page_costs_a_fixed_number_of_queries(tenant_a, catalog):
    _, shop = _shop(tenant_a, "9876500006")

    def queries() -> int:
        with CaptureQueriesContext(connection) as ctx:
            assert shop.get(f"{API}/products/").status_code == 200
        return sum(1 for q in ctx.captured_queries if "SAVEPOINT" not in q["sql"])

    queries()  # warm the settings and branding caches
    few = queries()
    with tenant_context(tenant_a.pk):
        for n in range(20):
            _product(f"X{n:02d}", category=catalog["drinks"], brand=catalog["lays"])
    assert queries() == few
