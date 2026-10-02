"""AI use this month (ADR-058 item 2): a distributor sees only its own; the super admin sees each
distributor's on the audited path; shops and other roles can't reach the platform view."""

from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_super_admin
from apps.accounts.tokens import issue_tokens
from apps.ai.models import AiUsage
from apps.ai.tests.test_semantic_search import switch
from apps.orders.tests.helpers import make_shop, shop_client, staff_client
from apps.platform.services import set_platform_settings
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"


def used(tenant: Any, feature: str, units_in: int, units_out: int = 0, ok: bool = True) -> None:
    with tenant_context(tenant.pk):
        AiUsage.objects.create(
            feature=feature, provider="mock", units_in=units_in, units_out=units_out, ok=ok
        )


@pytest.fixture
def admin_client(db):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(make_super_admin(), None).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = "admin.localhost"
    return client


@pytest.fixture
def world(tenant_a, tenant_b):
    cache.clear()
    switch(tenant_a)
    used(tenant_a, "SEARCH_INDEX", 900)
    used(tenant_a, "SEARCH_QUERY", 40)
    used(tenant_a, "SEARCH_QUERY", 0, ok=False)
    used(tenant_b, "ASSISTANT", 5_000, 700)
    return {"a": tenant_a, "b": tenant_b}


@covers("settings-ai-usage")
def test_a_distributor_sees_only_its_own_use(world):
    set_platform_settings({"platform.ai_monthly_units": 1_000}, user=None)
    cache.clear()
    body = staff_client(world["a"], "SALES").get(f"{API}/settings/ai-usage/").json()
    assert (body["enabled"], body["units"], body["limit"]) == (True, 940, 1_000)
    assert (body["calls"], body["failed"], body["near_limit"]) == (3, 1, True)
    assert [(f["feature"], f["units"], f["calls"]) for f in body["by_feature"]] == [
        ("SEARCH_INDEX", 900, 1),
        ("SEARCH_QUERY", 40, 2),
    ]
    other = staff_client(world["b"]).get(f"{API}/settings/ai-usage/").json()
    assert (other["enabled"], other["units"], other["calls"]) == (False, 5_700, 1)
    assert [f["feature"] for f in other["by_feature"]] == ["ASSISTANT"]


def test_no_limit_and_no_use(tenant_a):
    set_platform_settings({"platform.ai_monthly_units": 0}, user=None)
    cache.clear()
    body = staff_client(tenant_a).get(f"{API}/settings/ai-usage/").json()
    assert (body["units"], body["limit"], body["near_limit"], body["by_feature"]) == (
        0,
        None,
        False,
        [],
    )


@covers("platform-ai-usage")
def test_the_super_admin_sees_each_distributors_use(world, admin_client):
    response = admin_client.get(f"{API}/platform/ai-usage/")
    assert response.status_code == 200, response.json()
    rows = [(r["name"], r["units"], r["calls"], r["failed"]) for r in response.json()]
    assert rows == [("Bravo", 5_700, 1, 0), ("Alpha", 940, 3, 1)]  # the heaviest first
    assert staff_client(world["a"]).get(f"{API}/platform/ai-usage/").status_code == 403
    shop = shop_client(world["a"], make_shop(world["a"], "9876500151"))
    assert shop.get(f"{API}/platform/ai-usage/").status_code == 403
    assert shop.get(f"{API}/settings/ai-usage/").status_code == 403
