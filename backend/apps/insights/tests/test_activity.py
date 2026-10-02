"""Shop activity and win-back (ADR-056 items 1-4): the figures and segments, what counts as an
order, the win-back list and contacts, the dashboard tile and the report, sales visibility, and
isolation."""

from datetime import datetime, time, timedelta
from decimal import Decimal as D
from typing import Any

import pytest
from django.core.cache import cache

from apps.accounts.tests.factories import make_staff_in
from apps.insights import services
from apps.insights.api.serializers import ShopActivitySerializer
from apps.insights.models import Segment, ShopActivity
from apps.inventory.tests.helpers import make_product
from apps.orders.models import Order, OrderStatus
from apps.orders.tests.helpers import add_stock, client_for, make_shop, place, settings
from apps.retailers.models import Retailer
from common.dates import IST, today_ist
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"


def at(days_ago: int) -> datetime:
    return datetime.combine(today_ist() - timedelta(days=days_ago), time(11), tzinfo=IST)


def orders(tenant: Any, shop: Retailer, product: Any, *days_ago: int) -> list[Order]:
    placed = []
    for days in days_ago:
        order = place(tenant, shop, (product, "1"))
        with tenant_context(tenant.pk):
            Order.objects.filter(pk=order.pk).update(placed_at=at(days))
        placed.append(order)
    return placed


@pytest.fixture
def world(tenant_a, tenant_b):
    cache.clear()
    owner = make_staff_in(tenant_a, "OWNER")
    sales = make_staff_in(tenant_a, "SALES")
    product = make_product(tenant_a, "P-1", base_price=D("100"))
    add_stock(tenant_a, product, "1000")
    shops = {
        "regular": make_shop(tenant_a, "9876500061", shop_name="Regular Mart"),
        "slowing": make_shop(tenant_a, "9876500062", shop_name="Slowing Stores"),
        "halved": make_shop(tenant_a, "9876500063", shop_name="Halved Kirana"),
        "dormant": make_shop(tenant_a, "9876500064", shop_name="Dormant Traders"),
        "newbie": make_shop(tenant_a, "9876500065", shop_name="Newbie Shop"),
        "never": make_shop(tenant_a, "9876500066", shop_name="Never Ordered"),
    }
    orders(tenant_a, shops["regular"], product, 3, 10, 17, 24, 31, 38, 45, 52, 59, 66)
    orders(tenant_a, shops["slowing"], product, 20, 27, 34, 41, 48)
    # Six orders in the 90 days before, two in the last 90 (the last 8 days ago).
    orders(tenant_a, shops["halved"], product, 8, 40, 100, 110, 120, 130, 140, 150)
    orders(tenant_a, shops["dormant"], product, 60, 67, 74)
    orders(tenant_a, shops["newbie"], product, 5)
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shops["never"].pk).update(created_at=at(30))
        Retailer.objects.filter(pk__in=[shops["dormant"].pk, shops["slowing"].pk]).update(
            salesperson=sales
        )
    return {
        "t": tenant_a,
        "b": tenant_b,
        "owner_user": owner,
        "owner": client_for(tenant_a, owner),
        "sales": client_for(tenant_a, sales),
        "warehouse": client_for(tenant_a, make_staff_in(tenant_a, "WAREHOUSE")),
        "other": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
        "shops": shops,
        "product": product,
    }


def refresh(world: dict[str, Any]) -> dict[str, ShopActivity]:
    with tenant_context(world["t"].pk):
        services.refresh_activity()
        return {
            row.retailer.shop_name: row for row in ShopActivity.objects.select_related("retailer")
        }


def test_figures_and_segments(world):
    found = refresh(world)
    segments = {name: row.segment for name, row in found.items()}
    assert segments == {
        "Regular Mart": Segment.ACTIVE,
        "Slowing Stores": Segment.SLOWING,  # usually every 7 days, 20 days since
        "Halved Kirana": Segment.SLOWING,  # 2 orders in 90 days against 6 before
        "Dormant Traders": Segment.DORMANT,  # 60 days
        "Newbie Shop": Segment.NEW,
        "Never Ordered": Segment.NEVER_ORDERED,  # added 30 days ago
    }
    regular = found["Regular Mart"]
    assert (regular.usual_gap_days, regular.days_since_last, regular.orders_90) == (
        D("7.0"),
        3,
        10,
    )
    assert regular.value_90 == regular.orders_90 * D("105.00")  # 1 x 100 + 5% GST each
    halved = found["Halved Kirana"]
    assert (halved.orders_90, halved.orders_prev_90) == (2, 6)
    assert found["Never Ordered"].last_order_date is None
    # Most urgent first: stopped ordering, then slowing (the longer wait first), never ordered.
    order = sorted(found.values(), key=lambda r: -r.urgency)
    assert [r.retailer.shop_name for r in order[:4]] == [
        "Dormant Traders",
        "Slowing Stores",
        "Halved Kirana",
        "Never Ordered",
    ]


def test_rejected_and_shop_cancelled_orders_dont_count(world):
    t = world["t"]
    [rejected, cancelled] = orders(t, world["shops"]["never"], world["product"], 2, 3)
    with tenant_context(t.pk):
        Order.objects.filter(pk=rejected.pk).update(status=OrderStatus.REJECTED)
        shop_login = world["shops"]["never"].logins.first().user
        Order.objects.filter(pk=cancelled.pk).update(
            status=OrderStatus.CANCELLED, cancelled_by=shop_login
        )
    assert refresh(world)["Never Ordered"].segment == Segment.NEVER_ORDERED


@pytest.mark.parametrize(
    ("since", "gap", "o90", "oprev", "expected"),
    [
        (10, D("7"), 5, 5, Segment.ACTIVE),  # 10 <= 150% of 7
        (11, D("7"), 5, 5, Segment.SLOWING),  # 11 > 10.5
        (6, D("2"), 5, 5, Segment.ACTIVE),  # under 7 days is never slowing by the gap
        (45, D("7"), 0, 5, Segment.DORMANT),
        (5, None, 1, 4, Segment.SLOWING),  # halved
        (5, None, 1, 2, Segment.ACTIVE),  # too few before to judge
    ],
)
def test_segment_rules(since, gap, o90, oprev, expected):
    today = today_ist()
    limits = services.Thresholds(new_days=30, dormant_days=45, slowing_percent=150)
    assert (
        services.segment_of(
            today=today,
            added=today - timedelta(days=400),
            first=today - timedelta(days=300),
            last=today - timedelta(days=since),
            gap=gap,
            orders_90=o90,
            orders_prev_90=oprev,
            limits=limits,
        )
        == expected
    )


def test_usual_gap_needs_three_orders_and_uses_the_last_ten():
    today = today_ist()
    assert services.usual_gap([today, today - timedelta(days=5)]) is None
    dates = [today - timedelta(days=d) for d in (0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 200, 400)]
    assert services.usual_gap(dates) == D("2.0")  # the two oldest are beyond the last ten


@covers("shop-activity", "retailer-contacts", "retailer-activity")
def test_win_back_list_contacts_and_the_dashboard(world):
    refresh(world)
    owner = world["owner"]
    listed = owner.get(f"{API}/shop-activity/", {"win_back": "true"}).json()["results"]
    assert [r["shop_name"] for r in listed] == [
        "Dormant Traders",
        "Slowing Stores",
        "Halved Kirana",
        "Never Ordered",
    ]
    first = listed[0]
    # Its last orders were 60-74 days ago: still inside the last 90 days.
    assert (first["segment"], first["salesperson_name"] is not None, first["value_90"]) == (
        "DORMANT",
        True,
        "315.00",
    )
    assert owner.get(f"{API}/dashboard/").json()["action"]["win_back"] == 4
    dormant = world["shops"]["dormant"].pk
    logged = owner.post(
        f"{API}/retailers/{dormant}/contacts/",
        {"channel": "CALL", "outcome": "WILL_ORDER", "note": "Will order on Monday"},
        format="json",
    )
    assert logged.status_code == 201 and logged.json()["outcome"] == "WILL_ORDER"
    after = owner.get(f"{API}/shop-activity/", {"win_back": "true"}).json()["results"]
    assert "Dormant Traders" not in [r["shop_name"] for r in after]  # contacted: snoozed
    assert owner.get(f"{API}/dashboard/").json()["action"]["win_back"] == 3
    detail = owner.get(f"{API}/retailers/{dormant}/activity/").json()
    assert detail["activity"]["last_contact_outcome"] == "WILL_ORDER"
    assert [c["note"] for c in detail["contacts"]] == ["Will order on Monday"]
    refused = owner.post(
        f"{API}/retailers/{dormant}/contacts/", {"channel": "PIGEON"}, format="json"
    )
    assert refused.status_code == 400
    # Segment filter and search.
    slowing = owner.get(f"{API}/shop-activity/", {"segment": "SLOWING"}).json()["results"]
    assert {r["shop_name"] for r in slowing} == {"Slowing Stores", "Halved Kirana"}
    assert [
        r["shop_name"]
        for r in owner.get(f"{API}/shop-activity/", {"search": "newbie"}).json()["results"]
    ] == ["Newbie Shop"]
    # Another distributor sees none of it.
    other = world["other"]
    assert other.get(f"{API}/shop-activity/").json()["results"] == []
    assert other.get(f"{API}/retailers/{dormant}/activity/").status_code == 404
    assert (
        other.post(
            f"{API}/retailers/{dormant}/contacts/",
            {"channel": "CALL", "outcome": "REACHED"},
            format="json",
        ).status_code
        == 404
    )
    assert world["warehouse"].get(f"{API}/shop-activity/").status_code == 403


def test_sales_staff_limited_to_their_shops_see_only_those(world):
    refresh(world)
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    names = {r["shop_name"] for r in world["sales"].get(f"{API}/shop-activity/").json()["results"]}
    assert names == {"Dormant Traders", "Slowing Stores"}
    regular = world["shops"]["regular"].pk
    assert world["sales"].get(f"{API}/retailers/{regular}/activity/").status_code == 404


def test_values_need_a_sales_report_permission(world):
    found = refresh(world)["Regular Mart"]
    hidden = ShopActivitySerializer(found, context={"values": False}).data
    shown = ShopActivitySerializer(found, context={"values": True}).data
    assert (hidden["value_90"], shown["value_90"]) == (None, "1050.00")


@covers("shop-activity-refresh")
def test_refresh_now_is_rate_limited(world, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        first = world["owner"].post(f"{API}/shop-activity/refresh/")
    assert first.status_code == 202
    with tenant_context(world["t"].pk):
        assert ShopActivity.objects.count() == 6
    assert world["owner"].post(f"{API}/shop-activity/refresh/").status_code == 429
    assert world["other"].post(f"{API}/shop-activity/refresh/").status_code == 202
    with tenant_context(world["b"].pk):
        assert ShopActivity.objects.count() == 0  # its own (no shops), never tenant A's


def test_the_shop_activity_report(world):
    refresh(world)
    rows = (
        world["owner"].get(f"{API}/reports/shop_activity/", {"segment": "DORMANT"}).json()["rows"]
    )
    assert [(r["name"], r["segment"], r["days_since"]) for r in rows] == [
        ("Dormant Traders", "Stopped ordering", 60)
    ]
