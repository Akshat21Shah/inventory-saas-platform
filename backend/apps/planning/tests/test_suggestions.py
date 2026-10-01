"""Reorder suggestions (ADR-053 items 8 and 10): the formula with demand, lead time, safety and
cover days and the supplier's pack; little history; what is on order and waiting; refresh,
changes, dismissal, purchase orders from suggestions and reorder levels from them; the dashboard
tiles, the Purchases by supplier report, and what is on order on backorder lines."""

from datetime import timedelta
from decimal import Decimal as D
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.catalog.models import Product
from apps.compliance.tests.conftest import switch_on
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_stock, client_for, make_shop, place, shop_client
from apps.planning import suggestions
from apps.planning.models import ProductStats, ReorderSuggestion
from apps.purchasing.models import PurchaseOrder, Supplier, SupplierProduct
from common.dates import today_ist
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


def _stats(tenant: Any, product: Any, per_day: str) -> None:
    with tenant_context(tenant.pk):
        ProductStats.objects.update_or_create(
            product=product,
            defaults={
                "computed_at": timezone.now(),
                "demand_days": 30,
                "demand_qty": D(per_day) * 30,
                "per_day": D(per_day),
                "movement_days": 90,
            },
        )


@pytest.fixture
def world(tenant_a, tenant_b):
    cache.clear()
    switch_on(tenant_a, "stock_planning", "purchasing")
    switch_on(tenant_b, "stock_planning", "purchasing")  # so isolation, not the flag, is tested
    owner = make_staff_in(tenant_a, "OWNER")
    tea = make_product(tenant_a, "TEA", name="Tata Tea Gold")
    soap = make_product(tenant_a, "SOAP", name="Lifebuoy Soap")
    newbie = make_product(tenant_a, "NEW", name="New Noodles")
    levelled = make_product(tenant_a, "LVL", name="Levelled Lentils", reorder_level=D("10"))
    add_stock(tenant_a, tea, "20")
    add_stock(tenant_a, soap, "100")
    add_stock(tenant_a, levelled, "4")
    shop = make_shop(tenant_a, "9876500101")
    place(tenant_a, shop, (newbie, "3"))  # nothing in stock: 3 waiting
    _stats(tenant_a, tea, "4")
    _stats(tenant_a, soap, "1")
    with tenant_context(tenant_a.pk):
        supplier = Supplier.objects.create(
            code="S-0001", name="Hindustan Traders", lead_time_days=5
        )
        SupplierProduct.objects.create(
            supplier=supplier, product=tea, is_preferred=True, pack_size=D("10")
        )
    return {
        "t": tenant_a,
        "b": tenant_b,
        "owner_user": owner,
        "owner": client_for(tenant_a, owner),
        "warehouse": client_for(tenant_a, make_staff_in(tenant_a, "WAREHOUSE")),
        "sales": client_for(tenant_a, make_staff_in(tenant_a, "SALES")),
        "other": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
        "tea": tea,
        "soap": soap,
        "newbie": newbie,
        "levelled": levelled,
        "shop": shop,
        "supplier": supplier,
    }


def refresh(world: dict[str, Any]) -> dict[str, ReorderSuggestion]:
    with tenant_context(world["t"].pk):
        suggestions.refresh_suggestions()
        return {
            s.product.code: s
            for s in ReorderSuggestion.objects.filter(status="OPEN").select_related("product")
        }


def test_the_formula_with_demand_and_with_little_history(world):
    found = refresh(world)
    assert set(found) == {"TEA", "NEW", "LVL"}  # soap has plenty
    tea = found["TEA"]
    # d = 4, lead 5 (the supplier's), safety 7 days = 28: point 4 x 5 + 28 = 48; position 20.
    # Order 4 x (5 + 14) + 28 - 20 = 84, up to the supplier's pack of 10: 90.
    assert (tea.basis, tea.lead_days, tea.lead_source) == ("DEMAND", 5, "SUPPLIER")
    assert (tea.reorder_point, tea.suggested_qty, tea.pack_size) == (
        D("48.000"),
        D("90.000"),
        D("10.000"),
    )
    assert (tea.available, tea.days_left, tea.supplier_id) == (
        D("20.000"),
        D("5.0"),
        world["supplier"].pk,
    )
    new, lvl = found["NEW"], found["LVL"]
    assert (new.basis, new.waiting, new.suggested_qty, new.lead_source) == (
        "LOW_HISTORY",
        D("3.000"),
        D("3.000"),
        "DEFAULT",
    )
    assert (lvl.basis, lvl.reorder_level, lvl.suggested_qty, lvl.days_left) == (
        "LOW_HISTORY",
        D("10.000"),
        D("6.000"),
        None,
    )


def test_what_is_on_order_counts(world, run):
    owner = world["owner"]
    order = run(
        owner.post,
        f"{API}/purchase-orders/",
        {
            "supplier_id": str(world["supplier"].pk),
            "lines": [{"product_id": str(world["tea"].pk), "entered_qty": "30"}],
        },
        format="json",
    ).json()
    refresh(world)
    with tenant_context(world["t"].pk):
        assert (
            ReorderSuggestion.objects.get(product=world["tea"], status="OPEN").on_order == 0
        )  # a draft
    run(
        owner.post,
        f"{API}/purchase-orders/{order['id']}/send/",
        HTTP_IDEMPOTENCY_KEY=f"k-{uuid4().hex}",
    )
    assert "TEA" not in refresh(world)  # 20 + 30 on order is above the point of 48
    with tenant_context(world["t"].pk):
        assert ReorderSuggestion.objects.get(product=world["tea"]).status == "RESOLVED"


def test_changes_and_dismissals_last_through_a_refresh(world):
    found = refresh(world)
    with tenant_context(world["t"].pk):
        suggestions.change_quantity(found["TEA"].pk, D("100"), by=world["owner_user"])
        suggestions.dismiss(found["NEW"].pk, until=None, by=world["owner_user"])
    again = refresh(world)
    assert (again["TEA"].pk, again["TEA"].to_order) == (found["TEA"].pk, D("100.000"))
    assert "NEW" not in again  # dismissed for a week
    with tenant_context(world["t"].pk):
        ReorderSuggestion.objects.filter(product=world["newbie"]).update(
            dismissed_until=today_ist()
        )
    assert "NEW" in refresh(world)


@covers("reorder-suggestions", "reorder-suggestion")
def test_the_list_and_who_sees_the_supplier(world):
    refresh(world)
    rows = world["owner"].get(f"{API}/reorder-suggestions/").json()["results"]
    # Shops waiting first (no daily demand), then the fewest days left.
    assert [r["product_code"] for r in rows][-1] == "TEA"
    tea = rows[-1]
    assert (tea["supplier_name"], tea["to_order"], tea["per_day"]) == (
        "Hindustan Traders",
        "90.000",
        "4.000",
    )
    paged, url = [], f"{API}/reorder-suggestions/?page_size=1"
    while url:  # page by page, in the same order
        page = world["owner"].get(url).json()
        paged += [r["product_code"] for r in page["results"]]
        url = page["next"]
    assert paged == [r["product_code"] for r in rows]
    sales = world["sales"].get(f"{API}/reorder-suggestions/").json()["results"]  # stock.view
    assert {r["supplier_name"] for r in sales} == {None}
    assert not {k for r in rows for k in r if "cost" in k or "value" in k}
    url = f"{API}/reorder-suggestions/{tea['id']}/"
    changed = world["owner"].patch(url, {"quantity": "95"}, format="json").json()
    assert (changed["quantity"], changed["to_order"]) == ("95.000", "95.000")
    assert world["warehouse"].patch(url, {"quantity": "1"}, format="json").status_code == 403
    assert world["owner"].patch(url, {"dismiss": True}, format="json").status_code == 200
    assert world["owner"].get(url).status_code == 200  # still readable, no longer open
    assert world["owner"].patch(url, {"quantity": "1"}, format="json").status_code == 404
    assert world["other"].get(url).status_code == 404
    assert world["other"].get(f"{API}/reorder-suggestions/").json()["results"] == []


@covers("reorder-suggestions-create-orders")
def test_purchase_orders_from_suggestions_grouped_by_supplier(world, run):
    found = refresh(world)
    with tenant_context(world["t"].pk):
        other = Supplier.objects.create(code="S-0002", name="Patel Agencies")
        SupplierProduct.objects.create(supplier=other, product=world["levelled"], is_preferred=True)
    found = refresh(world)
    url = f"{API}/reorder-suggestions/create-orders/"
    refused = run(
        world["owner"].post,
        url,
        {"suggestion_ids": [str(found["NEW"].pk)]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"k-{uuid4().hex}",
    )
    assert "NEW" in refused.json()["error"]["details"]["fields"]["suggestion_ids"][0]  # no supplier
    made = run(
        world["owner"].post,
        url,
        {"suggestion_ids": [str(found["TEA"].pk), str(found["LVL"].pk)]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"k-{uuid4().hex}",
    )
    assert made.status_code == 201, made.json()
    assert sorted((o["supplier_name"], o["line_count"]) for o in made.json()) == [
        ("Hindustan Traders", 1),
        ("Patel Agencies", 1),
    ]
    with tenant_context(world["t"].pk):
        tea = ReorderSuggestion.objects.get(pk=found["TEA"].pk)
        assert (tea.status, tea.purchase_order_line.quantity) == ("ORDERED", D("90.000"))
        assert PurchaseOrder.objects.filter(status="DRAFT").count() == 2
    assert (
        run(
            world["warehouse"].post,
            url,
            {"suggestion_ids": [str(found["NEW"].pk)]},
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid4().hex}",
        ).status_code
        == 403
    )
    assert (
        run(
            world["other"].post,
            url,
            {"suggestion_ids": [str(found["NEW"].pk)]},
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"k-{uuid4().hex}",
        ).status_code
        == 400
    )


@covers("reorder-suggestions-apply-levels")
def test_reorder_points_become_reorder_levels_only_when_asked(world):
    found = refresh(world)
    with tenant_context(world["t"].pk):
        assert Product.objects.get(pk=world["tea"].pk).reorder_level == 0  # never automatic
    url = f"{API}/reorder-suggestions/apply-reorder-levels/"
    applied = world["warehouse"].post(
        url, {"suggestion_ids": [str(found["TEA"].pk)]}, format="json"
    )
    assert applied.json() == {"changed": 1}  # stock.adjust may
    with tenant_context(world["t"].pk):
        assert Product.objects.get(pk=world["tea"].pk).reorder_level == D("48")
        assert AuditLog.objects.filter(action="stock.reorder_level_changed").count() == 1
    assert (
        world["sales"]
        .post(url, {"suggestion_ids": [str(found["TEA"].pk)]}, format="json")
        .status_code
        == 403
    )
    assert (
        world["other"]
        .post(url, {"suggestion_ids": [str(found["TEA"].pk)]}, format="json")
        .status_code
        == 400
    )


def test_stock_planning_switched_off(world):
    refresh(world)
    from apps.platform.models import FeatureFlag, TenantFeature
    from apps.platform.selectors import invalidate_tenant_features

    with tenant_context(world["t"].pk):
        TenantFeature.objects.filter(flag=FeatureFlag.objects.get(code="stock_planning")).update(
            enabled=False
        )
    invalidate_tenant_features(world["t"].pk)
    refused = world["owner"].get(f"{API}/reorder-suggestions/")
    assert (refused.status_code, refused.json()["error"]["code"]) == (403, "MODULE_NOT_ENABLED")
    assert world["owner"].get(f"{API}/dashboard/").json()["action"]["to_reorder"] is None


def test_the_dashboard_counts_suggestions_and_late_orders(world, run):
    refresh(world)
    order = run(
        world["owner"].post,
        f"{API}/purchase-orders/",
        {
            "supplier_id": str(world["supplier"].pk),
            "lines": [{"product_id": str(world["soap"].pk), "entered_qty": "5"}],
        },
        format="json",
    ).json()
    run(
        world["owner"].post,
        f"{API}/purchase-orders/{order['id']}/send/",
        HTTP_IDEMPOTENCY_KEY=f"k-{uuid4().hex}",
    )
    with tenant_context(world["t"].pk):
        PurchaseOrder.objects.filter(pk=order["id"]).update(
            expected_date=today_ist() - timedelta(days=2)
        )
    action = world["owner"].get(f"{API}/dashboard/").json()["action"]
    assert (action["to_reorder"], action["late_purchase_orders"]) == (3, 1)
    sales = world["sales"].get(f"{API}/dashboard/").json()["action"]
    assert (sales["to_reorder"], sales["late_purchase_orders"]) == (3, None)  # no purchasing.view
    other = world["other"].get(f"{API}/dashboard/").json()["action"]
    assert (other["to_reorder"], other["late_purchase_orders"]) == (0, 0)


def test_purchases_by_supplier_and_on_order_in_backorder_demand(world, run):
    owner = world["owner"]
    order = run(
        owner.post,
        f"{API}/purchase-orders/",
        {
            "supplier_id": str(world["supplier"].pk),
            "expected_date": str(today_ist() + timedelta(days=4)),
            "lines": [
                {"product_id": str(world["newbie"].pk), "entered_qty": "12", "entered_cost": "9"}
            ],
        },
        format="json",
    ).json()
    run(
        owner.post,
        f"{API}/purchase-orders/{order['id']}/send/",
        HTTP_IDEMPOTENCY_KEY=f"k-{uuid4().hex}",
    )
    demand = owner.get(f"{API}/reports/backorder_demand/").json()
    [row] = demand["rows"]
    assert (row["code"], row["on_order"], row["expected"]) == (
        "NEW",
        "12.000",
        str(today_ist() + timedelta(days=4)),
    )
    period = {"date_from": str(today_ist() - timedelta(days=1)), "date_to": str(today_ist())}
    report = owner.get(f"{API}/reports/purchases_by_supplier/", period).json()
    [supplier] = report["rows"]
    assert (supplier["supplier"], supplier["orders_sent"], supplier["open_orders"]) == (
        "Hindustan Traders",
        1,
        1,
    )
    assert "value" in supplier
    no_costs = world["warehouse"].get(f"{API}/reports/purchases_by_supplier/", period).json()
    assert "value" not in no_costs["rows"][0]
    assert world["sales"].get(f"{API}/reports/purchases_by_supplier/", period).status_code in (
        403,
        404,
    )
    other = world["other"]
    assert other.get(f"{API}/reports/purchases_by_supplier/", period).json()["rows"] == []
    assert other.get(f"{API}/reports/backorder_demand/").json()["rows"] == []
    # With purchasing off, the report doesn't exist and the columns are left out.
    from apps.platform.models import FeatureFlag, TenantFeature
    from apps.platform.selectors import invalidate_tenant_features

    with tenant_context(world["t"].pk):
        TenantFeature.objects.filter(flag=FeatureFlag.objects.get(code="purchasing")).update(
            enabled=False
        )
    invalidate_tenant_features(world["t"].pk)
    assert owner.get(f"{API}/reports/purchases_by_supplier/", period).status_code in (403, 404)
    columns = owner.get(f"{API}/reports/backorder_demand/").json()["columns"]
    assert not {"on_order", "expected"} & {c["key"] for c in columns}


def test_staff_see_what_is_on_order_for_a_waiting_line_and_shops_dont(world, run):
    owner = world["owner"]
    order = run(
        owner.post,
        f"{API}/purchase-orders/",
        {
            "supplier_id": str(world["supplier"].pk),
            "lines": [{"product_id": str(world["newbie"].pk), "entered_qty": "12"}],
        },
        format="json",
    ).json()
    run(
        owner.post,
        f"{API}/purchase-orders/{order['id']}/send/",
        HTTP_IDEMPOTENCY_KEY=f"k-{uuid4().hex}",
    )
    listed = owner.get(f"{API}/orders/").json()["results"]
    shop_order = owner.get(f"{API}/orders/{listed[0]['id']}/").json()
    [line] = shop_order["lines"]
    assert line["on_order"]["quantity"] == "12.000" and "supplier" not in line["on_order"]
    mine = (
        shop_client(world["t"], world["shop"]).get(f"{API}/shop/orders/{listed[0]['id']}/").json()
    )
    assert "on_order" not in mine["lines"][0]
