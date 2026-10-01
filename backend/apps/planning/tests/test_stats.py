"""Product stats (ADR-053 item 3): demand from what shops ordered (without rejected orders or the
shop's own cancellations), days of stock, ABC classes by share of sales value, and the same fast /
slow / dead / new classes as the Phase 8 report; nightly for distributors with stock planning on,
or when staff ask (once every five minutes)."""

from datetime import timedelta
from decimal import Decimal as D
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.tests.factories import make_staff_in
from apps.billing.tests.helpers import ship_invoice
from apps.catalog.models import Product
from apps.compliance.tests.conftest import switch_on
from apps.inventory.selectors import with_stock
from apps.inventory.tests.helpers import make_product
from apps.orders import transitions
from apps.orders.models import Order
from apps.orders.tests.helpers import add_stock, client_for, make_shop, place, settings, shop_user
from apps.planning import services
from apps.planning.models import ProductStats
from apps.planning.tasks import refresh_all
from apps.reports.definitions.stock import movement_class_rows
from apps.reports.registry import Context, Scope
from common.dates import today_ist
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"


def test_abc_classes_by_share_of_sales_value():
    p = [uuid4() for _ in range(6)]
    values = {
        p[0]: D("700"),
        p[1]: D("200"),
        p[2]: D("60"),
        p[3]: D("40"),
        p[4]: D("0"),
        p[5]: D("-5"),
    }
    classes = services.abc_classes(values, 80, 95)
    # Above the first: nothing; above the second: 70%; the third: 90%; the fourth: 96%.
    assert [classes.get(pk) for pk in p] == ["A", "A", "B", "C", None, None]
    assert services.abc_classes({p[0]: D("10")}, 80, 95) == {p[0]: "A"}
    assert services.abc_classes({}, 80, 95) == {}


@pytest.fixture
def world(tenant_a, tenant_b):
    switch_on(tenant_a, "stock_planning")
    owner = make_staff_in(tenant_a, "OWNER")
    tea = make_product(tenant_a, "TEA", base_price=D("100"))
    soap = make_product(tenant_a, "SOAP", base_price=D("10"))
    add_stock(tenant_a, tea, "100")
    add_stock(tenant_a, soap, "20")
    shop = make_shop(tenant_a, "9876500101")
    return {"t": tenant_a, "b": tenant_b, "owner": owner, "tea": tea, "soap": soap, "shop": shop}


def _placed_days_ago(tenant: Any, order: Order, days: int) -> None:
    with tenant_context(tenant.pk):
        Order.objects.filter(pk=order.pk).update(placed_at=timezone.now() - timedelta(days=days))


def _stats(tenant: Any, product: Any) -> ProductStats:
    with tenant_context(tenant.pk):
        stats: ProductStats = ProductStats.objects.get(product=product)
        return stats


def _refresh(tenant: Any) -> int:
    with tenant_context(tenant.pk):
        return services.refresh_stats()


def test_demand_is_what_shops_ordered(world):
    t, tea, shop, owner = world["t"], world["tea"], world["shop"], world["owner"]
    place(t, shop, (tea, "4"))  # waiting today
    _placed_days_ago(t, ship_invoice(t, shop, owner, (tea, "6")).order, 10)
    with tenant_context(t.pk):
        rejected = place(t, shop, (tea, "3"))
        transitions.reject_order(rejected.pk, reason="No credit", by=owner)
        mine = place(t, shop, (tea, "2"))
        transitions.cancel_order(mine.pk, by=shop_user(shop), retailer_id=shop.pk)
        theirs = place(t, shop, (tea, "5"))
        transitions.cancel_order(theirs.pk, by=owner, reason="Out of stock")  # still wanted
    _placed_days_ago(t, place(t, shop, (tea, "40")), 31)  # before the 30 days

    assert _refresh(t) == 2
    stats = _stats(t, tea)
    assert (stats.demand_days, stats.demand_qty, stats.per_day) == (30, D("15"), D("0.500"))
    with tenant_context(t.pk):
        listed: Any = with_stock(Product.objects.filter(pk=tea.pk))
        available = listed.get().available
    assert stats.available == available
    assert stats.days_of_stock == (available / D("0.5")).quantize(D("0.1"))
    soap = _stats(t, world["soap"])
    assert (soap.demand_qty, soap.per_day, soap.days_of_stock) == (D("0"), D("0"), None)

    settings(t, planning__demand_days=7)
    _refresh(t)
    stats = _stats(t, tea)
    assert (stats.demand_days, stats.demand_qty) == (7, D("9"))  # today's 4 and the cancelled 5


def test_classes_match_the_fast_slow_dead_and_new_report(world, monkeypatch):
    """Ten days on, with a 7-day period: six products sold in it (fast or slow), one first stocked
    in it (new), the rest stocked before it and unsold (dead), one never stocked (no class)."""
    t, owner, shop = world["t"], world["owner"], world["shop"]
    settings(t, reports__movement_days=7)
    later = today_ist() + timedelta(days=10)
    products = [world["tea"], world["soap"]]
    for n in range(6):
        product = make_product(t, f"P{n}", base_price=D(10 * (n + 1)))
        add_stock(t, product, "50")
        products.append(product)
    monkeypatch.setattr("apps.billing.invoicing.today_ist", lambda: later - timedelta(days=1))
    for product in products[:6]:
        ship_invoice(t, shop, owner, (product, "1"))
    new = make_product(t, "NEW")
    moment = timezone.now() + timedelta(days=8)
    with monkeypatch.context() as m:
        m.setattr("django.utils.timezone.now", lambda: moment)
        add_stock(t, new, "5")
    never = make_product(t, "NEVER")
    monkeypatch.setattr("apps.reports.definitions.stock.today_ist", lambda: later)
    with tenant_context(t.pk):
        services.refresh_stats(today=later)
        report = {
            row["product_id"]: row["class"].upper()
            for row in movement_class_rows(
                Context({}, Scope(owner.pk, own_shops=False, costs=False))
            )
        }
        stats = dict(ProductStats.objects.values_list("product_id", "movement_class"))
        abc = dict(ProductStats.objects.values_list("product_id", "abc_class"))
    assert {pk: c for pk, c in stats.items() if c} == report
    assert {stats[p.pk] for p in products[:6]} == {"FAST", "SLOW"}
    assert {stats[p.pk] for p in products[6:]} == {"DEAD"}
    assert (stats[new.pk], stats[never.pk]) == ("NEW", None)
    # Sold ₹100 (tea), 40, 30, 20, 10, 10 of ₹210: A while those above make under 80%, B under 95%.
    assert abc[world["tea"].pk] == "A"
    assert sorted(abc[p.pk] for p in products[:6]) == ["A", "A", "A", "B", "B", "C"]
    assert abc[new.pk] is None


def test_figures_are_replaced_and_deleted_products_lose_them(world):
    t = world["t"]
    _refresh(t)
    first = _stats(t, world["tea"]).computed_at
    with tenant_context(t.pk):
        Product.objects.filter(pk=world["soap"].pk).update(deleted_at=timezone.now())
    _refresh(t)
    with tenant_context(t.pk):
        assert ProductStats.objects.count() == 1
    assert _stats(t, world["tea"]).computed_at > first


def test_the_nightly_job_covers_distributors_with_stock_planning(world):
    tea_b = make_product(world["b"], "TEA")
    add_stock(world["b"], tea_b, "5")
    assert refresh_all() == 2  # every distributor that isn't suspended
    with tenant_context(world["t"].pk):
        assert ProductStats.objects.count() == 2
    with tenant_context(world["b"].pk):
        assert not ProductStats.objects.exists()  # stock planning is off there


# --- API --------------------------------------------------------------------------------------


@covers("product-stats")
def test_a_products_figures(world):
    t, tea = world["t"], world["tea"]
    owner = client_for(t, world["owner"])
    url = f"{API}/products/{tea.pk}/stats/"
    assert owner.get(url).status_code == 204  # not worked out yet
    _refresh(t)
    body = owner.get(url).json()
    assert body["demand_days"] == 30 and body["movement_class"] == "NEW"  # stocked today
    assert not {k for k in body if "value" in k or "cost" in k}  # no money
    assert client_for(t, make_staff_in(t, "WAREHOUSE")).get(url).status_code == 200
    other = client_for(world["b"], make_staff_in(world["b"], "OWNER"))
    switch_on(world["b"], "stock_planning")
    assert other.get(url).status_code == 404
    from apps.orders.tests.helpers import shop_client

    assert shop_client(t, world["shop"]).get(url).status_code == 403


def test_stock_planning_switched_off(world):
    b = world["b"]
    product = make_product(b, "TEA")
    owner = client_for(b, make_staff_in(b, "OWNER"))
    refused = owner.get(f"{API}/products/{product.pk}/stats/")
    assert (refused.status_code, refused.json()["error"]["code"]) == (403, "MODULE_NOT_ENABLED")
    refused = owner.post(f"{API}/planning/stats/refresh/")
    assert (refused.status_code, refused.json()["error"]["code"]) == (403, "MODULE_NOT_ENABLED")


@covers("planning-stats-refresh")
def test_staff_can_ask_for_fresh_figures_once_every_few_minutes(
    world, django_capture_on_commit_callbacks
):
    cache.clear()
    t = world["t"]
    owner = client_for(t, world["owner"])
    with django_capture_on_commit_callbacks(execute=True):
        response = owner.post(f"{API}/planning/stats/refresh/")
    assert (response.status_code, response.json()) == (202, {"status": "QUEUED"})
    with tenant_context(t.pk):
        assert ProductStats.objects.count() == 2
    again = owner.post(f"{API}/planning/stats/refresh/")
    assert (again.status_code, again.json()["error"]["code"]) == (429, "RATE_LIMITED")
    warehouse = client_for(t, make_staff_in(t, "WAREHOUSE"))  # purchasing.view only
    assert warehouse.post(f"{API}/planning/stats/refresh/").status_code == 403
    # Another distributor's refresh works on its own products only.
    switch_on(world["b"], "stock_planning")
    make_product(world["b"], "TEA")
    other = client_for(world["b"], make_staff_in(world["b"], "OWNER"))
    with django_capture_on_commit_callbacks(execute=True):
        assert other.post(f"{API}/planning/stats/refresh/").status_code == 202
    with tenant_context(world["b"].pk):
        assert ProductStats.objects.count() == 1
    with tenant_context(t.pk):
        assert ProductStats.objects.count() == 2


def test_the_settings_and_class_b_above_class_a(world):
    from apps.platform import registry
    from apps.platform.services import SettingsInvalid, set_tenant_settings

    defaults = {
        k: registry.REGISTRY[k].default for k in registry.REGISTRY if k.startswith("planning.")
    }
    assert defaults == {
        "planning.demand_days": 30,
        "planning.safety_days": 7,
        "planning.cover_days": 14,
        "planning.default_lead_days": 7,
        "planning.abc_a_percent": 80,
        "planning.abc_b_percent": 95,
    }
    assert all(registry.REGISTRY[k].features == ("stock_planning",) for k in defaults)
    with tenant_context(world["t"].pk):
        with pytest.raises(SettingsInvalid) as refused:
            set_tenant_settings({"planning.abc_a_percent": 95}, user=None)
        assert list(refused.value.details["fields"]) == ["planning.abc_a_percent"]
        with pytest.raises(SettingsInvalid) as refused:
            set_tenant_settings({"planning.abc_b_percent": 70}, user=None)
        assert list(refused.value.details["fields"]) == ["planning.abc_b_percent"]
        set_tenant_settings({"planning.abc_a_percent": 70, "planning.abc_b_percent": 90}, user=None)
