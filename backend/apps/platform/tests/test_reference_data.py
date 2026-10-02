from decimal import Decimal

import pytest
from django.apps import apps as django_apps

from apps.platform.models import FeatureFlag, Plan, State, TaxRate
from apps.platform.reference_data import FEATURE_FLAGS, STATES, seed_reference_data

pytestmark = pytest.mark.django_db


def test_states_seeded_with_legacy_codes_inactive():
    assert State.objects.count() == len(STATES)
    assert State.objects.get(code="27").name == "Maharashtra"
    assert State.objects.get(code="37").is_active
    assert not State.objects.get(code="25").is_active
    assert not State.objects.get(code="28").is_active
    assert State.objects.get(code="07").is_union_territory


def test_gst_rate_master_matches_adr_008():
    active = set(TaxRate.objects.filter(is_active=True).values_list("rate", flat=True))
    inactive = set(TaxRate.objects.filter(is_active=False).values_list("rate", flat=True))
    assert active == {Decimal(x) for x in ("0", "0.25", "3", "5", "18", "40")}
    assert inactive == {Decimal("12"), Decimal("28")}


def test_default_plan_is_unlimited_free_beta():
    plan = Plan.objects.get(is_default=True)
    assert plan.code == "BETA"
    assert plan.price_monthly == Decimal("0")
    assert (plan.max_retailers, plan.max_staff, plan.max_products) == (None, None, None)


def test_feature_flags_seeded_off_and_not_tenant_toggleable():
    codes = set(FeatureFlag.objects.values_list("code", flat=True))
    assert codes == {code for code, _, _ in FEATURE_FLAGS}
    assert codes == {
        "payments",
        "subscriptions_enforcement",
        "einvoice",
        "ewaybill",
        "whatsapp",
        "batches",
        "multi_warehouse",
        "purchasing",  # ADR-053
        "stock_planning",
        "free_goods",  # ADR-056
        "ai",
    }
    assert not FeatureFlag.objects.filter(default_enabled=True).exists()
    assert not FeatureFlag.objects.filter(tenant_toggleable=True).exists()


def test_seed_is_idempotent_and_keeps_admin_changes():
    FeatureFlag.objects.filter(code="whatsapp").update(tenant_toggleable=True)
    seed_reference_data(django_apps)
    seed_reference_data(django_apps)
    assert State.objects.count() == len(STATES)
    assert TaxRate.objects.count() == 8
    assert Plan.objects.filter(code="BETA").count() == 1
    assert FeatureFlag.objects.get(code="whatsapp").tenant_toggleable
