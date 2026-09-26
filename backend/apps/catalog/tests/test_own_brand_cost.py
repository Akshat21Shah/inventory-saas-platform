"""Own brand and cost price (ADR-039): who sees and sets the cost, audit, the product filter, the
shop badge setting, and the cost column in imports, templates and exports."""

import io
from decimal import Decimal as D

import pytest
from django.core.cache import cache
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.audit.models import AuditLog
from apps.catalog import services
from apps.catalog.models import Brand, Product, ProductTaxRate, Unit
from apps.dataio.kinds.products import ProductsKind
from apps.dataio.parsing import read_sheet
from apps.dataio.services import _synonyms
from apps.platform.models import TenantSetting
from apps.retailers.services import create_retailer
from common.dates import today_ist
from common.errors import InvalidFields
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
API = "/api/v1"


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


@pytest.fixture
def owner_user(tenant_a):
    return make_staff_in(tenant_a, "OWNER")


@pytest.fixture
def owner(tenant_a, owner_user):
    return _client(tenant_a, owner_user)


def _product(tenant, code, *, brand=None, cost=None, price="10.00"):
    with tenant_context(tenant.pk):
        product = Product.objects.create(
            code=code,
            name=f"Item {code}",
            unit=Unit.objects.get(code="PCS"),
            hsn_code="1905",
            base_price=D(price),
            brand=brand,
            cost_price=D(cost) if cost else None,
        )
        ProductTaxRate.objects.create(product=product, gst_rate=D("5"), effective_from=today_ist())
        return product


def test_brands_can_be_marked_own_brand_and_products_filtered(tenant_a, tenant_b, owner):
    house = owner.post(
        f"{API}/brands/", {"name": "Sharma Gold", "own_brand": True}, format="json"
    ).json()
    traded = owner.post(f"{API}/brands/", {"name": "Parle"}, format="json").json()
    assert (house["own_brand"], traded["own_brand"]) == (True, False)
    renamed = owner.patch(f"{API}/brands/{traded['id']}/", {"own_brand": True}, format="json")
    assert renamed.json() == {"id": traded["id"], "name": "Parle", "own_brand": True}
    change = AuditLog.objects.filter(action="catalog.brand_updated").last()
    assert change is not None and change.changes == {"own_brand": [False, True]}
    owner.patch(f"{API}/brands/{traded['id']}/", {"own_brand": False}, format="json")

    with tenant_context(tenant_a.pk):
        brands = {b.name: b for b in Brand.objects.all()}
    _product(tenant_a, "OWN-1", brand=brands["Sharma Gold"])
    _product(tenant_a, "TR-1", brand=brands["Parle"])
    _product(tenant_a, "NB-1")
    codes = lambda q: sorted(r["code"] for r in owner.get(f"{API}/products/", q).json()["results"])  # noqa: E731
    assert codes({"own_brand": "true"}) == ["OWN-1"]
    assert codes({"own_brand": "false"}) == ["NB-1", "TR-1"]
    listed = owner.get(f"{API}/products/", {"search": "OWN-1"}).json()["results"][0]
    assert listed["own_brand"] is True

    other = _client(tenant_b, make_staff_in(tenant_b, "OWNER"))
    assert (
        other.patch(f"{API}/brands/{house['id']}/", {"own_brand": False}, format="json").status_code
        == 404
    )


def test_cost_price_is_seen_only_with_costs_view_and_audited(tenant_a, owner):
    unit = owner.get(f"{API}/units/").json()["results"][0]["id"]
    created = owner.post(
        f"{API}/products/",
        {
            "code": "C-1",
            "name": "Costed",
            "unit": unit,
            "hsn_code": "1905",
            "base_price": "10.00",
            "cost_price": "7.25",
            "gst_rate": "5",
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    product_id = created.json()["id"]
    assert created.json()["cost_price"] == "7.25"
    owner.patch(f"{API}/products/{product_id}/", {"cost_price": "7.50"}, format="json")
    change = AuditLog.objects.get(action="catalog.product_price_changed")
    assert change.changes == {"cost_price": ["7.25", "7.50"]}

    # costs.view (ADR-042): accounts staff yes; sales (pricing.view only) and warehouse no.
    for role, visible in (
        ("ACCOUNTS", "7.50"),
        ("MANAGER", "7.50"),
        ("SALES", None),
        ("WAREHOUSE", None),
    ):
        viewer = _client(tenant_a, make_staff_in(tenant_a, role))
        assert viewer.get(f"{API}/products/{product_id}/").json()["cost_price"] == visible, role


def test_only_cost_managers_can_set_cost(tenant_a):
    warehouse = make_staff_in(tenant_a, "WAREHOUSE")
    product = _product(tenant_a, "C-2")
    with tenant_context(tenant_a.pk), pytest.raises(InvalidFields) as refused:
        services.update_product(product.pk, {"cost_price": D("5")}, by=warehouse)
    assert "cost_price" in refused.value.details["fields"]
    with tenant_context(tenant_a.pk):  # other edits still work without the cost
        services.update_product(product.pk, {"name": "Renamed"}, by=warehouse)


@pytest.mark.parametrize("badge", [False, True])
def test_shops_never_see_cost_and_see_the_badge_only_when_switched_on(tenant_a, badge):
    with tenant_context(tenant_a.pk):
        house = Brand.objects.create(name="House", own_brand=True)
        TenantSetting.objects.update_or_create(
            key="retailers.show_own_brand_badge", defaults={"value": badge}
        )
        create_retailer(shop_name="Shop", phone="9876500011", send_welcome=False)
    cache.clear()
    _product(tenant_a, "OWN-9", brand=house, cost="4.00")
    _product(tenant_a, "TR-9", cost="3.00")
    shop = _client(tenant_a, User.objects.get(tenant=tenant_a, phone="+919876500011"))
    rows = {r["code"]: r for r in shop.get(f"{API}/shop/products/").json()["results"]}
    assert (rows["OWN-9"]["own_brand"], rows["TR-9"]["own_brand"]) == (badge, False)
    detail = shop.get(f"{API}/shop/products/{rows['OWN-9']['id']}/").json()
    body = str(rows) + str(detail)
    assert "cost" not in body and "4.00" not in body


def _sheet(rows):
    from openpyxl import Workbook

    book = Workbook()
    for row in rows:
        book.worksheets[0].append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return read_sheet("products.xlsx", buffer.getvalue(), _synonyms(ProductsKind()))


def test_the_cost_column_needs_pricing_permission_in_imports(tenant_a, owner_user):
    header = ["Product code", "Product name", "Unit", "HSN code", "GST rate", "Price", "Cost price"]
    sheet = _sheet([header, ["IC-1", "Imported", "PCS", "1905", "5", "10", "6.40"]])
    warehouse = make_staff_in(tenant_a, "WAREHOUSE")
    with tenant_context(tenant_a.pk):
        [refused] = ProductsKind().plan(sheet, "ADD_ONLY", warehouse)
        [allowed] = ProductsKind().plan(sheet, "ADD_ONLY", owner_user)
    assert refused.action == "ERROR"
    assert refused.messages() == [
        "Row 2, column “Cost price”: You can't set cost prices. Remove this column or ask "
        "someone who manages costs."
    ]
    assert allowed.action == "NEW" and allowed.data["cost_price"] == D("6.40")

    _product(tenant_a, "IC-2", cost="5.00")
    update = _sheet([["Product code", "Cost price"], ["IC-2", "5.50"]])
    with tenant_context(tenant_a.pk):
        [plan] = ProductsKind().plan(update, "ADD_OR_UPDATE", owner_user)
    assert plan.changes == {"Cost price": ["5.00", "5.50"]}
    assert plan.highlight == ["Cost price"]


def test_templates_and_exports_leave_out_cost_without_pricing_view(tenant_a, owner):
    _product(tenant_a, "EX-1", cost="3.30")
    warehouse = _client(tenant_a, make_staff_in(tenant_a, "WAREHOUSE"))

    def header(client, url):
        response = client.get(url)
        assert response.status_code == 200, response.content[:200]
        book = load_workbook(io.BytesIO(response.content))
        return [c.value for c in book.worksheets[0][1]]

    assert "Cost price" in header(owner, f"{API}/products/export/?file_type=xlsx")
    assert "Cost price" not in header(warehouse, f"{API}/products/export/?file_type=xlsx")
    assert "Cost price" in header(owner, f"{API}/imports/templates/products/")
