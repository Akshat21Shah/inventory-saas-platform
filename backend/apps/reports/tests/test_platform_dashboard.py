"""The super admin's dashboard (ADR-050 item 12): orders per day and the top distributors,
failures per distributor, usage against plans, and the error rate; for the super admin only."""

from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in, make_super_admin
from apps.accounts.tokens import issue_tokens
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_stock, client_for, make_shop, place
from apps.payments.models import GatewayConfig
from apps.platform.models import Plan, Subscription
from common import metrics
from common.dates import today_ist
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
P = "/api/v1/platform"


@pytest.fixture
def api():
    client = APIClient()
    admin = make_super_admin("root@platform.example.com")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(admin, None).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = "admin.localhost"
    return client


@pytest.fixture
def world(tenant_a, tenant_b):
    cache.clear()
    product = make_product(tenant_a, base_price=D("100"))
    add_stock(tenant_a, product, "10")
    place(tenant_a, make_shop(tenant_a), (product, "2"))  # ₹210
    small = Plan.objects.create(code="small", name="Small", max_retailers=1, max_staff=50)
    with tenant_context(tenant_a.pk):
        Subscription.objects.filter(is_current=True).update(is_current=False)
        Subscription.objects.create(plan=small, starts_at=timezone.now())
    with tenant_context(tenant_b.pk):
        GatewayConfig.objects.create(provider="MOCK", status=GatewayConfig.Status.FAILED)
    return {"a": tenant_a, "b": tenant_b}


def test_platform_health_across_distributors(api, world):
    body = api.get(f"{P}/dashboard/").json()
    assert body["total"] >= 2  # the tenant counts stay
    today = next(d for d in body["orders_per_day"] if d["date"] == today_ist().isoformat())
    assert (today["count"], today["value"]) == (1, "210.00")
    assert len(body["orders_per_day"]) == 30
    assert [(t["name"], t["orders"]) for t in body["top_tenants"]] == [(world["a"].name, 1)]
    [failing] = body["failures"]
    assert (failing["name"], failing["gateway_failed"], failing["failed_messages"]) == (
        world["b"].name,
        True,
        0,
    )
    usage = {u["name"]: u for u in body["usage"]}
    alpha = usage[world["a"].name]
    assert (alpha["plan"], alpha["shops"], alpha["max_shops"], alpha["near_limit"]) == (
        "Small",
        1,
        1,
        True,
    )
    assert body["usage"][0]["name"] == world["a"].name  # near a limit first


def test_the_error_rate_counts_server_errors_not_health_checks(api, world):
    cache.clear()
    for status in (200, 200, 404, 500):
        metrics.record("/api/v1/orders/", status)
    metrics.record("/health/ready", 500)
    rate = api.get(f"{P}/dashboard/").json()["errors_24h"]
    # The dashboard request is counted once it has answered, so not in its own figures.
    assert (rate["requests"], rate["server_errors"], rate["rate"]) == (4, 1, "25.00")


def test_only_the_super_admin(world):
    owner = client_for(world["a"], make_staff_in(world["a"], "OWNER"))
    assert owner.get(f"{P}/dashboard/").status_code in (403, 404)


def test_the_error_rate_covers_the_last_24_hours_only(monkeypatch):
    cache.clear()
    now = timezone.now()
    monkeypatch.setattr("django.utils.timezone.now", lambda: now - timedelta(hours=25))
    metrics.record("/api/v1/orders/", 500)
    monkeypatch.setattr("django.utils.timezone.now", lambda: now - timedelta(hours=23))
    metrics.record("/api/v1/orders/", 200)
    monkeypatch.setattr("django.utils.timezone.now", lambda: now)
    assert metrics.last_hours(24) == {"requests": 1, "errors": 0}


def test_counting_never_breaks_a_request(monkeypatch):
    def broken(*args, **kwargs):
        raise ConnectionError("cache down")

    monkeypatch.setattr(cache, "incr", broken)
    monkeypatch.setattr(cache, "get_many", broken)
    metrics.record("/api/v1/orders/", 500)
    assert metrics.last_hours(24) == {"requests": 0, "errors": 0}
