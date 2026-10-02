"""Free-goods schemes (ADR-056 item 7): create, change and delete with validation and audit; who
may; the module switched off; the ₹0-price warning pointing to schemes; and isolation."""

import pytest
from django.core.cache import cache

from apps.audit.models import AuditLog
from apps.catalog.models import Unit
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import make_shop, staff_client
from apps.platform.models import FeatureFlag, TenantFeature
from apps.platform.selectors import invalidate_tenant_features
from apps.pricing import free_goods
from apps.pricing.models import RetailerPrice
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1/free-goods-schemes/"


def switch(tenant, on=True):
    with tenant_context(tenant.pk):
        TenantFeature.objects.update_or_create(
            flag=FeatureFlag.objects.get(code="free_goods"), defaults={"enabled": on}
        )
    invalidate_tenant_features(tenant.pk)


@pytest.fixture
def world(tenant_a, tenant_b):
    cache.clear()
    switch(tenant_a)
    switch(tenant_b)
    with tenant_context(tenant_a.pk):
        kg = Unit.objects.get(code="KG")
    yield {
        "t": tenant_a,
        "b": tenant_b,
        "owner": staff_client(tenant_a),
        "sales": staff_client(tenant_a, "SALES"),
        "warehouse": staff_client(tenant_a, "WAREHOUSE"),
        "other": staff_client(tenant_b),
        "p1": make_product(tenant_a, "P-1"),
        "sugar": make_product(tenant_a, "SUGAR", unit=kg),
        "shop": make_shop(tenant_a, "9876500091"),
    }
    cache.clear()


def body(world, **extra):
    return {
        "name": "Buy 10 get 1",
        "buy_product": str(world["p1"].pk),
        "buy_qty": "10",
        "free_product": str(world["p1"].pk),
        "free_qty": "1",
        "audience_type": "ALL",
        **extra,
    }


def fields(response):
    assert response.status_code == 400, response.json()
    return response.json()["error"]["details"]["fields"]


@covers("free-goods-schemes", "free-goods-scheme-detail")
def test_create_change_delete_audited_and_isolated(world):
    owner, other = world["owner"], world["other"]
    created = owner.post(API, body(world, max_free_qty="5"), format="json")
    assert created.status_code == 201, created.json()
    scheme = created.json()
    assert (scheme["buy_product"]["code"], scheme["buy_qty"], scheme["max_free_qty"]) == (
        "P-1",
        "10.000",
        "5.000",
    )
    url = f"{API}{scheme['id']}/"
    changed = owner.patch(
        url,
        {"audience_type": "RETAILER", "retailer": str(world["shop"].pk), "repeat": False},
        format="json",
    )
    assert changed.status_code == 200 and changed.json()["retailer"]["shop_name"]
    assert [s["name"] for s in owner.get(API, {"search": "p-1"}).json()["results"]] == [
        "Buy 10 get 1"
    ]
    assert world["sales"].get(url).status_code == 200  # pricing.view reads
    assert world["sales"].patch(url, {"name": "x"}, format="json").status_code == 403
    assert world["warehouse"].get(API).status_code == 403
    # Another distributor sees and changes none of it.
    assert other.get(API).json()["results"] == []
    assert other.get(url).status_code == 404
    assert other.patch(url, {"name": "Mine"}, format="json").status_code == 404
    assert other.delete(url).status_code == 404
    assert owner.delete(url).status_code == 204
    with tenant_context(world["t"].pk):
        actions = list(
            AuditLog.objects.filter(action__startswith="pricing.scheme_")
            .order_by("created_at")
            .values_list("action", flat=True)
        )
    assert actions == ["pricing.scheme_created", "pricing.scheme_updated", "pricing.scheme_deleted"]


def test_validation(world):
    owner = world["owner"]
    assert set(fields(owner.post(API, body(world, buy_qty="2.5"), format="json"))) == {"buy_qty"}
    # Kilograms can be split; a cap below one lot of free units can't be right.
    sugar = str(world["sugar"].pk)
    assert (
        owner.post(API, body(world, free_product=sugar, free_qty="0.5"), format="json").status_code
        == 201
    )
    assert "max_free_qty" in fields(
        owner.post(API, body(world, free_qty="2", max_free_qty="1"), format="json")
    )
    one_shop = body(world, audience_type="RETAILER")
    assert "retailer" in fields(owner.post(API, one_shop, format="json"))
    assert "valid_to" in fields(
        owner.post(API, body(world, valid_from="2026-10-10", valid_to="2026-10-01"), format="json")
    )
    their = make_product(world["b"], "X-1")
    assert "free_product" in fields(
        owner.post(API, body(world, free_product=str(their.pk)), format="json")
    )


def test_switched_off_the_module_is_refused(world):
    switch(world["t"], False)
    refused = world["owner"].get(API)
    assert (refused.status_code, refused.json()["error"]["code"]) == (403, "MODULE_NOT_ENABLED")


def test_the_zero_price_warning_points_to_schemes_when_they_are_on(world):
    with tenant_context(world["t"].pk):
        row = RetailerPrice.objects.create(retailer=world["shop"], product=world["p1"], price=0)
        [on] = free_goods.special_price_warnings(row)
    switch(world["t"], False)
    with tenant_context(world["t"].pk):
        [off] = free_goods.special_price_warnings(row)
    assert (on.details["schemes"], off.details["schemes"]) == (True, False)
    assert "use a free-goods scheme" in on.message
