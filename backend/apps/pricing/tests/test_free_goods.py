"""Free-goods warning (ADR-036): saving a rule or special price that makes products free for shops
succeeds, with a warning naming how many products and shops."""

from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.catalog.models import Category, Product, Unit
from apps.platform.models import TenantSetting
from apps.pricing import services
from apps.pricing.models import PriceList, PriceListItem, RetailerPrice
from apps.retailers.services import create_retailer
from common.dates import today_ist
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
TODAY = today_ist()


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def world(tenant_a):
    """A 10.00 and B 20.00 (in Food > Snacks); Z has no price; H is hidden from shops.
    r1 pays base prices; r2 is on Gold (A at 16.00); r3 has a special price of 12.00 on B."""
    with tenant_context(tenant_a.pk):
        unit = Unit.objects.get(code="PCS")
        food = Category.objects.create(name="Food", slug="food")
        snacks = Category.objects.create(name="Snacks", slug="snacks", parent=food, level=2)

        def product(code, price, **extra):
            return Product.objects.create(
                code=code, name=code, unit=unit, hsn_code="2106", base_price=D(price), **extra
            )

        a = product("A", "10.00", category=snacks)
        b = product("B", "20.00", category=snacks)
        product("Z", "0.00")
        product("H", "1.00", show_in_shop=False)
        gold = PriceList.objects.create(name="Gold")
        PriceListItem.objects.create(price_list=gold, product=a, price=D("16.00"))
        r1 = create_retailer(shop_name="R1", phone="9876500001", send_welcome=False)
        r2 = create_retailer(
            shop_name="R2",
            phone="9876500002",
            send_welcome=False,
            extra={"price_list_id": gold.pk},
        )
        r3 = create_retailer(shop_name="R3", phone="9876500003", send_welcome=False)
        RetailerPrice.objects.create(retailer=r3, product=b, price=D("12.00"))
    return {"a": a, "b": b, "food": food, "gold": gold, "r1": r1, "r2": r2, "r3": r3}


def _rule(tenant, owner, **fields):
    data = {
        "name": "Rule",
        "discount_type": "PERCENT",
        "value": D("10"),
        "scope_type": "ALL",
        "audience_type": "ALL",
    }
    slabs = fields.pop("slabs", None)
    data.update(fields)
    with tenant_context(tenant.pk):
        inputs = [services.SlabInput(D(q), D(v)) for q, v in slabs] if slabs else None
        return services.save_discount_rule(None, data, inputs, by=owner)[1]


def _messages(warnings):
    return [w.message for w in warnings]


@pytest.fixture
def owner(tenant_a):
    return make_staff_in(tenant_a, "OWNER")


def test_a_full_percentage_frees_every_priced_shop_product_for_every_shop(tenant_a, world, owner):
    warnings = _rule(tenant_a, owner, value=D("100"))
    assert _messages(warnings) == [
        "This rule makes 2 products free for 3 retailers. Free-goods schemes are not supported yet."
    ]
    assert warnings[0].code == "FREE_GOODS" and warnings[0].details == {
        "products": 2,
        "retailers": 3,
        "schemes": False,
    }
    assert _rule(tenant_a, owner, value=D("99.99")) == []


@pytest.mark.parametrize(("on_special", "products", "retailers"), [(True, 2, 2), (False, 1, 2)])
def test_rupees_off_compares_with_each_shops_own_price(
    tenant_a, world, owner, on_special, products, retailers
):
    with tenant_context(tenant_a.pk):
        TenantSetting.objects.update_or_create(
            key="pricing.discounts_on_special_prices", defaults={"value": on_special}
        )
    cache.clear()
    # ₹15 off: A (10.00) for r1 and r3; not for r2 (Gold: 16.00); B (20.00) only for r3 (12.00
    # special), and only when discounts apply on top of special prices.
    warnings = _rule(tenant_a, owner, discount_type="FLAT_PER_UNIT", value=D("15"))
    assert warnings[0].details == {"products": products, "retailers": retailers, "schemes": False}


def test_scope_audience_slabs_and_dates(tenant_a, world, owner):
    one = "This rule makes 1 product free for 1 retailer."
    assert _messages(
        _rule(
            tenant_a,
            owner,
            value=D("100"),
            scope_type="PRODUCT",
            product_id=world["a"].pk,
            audience_type="RETAILER",
            retailer_id=world["r1"].pk,
        )
    )[0].startswith(one)
    assert _rule(
        tenant_a, owner, value=D("100"), audience_type="PRICE_LIST", price_list_id=world["gold"].pk
    )[0].details == {"products": 2, "retailers": 1, "schemes": False}
    assert (
        _rule(tenant_a, owner, value=D("100"), scope_type="CATEGORY", category_id=world["food"].pk)[
            0
        ].details["products"]
        == 2
    )  # sub-categories count
    assert _rule(tenant_a, owner, value=D("0"), slabs=[("10", "5"), ("100", "100")])  # top slab
    assert _rule(tenant_a, owner, value=D("100"), is_active=False) == []
    assert _rule(tenant_a, owner, value=D("100"), valid_to=TODAY - timedelta(days=1)) == []
    assert _rule(tenant_a, owner, value=D("100"), valid_from=TODAY + timedelta(days=5))


def test_special_prices(tenant_a, world, owner):
    free = [
        "This special price makes 1 product free for 1 retailer. Free-goods schemes are not "
        "supported yet."
    ]
    with tenant_context(tenant_a.pk):
        _, warnings = services.save_retailer_price(
            None, retailer_id=world["r1"].pk, product_id=world["a"].pk, price=D("0"), by=owner
        )
        assert _messages(warnings) == free
    _rule(
        tenant_a,
        owner,
        discount_type="FLAT_PER_UNIT",
        value=D("5"),
        scope_type="CATEGORY",
        category_id=world["food"].pk,
    )
    with tenant_context(tenant_a.pk):
        row = RetailerPrice.objects.get(retailer=world["r3"])
        assert services.save_retailer_price(row.pk, price=D("6"), by=owner)[1] == []
        assert _messages(services.save_retailer_price(row.pk, price=D("5"), by=owner)[1]) == free
        TenantSetting.objects.update_or_create(
            key="pricing.discounts_on_special_prices", defaults={"value": False}
        )
    cache.clear()
    with tenant_context(tenant_a.pk):
        assert services.save_retailer_price(row.pk, price=D("4"), by=owner)[1] == []


def test_the_api_returns_the_warning_and_still_saves(tenant_a, world, owner):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(owner, tenant_a.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant_a.slug}.localhost"
    created = client.post(
        "/api/v1/discount-rules/",
        {
            "name": "All free",
            "discount_type": "PERCENT",
            "value": "100",
            "scope_type": "ALL",
            "audience_type": "ALL",
        },
        format="json",
    )
    assert created.status_code == 201
    assert [w["code"] for w in created.json()["warnings"]] == ["FREE_GOODS"]
    assert client.get(f"/api/v1/discount-rules/{created.json()['id']}/").json()["warnings"] == []
    special = client.post(
        "/api/v1/retailer-prices/",
        {"retailer": str(world["r1"].pk), "product": str(world["b"].pk), "price": "0"},
        format="json",
    )
    assert special.status_code == 201
    assert special.json()["warnings"][0]["details"] == {
        "products": 1,
        "retailers": 1,
        "schemes": False,
    }


def test_a_zero_list_price_is_free_for_the_lists_shops_without_a_special_price(
    tenant_a, world, owner
):
    with tenant_context(tenant_a.pk):
        other = create_retailer(
            shop_name="R4",
            phone="9876500004",
            send_welcome=False,
            extra={"price_list_id": world["gold"].pk},
        )
        RetailerPrice.objects.create(retailer=other, product=world["b"], price=D("15"))
        changed, warnings = services.upsert_items(
            world["gold"].pk,
            [services.ItemInput(world["a"].pk, D("0")), services.ItemInput(world["b"].pk, D("0"))],
            by=owner,
        )
    assert changed == 2
    assert _messages(warnings) == [
        "This price list makes 2 products free for 2 retailers. Free-goods schemes are not "
        "supported yet."
    ]
    assert warnings[0].details == {
        "products": 2,
        "retailers": 2,
        "schemes": False,
    }  # R4 pays 15 for B
    with tenant_context(tenant_a.pk):
        _, none = services.upsert_items(
            world["gold"].pk, [services.ItemInput(world["a"].pk, D("3"))], by=owner
        )
    assert none == []
