"""``resolve_price`` (spec 5.6, PLAN M1-M6, ADR-036): every price source, discount type, scope,
audience, validity window, slab boundary and tie-break, both values of
``pricing.discounts_on_special_prices``, tax dates, unsellable products, and properties."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP
from decimal import Decimal as D
from typing import Any

import pytest
from django.core.cache import cache
from django.utils import timezone
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.catalog.models import Brand, Category, Product, ProductTaxRate, Unit
from apps.platform.models import TenantSetting
from apps.pricing.models import DiscountRule, DiscountSlab, PriceList, PriceListItem, RetailerPrice
from apps.pricing.resolve import PriceUnavailable, resolve_price
from apps.retailers.services import create_retailer
from common.dates import today_ist
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
TODAY = today_ist()


@dataclass
class World:
    food: Category
    snacks: Category
    chips: Category
    drinks: Category
    lays: Brand
    other_brand: Brand
    p: Product  # chips, Lays, base 10.00
    q: Product  # no category or brand, base 20.00
    gold: PriceList
    r: object  # a shop on base prices
    s: object  # a shop on the Gold list


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def w(tenant_a):
    with tenant_context(tenant_a.pk):
        unit = Unit.objects.get(code="PCS")
        food = Category.objects.create(name="Food", slug="food")
        snacks = Category.objects.create(name="Snacks", slug="snacks", parent=food, level=2)
        chips = Category.objects.create(name="Chips", slug="chips", parent=snacks, level=3)
        drinks = Category.objects.create(name="Drinks", slug="drinks")
        lays = Brand.objects.create(name="Lays")
        other_brand = Brand.objects.create(name="Kurkure")
        p = Product.objects.create(
            code="P",
            name="Lays Classic",
            unit=unit,
            hsn_code="2106",
            category=chips,
            brand=lays,
            base_price=D("10.00"),
        )
        q = Product.objects.create(
            code="Q", name="Plain item", unit=unit, hsn_code="2106", base_price=D("20.00")
        )
        for product in (p, q):
            ProductTaxRate.objects.create(
                product=product, gst_rate=D("18"), effective_from=TODAY - timedelta(days=1000)
            )
        gold = PriceList.objects.create(name="Gold")
        PriceListItem.objects.create(price_list=gold, product=p, price=D("9.00"))
        r = create_retailer(shop_name="R", phone="9876500001", send_welcome=False)
        s = create_retailer(
            shop_name="S", phone="9876500002", send_welcome=False, extra={"price_list_id": gold.pk}
        )
    return World(food, snacks, chips, drinks, lays, other_brand, p, q, gold, r, s)


def price(tenant, retailer, product, qty="1", on=None):
    with tenant_context(tenant.pk):
        return resolve_price(retailer, product, D(qty), on=on)


def rule(tenant, **fields):
    defaults: dict[str, Any] = {
        "name": "Rule",
        "discount_type": "PERCENT",
        "value": D("10"),
        "scope_type": "ALL",
        "audience_type": "ALL",
    }
    defaults.update(fields)
    slabs = defaults.pop("slabs", [])
    with tenant_context(tenant.pk):
        created = DiscountRule.objects.create(**defaults)
        for min_qty, value in slabs:
            DiscountSlab.objects.create(rule=created, min_qty=D(min_qty), value=D(value))
        return created


def setting(tenant, key, value):
    with tenant_context(tenant.pk):
        TenantSetting.objects.update_or_create(key=key, defaults={"value": value})
    cache.clear()


# --- 1. Unit price: special → price list → base -----------------------------------------------


def test_price_sources(tenant_a, w):
    assert (price(tenant_a, w.r, w.p).unit_price, price(tenant_a, w.r, w.p).price_source) == (
        D("10.00"),
        "BASE",
    )
    on_list = price(tenant_a, w.s, w.p)
    assert (on_list.unit_price, on_list.price_source, on_list.base_price) == (
        D("9.00"),
        "PRICE_LIST",
        D("10.00"),
    )
    not_listed = price(tenant_a, w.s, w.q)  # the list has no price for Q
    assert (not_listed.unit_price, not_listed.price_source) == (D("20.00"), "BASE")
    with tenant_context(tenant_a.pk):
        RetailerPrice.objects.create(retailer=w.s, product=w.p, price=D("7.00"))
    special = price(tenant_a, w.s, w.p)  # the special price beats the price list
    assert (special.unit_price, special.price_source) == (D("7.00"), "SPECIAL")


def test_a_deleted_price_list_is_not_used(tenant_a, w):
    with tenant_context(tenant_a.pk):
        PriceList.objects.filter(pk=w.gold.pk).update(deleted_at=timezone.now())
    assert price(tenant_a, w.s, w.p).price_source == "BASE"


# --- 2. Discount types and line math ----------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "value", "qty", "discount", "net_unit", "valid"),
    [
        ("PERCENT", "10", "3", "3.00", "9.00", True),
        ("PERCENT", "7.5", "3", "2.25", "9.25", True),
        ("PERCENT", "33.33", "1", "3.33", "6.67", True),
        ("FLAT_PER_UNIT", "2", "3", "6.00", "8.00", True),
        ("FLAT_PER_UNIT", "12", "3", "30.00", "0.00", False),  # capped at the line: not sellable
        ("PERCENT", "100", "2", "20.00", "0.00", False),
    ],
)
def test_discount_line_math(tenant_a, w, kind, value, qty, discount, net_unit, valid):
    rule(tenant_a, discount_type=kind, value=D(value))
    result = price(tenant_a, w.r, w.p, qty)
    assert result.gross == D("10.00") * D(qty)
    assert result.discount is not None and result.discount.amount == D(discount)
    assert result.line_net == result.gross - result.discount.amount
    assert (result.net_unit_price, result.valid) == (D(net_unit), valid)


def test_fractional_quantities(tenant_a, w):
    with tenant_context(tenant_a.pk):
        Product.objects.filter(pk=w.p.pk).update(base_price=D("180.00"))
        w.p.refresh_from_db()
    rule(tenant_a, value=D("7.5"))
    result = price(tenant_a, w.r, w.p, "2.750")
    assert (result.gross, result.discount.amount, result.line_net) == (
        D("495.00"),
        D("37.13"),
        D("457.87"),
    )  # 37.125 rounds half-up


# --- 3. Scope: product, category (and its sub-categories), brand, all -------------------------


@pytest.mark.parametrize(
    ("scope", "target", "applies"),
    [
        ("ALL", None, True),
        ("PRODUCT", "p", True),
        ("PRODUCT", "q", False),
        ("CATEGORY", "food", True),  # an ancestor of Chips
        ("CATEGORY", "snacks", True),
        ("CATEGORY", "chips", True),
        ("CATEGORY", "drinks", False),
        ("BRAND", "lays", True),
        ("BRAND", "other_brand", False),
    ],
)
def test_scope(tenant_a, w, scope, target, applies):
    field = {"PRODUCT": "product", "CATEGORY": "category", "BRAND": "brand"}.get(scope)
    extra = {field: getattr(w, target)} if field else {}
    rule(tenant_a, scope_type=scope, **extra)
    assert (price(tenant_a, w.r, w.p).discount is not None) is applies


def test_products_without_category_or_brand_only_get_all_and_product_rules(tenant_a, w):
    rule(tenant_a, scope_type="CATEGORY", category=w.food, name="Category")
    rule(tenant_a, scope_type="BRAND", brand=w.lays, name="Brand")
    assert price(tenant_a, w.r, w.q).discount is None
    rule(tenant_a, scope_type="PRODUCT", product=w.q, name="Product", value=D("5"))
    assert price(tenant_a, w.r, w.q).discount.rule_name == "Product"


# --- 4. Audience: everyone, a price list, one shop --------------------------------------------


def test_audience(tenant_a, w):
    rule(tenant_a, audience_type="PRICE_LIST", price_list=w.gold, name="Gold only")
    assert price(tenant_a, w.r, w.p).discount is None
    assert price(tenant_a, w.s, w.p).discount.rule_name == "Gold only"
    rule(tenant_a, audience_type="RETAILER", retailer=w.r, name="R only")
    assert price(tenant_a, w.r, w.p).discount.rule_name == "R only"
    assert price(tenant_a, w.s, w.p).discount.rule_name == "Gold only"


# --- 5. Validity and active flag ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("valid_from", "valid_to", "offset", "applies"),
    [
        (0, 10, -1, False),  # the day before it starts
        (0, 10, 0, True),  # first day
        (0, 10, 10, True),  # last day
        (0, 10, 11, False),  # the day after
        (None, 10, -100, True),  # open start
        (0, None, 1000, True),  # open end
    ],
)
def test_validity_dates_are_inclusive(tenant_a, w, valid_from, valid_to, offset, applies):
    start = TODAY + timedelta(days=5)
    rule(
        tenant_a,
        valid_from=start + timedelta(days=valid_from) if valid_from is not None else None,
        valid_to=start + timedelta(days=valid_to) if valid_to is not None else None,
    )
    on = start + timedelta(days=offset)
    assert (price(tenant_a, w.r, w.p, on=on).discount is not None) is applies


def test_inactive_rules_never_apply(tenant_a, w):
    rule(tenant_a, is_active=False)
    assert price(tenant_a, w.r, w.p).discount is None


# --- 6. Quantity slabs --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("qty", "percent", "slab"),
    [
        ("11", None, None),
        ("12", "5.00", "12"),
        ("23", "5.00", "12"),
        ("24", "10.00", "24"),
        ("100", "10.00", "24"),
    ],
)
def test_slabs(tenant_a, w, qty, percent, slab):
    rule(tenant_a, value=D("0"), slabs=[("12", "5"), ("24", "10")])
    result = price(tenant_a, w.r, w.p, qty)
    if percent is None:
        assert result.discount is None  # a rule with slabs and none reached doesn't apply
    else:
        assert (result.discount.value, result.discount.slab_min_qty) == (D(percent), D(slab))
        assert result.discount.amount == (result.gross * D(percent) / 100).quantize(D("0.01"))


def test_flat_slab_per_unit(tenant_a, w):
    rule(tenant_a, discount_type="FLAT_PER_UNIT", value=D("0"), slabs=[("24", "1.50")])
    assert price(tenant_a, w.r, w.p, "36").discount.amount == D("54.00")  # 36 x 1.50


# --- 7. The single best rule and tie-breaks (PLAN M5) -----------------------------------------


def test_highest_amount_wins(tenant_a, w):
    rule(tenant_a, name="5%", value=D("5"))
    rule(tenant_a, name="Flat 2", discount_type="FLAT_PER_UNIT", value=D("2"))
    rule(tenant_a, name="12%", value=D("12"))
    assert price(tenant_a, w.r, w.p, "4").discount.rule_name == "Flat 2"  # 8.00 > 4.80 > 2.00


def test_tie_break_order(tenant_a, w):
    rule(tenant_a, name="all/all", value=D("10"))
    rule(tenant_a, name="brand", scope_type="BRAND", brand=w.lays, value=D("10"))
    assert price(tenant_a, w.r, w.p).discount.rule_name == "brand"  # brand beats all products
    rule(tenant_a, name="food", scope_type="CATEGORY", category=w.food, value=D("10"))
    assert price(tenant_a, w.r, w.p).discount.rule_name == "food"  # category beats brand
    rule(tenant_a, name="chips", scope_type="CATEGORY", category=w.chips, value=D("10"))
    assert price(tenant_a, w.r, w.p).discount.rule_name == "chips"  # deeper category
    rule(tenant_a, name="product", scope_type="PRODUCT", product=w.p, value=D("10"))
    assert price(tenant_a, w.r, w.p).discount.rule_name == "product"
    rule(tenant_a, name="gold list", audience_type="PRICE_LIST", price_list=w.gold, value=D("10"))
    assert price(tenant_a, w.s, w.p).discount.rule_name == "gold list"  # audience before scope
    rule(tenant_a, name="just S", audience_type="RETAILER", retailer=w.s, value=D("10"))
    assert price(tenant_a, w.s, w.p).discount.rule_name == "just S"
    rule(tenant_a, name="just S newer", audience_type="RETAILER", retailer=w.s, value=D("10"))
    assert price(tenant_a, w.s, w.p).discount.rule_name == "just S newer"  # newest last


def test_no_stacking(tenant_a, w):
    rule(tenant_a, name="a", value=D("10"))
    rule(tenant_a, name="b", value=D("5"))
    assert price(tenant_a, w.r, w.p, "10").discount.amount == D("10.00")  # not 15.00


# --- 8. Discounts on special prices (ADR-036, both values) ------------------------------------


@pytest.mark.parametrize("allowed", [True, False])
def test_discounts_on_special_prices_setting(tenant_a, w, allowed):
    setting(tenant_a, "pricing.discounts_on_special_prices", allowed)
    rule(tenant_a, value=D("10"))
    with tenant_context(tenant_a.pk):
        RetailerPrice.objects.create(retailer=w.r, product=w.p, price=D("8.00"))
    special = price(tenant_a, w.r, w.p, "2")
    assert special.price_source == "SPECIAL"
    if allowed:
        assert (special.discount.amount, special.line_net) == (D("1.60"), D("14.40"))
    else:
        assert (special.discount, special.line_net) == (None, D("16.00"))
    # Price-list and base prices get the discount either way.
    assert price(tenant_a, w.s, w.p, "2").discount.amount == D("1.80")
    assert price(tenant_a, w.r, w.q, "1").discount.amount == D("2.00")


# --- 9. Tax rates and sellability --------------------------------------------------------------


def test_tax_rate_on_the_day_and_price_basis(tenant_a, w):
    change = TODAY + timedelta(days=5)
    with tenant_context(tenant_a.pk):
        ProductTaxRate.objects.create(product=w.p, gst_rate=D("5"), effective_from=change)
    assert price(tenant_a, w.r, w.p).gst_rate == D("18")
    assert price(tenant_a, w.r, w.p, on=change).gst_rate == D("5")
    assert price(tenant_a, w.r, w.p).prices_include_gst is False
    setting(tenant_a, "tax.prices_include_gst", True)
    assert price(tenant_a, w.r, w.p).prices_include_gst is True


@pytest.mark.parametrize("state", ["future_rate_only", "inactive", "deleted"])
def test_unsellable_products_have_no_price(tenant_a, w, state):
    with tenant_context(tenant_a.pk):
        if state == "future_rate_only":
            fresh = Product.objects.create(
                code="F", name="Future", unit=w.p.unit, hsn_code="2106", base_price=D("5")
            )
            ProductTaxRate.objects.create(
                product=fresh, gst_rate=D("5"), effective_from=TODAY + timedelta(days=2)
            )
            target = fresh
        else:
            fields = (
                {"is_active": False}
                if state == "inactive"
                else {"deleted_at": timezone.now(), "is_active": False}
            )
            Product.objects.filter(pk=w.p.pk).update(**fields)
            target = Product.objects.get(pk=w.p.pk)
    with pytest.raises(PriceUnavailable):
        price(tenant_a, w.r, target)


# --- 10. Properties ----------------------------------------------------------------------------


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    base=st.decimals(min_value=D("0.01"), max_value=D("99999.99"), places=2),
    qty=st.decimals(min_value=D("0.001"), max_value=D("9999"), places=3),
    percent=st.one_of(st.none(), st.decimals(min_value=D("0.01"), max_value=D("100"), places=2)),
)
def test_price_properties(tenant_a, w, base, qty, percent):
    with tenant_context(tenant_a.pk):
        Product.objects.filter(pk=w.q.pk).update(base_price=base)
        DiscountRule.objects.all().delete()
        product = Product.objects.get(pk=w.q.pk)
    if percent is not None:
        rule(tenant_a, value=percent)
    result = price(tenant_a, w.r, product, str(qty))
    amount = result.discount.amount if result.discount else D("0")
    assert D("0") <= amount <= result.gross
    assert result.line_net == result.gross - amount
    assert result.gross == (base * qty).quantize(D("0.01"), rounding=ROUND_HALF_UP)


# --- API ---------------------------------------------------------------------------------------


def _client(tenant, role="OWNER", user=None):
    client = APIClient()
    user = user or make_staff_in(tenant, role)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


@covers("pricing-preview", "retailer-price-sheet")
def test_preview_and_price_sheet(tenant_a, tenant_b, w):
    rule(tenant_a, value=D("0"), slabs=[("12", "5")], name="Bulk")
    owner = _client(tenant_a)
    rows = owner.post(
        "/api/v1/pricing/preview/",
        {"retailer": str(w.s.pk), "lines": [{"product": str(w.p.pk), "qty": "12"}]},
        format="json",
    ).json()
    result = rows[0]["result"]
    assert (
        result["unit_price"],
        result["price_source"],
        result["discount"]["rule_name"],
        result["discount"]["amount"],
        result["net_unit_price"],
    ) == ("9.00", "PRICE_LIST", "Bulk", "5.40", "8.55")
    sheet = owner.get(f"/api/v1/retailers/{w.s.pk}/prices/").json()["results"]
    assert {row["product"]["code"]: row["result"]["unit_price"] for row in sheet} == {
        "P": "9.00",
        "Q": "20.00",
    }

    other = _client(tenant_b)
    assert (
        other.post(
            "/api/v1/pricing/preview/",
            {"retailer": str(w.s.pk), "lines": [{"product": str(w.p.pk), "qty": "1"}]},
            format="json",
        ).status_code
        == 404
    )
    assert other.get(f"/api/v1/retailers/{w.s.pk}/prices/").status_code == 404
    warehouse = _client(tenant_a, "WAREHOUSE")  # no pricing.view
    assert warehouse.get(f"/api/v1/retailers/{w.s.pk}/prices/").status_code == 403
