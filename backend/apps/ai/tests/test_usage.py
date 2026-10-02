"""AI use this month (ADR-058 item 2, ADR-059 item 8): in estimated rupees, questions and
searches, against the cap as questions, searches and rupees; a distributor sees only its own;
the super admin sees each distributor's on the audited path; shops and other roles can't reach
the platform view."""

from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in, make_super_admin
from apps.accounts.tokens import issue_tokens
from apps.ai import pricing
from apps.ai.models import AiUsage, AssistantQuestion
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
    asker = make_staff_in(tenant_b, "OWNER")
    with tenant_context(tenant_b.pk):
        for text in ("Sales today?", "Top shops?"):
            AssistantQuestion.objects.create(user=asker, question=text)
    # ₹1,000 per million search units (₹0.001 each) keeps the figures readable.
    set_platform_settings({"platform.ai_embeddings_price": "1000.00"}, user=None)
    cache.clear()
    return {"a": tenant_a, "b": tenant_b}


@covers("settings-ai-usage")
def test_a_distributor_sees_only_its_own_use_in_rupees_questions_and_searches(world):
    body = staff_client(world["a"], "SALES").get(f"{API}/settings/ai-usage/").json()
    assert (body["enabled"], body["cost"], body["questions"], body["searches"]) == (
        True,
        "0.94",
        0,
        1,  # the failed search isn't one
    )
    assert (body["units"], body["calls"], body["failed"], body["model"]) == (
        940,
        3,
        1,
        "claude-sonnet-5-5",
    )
    assert [(f["feature"], f["cost"], f["calls"]) for f in body["by_feature"]] == [
        ("SEARCH_INDEX", "0.90", 1),
        ("SEARCH_QUERY", "0.04", 2),
    ]
    other = staff_client(world["b"]).get(f"{API}/settings/ai-usage/").json()
    # 5,000 units in at ₹265 a million and 700 out at ₹1,325 a million.
    assert (other["enabled"], other["cost"], other["questions"], other["searches"]) == (
        False,
        "2.25",
        2,
        0,
    )
    assert [f["feature"] for f in other["by_feature"]] == ["ASSISTANT"]


def test_the_cap_reads_as_questions_searches_and_rupees(tenant_a):
    set_platform_settings({"platform.ai_monthly_units": 2_000_000}, user=None)
    cache.clear()
    body = staff_client(tenant_a).get(f"{API}/settings/ai-usage/").json()
    # A typical question is 5,700 units in and 300 out (₹1.908 at the Sonnet prices); a search
    # 20 units. 2,000,000 units: 333 questions or 100,000 searches, at most ₹636.
    assert body["allowance"] == {"questions": 333, "searches": 100_000, "cost": "636.00"}
    assert (body["limit"], body["near_limit"]) == (2_000_000, False)
    set_platform_settings({"platform.ai_assistant_model": "claude-haiku-4-5-20251001"}, user=None)
    cache.clear()
    body = staff_client(tenant_a).get(f"{API}/settings/ai-usage/").json()
    # Haiku: ₹88 and ₹440 a million → ₹0.6336 a question → at most ₹211.20.
    assert (body["model"], body["allowance"]["cost"]) == ("claude-haiku-4-5-20251001", "211.20")


def test_near_the_limit_no_limit_and_no_use(world, tenant_b):
    set_platform_settings({"platform.ai_monthly_units": 1_000}, user=None)
    cache.clear()
    body = staff_client(world["a"]).get(f"{API}/settings/ai-usage/").json()
    assert body["near_limit"] is True  # 940 of 1,000 units
    set_platform_settings({"platform.ai_monthly_units": 0}, user=None)
    cache.clear()
    body = staff_client(world["a"]).get(f"{API}/settings/ai-usage/").json()
    assert (body["limit"], body["allowance"], body["near_limit"]) == (None, None, False)


def test_prices_follow_the_model_and_the_feature(db):
    cache.clear()
    p = pricing.prices("claude-sonnet-5-5")
    assert p.cost("ASSISTANT", 1_000_000, 0) == 265
    assert p.cost("ASSISTANT", 0, 1_000_000) == 1325
    assert p.cost("SEARCH_QUERY", 1_000_000, 0) == 2
    haiku = pricing.prices("claude-haiku-4-5-20251001")
    assert haiku.cost("ASSISTANT", 1_000_000, 1_000_000) == 528
    assert pricing.allowance(None, p) is None


@covers("platform-ai-usage")
def test_the_super_admin_sees_each_distributors_use(world, admin_client):
    response = admin_client.get(f"{API}/platform/ai-usage/")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert (body["model"], body["limit"]) == ("claude-sonnet-5-5", 2_000_000)
    assert body["allowance"]["questions"] == 333
    rows = [
        (r["name"], r["cost"], r["questions"], r["searches"], r["failed"]) for r in body["rows"]
    ]
    assert rows == [("Bravo", "2.25", 2, 0, 0), ("Alpha", "0.94", 0, 1, 1)]  # the dearest first
    assert staff_client(world["a"]).get(f"{API}/platform/ai-usage/").status_code == 403
    shop = shop_client(world["a"], make_shop(world["a"], "9876500151"))
    assert shop.get(f"{API}/platform/ai-usage/").status_code == 403
    assert shop.get(f"{API}/settings/ai-usage/").status_code == 403
