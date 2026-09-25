import pytest
from django.core.cache import cache
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.platform import selectors
from apps.platform.models import FeatureFlag, Plan, Subscription, TenantFeature
from apps.platform.selectors import PlanResource
from common.tenancy import TenantContextMissing, tenant_context

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _override(tenant, code, enabled):
    with tenant_context(tenant.id):
        TenantFeature.objects.create(flag=FeatureFlag.objects.get(code=code), enabled=enabled)
    selectors.invalidate_tenant_features(tenant.id)


def test_defaults_apply_without_overrides(tenant_a):
    features = selectors.effective_features(tenant_a.id)
    assert set(features) == set(FeatureFlag.objects.values_list("code", flat=True))
    assert not any(features.values())


def test_tenant_override_wins_and_does_not_leak_to_other_tenants(tenant_a, tenant_b):
    _override(tenant_a, "whatsapp", True)
    assert selectors.is_feature_enabled("whatsapp", tenant_a.id) is True
    assert selectors.is_feature_enabled("whatsapp", tenant_b.id) is False


def test_uses_active_tenant_by_default_and_fails_closed_without_one(tenant_a):
    _override(tenant_a, "batches", True)
    with tenant_context(tenant_a.id):
        assert selectors.is_feature_enabled("batches") is True
    with pytest.raises(TenantContextMissing):
        selectors.is_feature_enabled("batches")


def test_unknown_flag_is_a_programming_error(tenant_a):
    with pytest.raises(selectors.UnknownFeatureFlag):
        selectors.is_feature_enabled("teleportation", tenant_a.id)


def test_result_is_cached_and_invalidated(tenant_a):
    selectors.effective_features(tenant_a.id)
    with CaptureQueriesContext(connection) as ctx:
        selectors.is_feature_enabled("ai", tenant_a.id)
    assert len(ctx.captured_queries) == 0

    with tenant_context(tenant_a.id):
        TenantFeature.objects.create(flag=FeatureFlag.objects.get(code="ai"), enabled=True)
    assert selectors.is_feature_enabled("ai", tenant_a.id) is False  # stale until invalidated
    selectors.invalidate_tenant_features(tenant_a.id)
    assert selectors.is_feature_enabled("ai", tenant_a.id) is True


def test_default_change_invalidates_every_tenant(tenant_a, tenant_b):
    assert selectors.is_feature_enabled("payments", tenant_a.id) is False
    assert selectors.is_feature_enabled("payments", tenant_b.id) is False
    FeatureFlag.objects.filter(code="payments").update(default_enabled=True)
    selectors.invalidate_all_features()
    assert selectors.is_feature_enabled("payments", tenant_a.id) is True
    assert selectors.is_feature_enabled("payments", tenant_b.id) is True


def test_overrides_are_read_correctly_under_rls(tenant_a, tenant_b):
    """As the runtime role (RLS enforced) acting for tenant A, reading tenant B's flags must switch
    the DB tenant for the read and restore A afterwards, not silently return B's defaults."""
    _override(tenant_b, "ewaybill", True)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE app_user")
        cursor.execute("SELECT set_config('app.current_tenant', %s, true)", [str(tenant_a.id)])
        assert selectors.is_feature_enabled("ewaybill", tenant_b.id) is True
        cursor.execute("SELECT current_setting('app.current_tenant')")
        assert cursor.fetchone()[0] == str(tenant_a.id)
        cursor.execute("RESET ROLE")


def test_current_plan_defaults_to_beta(tenant_a):
    assert selectors.current_plan(tenant_a.id).code == "BETA"


def test_current_plan_uses_current_subscription(tenant_a):
    pro = Plan.objects.create(code="PRO", name="Pro", max_staff=2)
    beta = Plan.objects.get(code="BETA")

    with tenant_context(tenant_a.id):
        Subscription.objects.create(plan=beta, starts_at=timezone.now(), is_current=False)
        Subscription.objects.create(plan=pro, starts_at=timezone.now())
    assert selectors.current_plan(tenant_a.id) == pro


@pytest.fixture
def limited_plan(tenant_a):

    plan = Plan.objects.create(code="SMALL", name="Small", max_staff=2)
    with tenant_context(tenant_a.id):
        Subscription.objects.create(plan=plan, starts_at=timezone.now())
    return plan


def test_plan_limits_not_enforced_by_default(settings, tenant_a, limited_plan):
    assert settings.PLAN_ENFORCEMENT_ENABLED is False
    assert selectors.plan_limit_allows(PlanResource.STAFF, 50, tenant_a.id)


def test_plan_limits_need_platform_switch_and_tenant_flag(settings, tenant_a, limited_plan):
    settings.PLAN_ENFORCEMENT_ENABLED = True
    assert selectors.plan_limit_allows(PlanResource.STAFF, 50, tenant_a.id)  # flag still off
    _override(tenant_a, "subscriptions_enforcement", True)
    assert selectors.plan_limit_allows(PlanResource.STAFF, 1, tenant_a.id)
    assert not selectors.plan_limit_allows(PlanResource.STAFF, 2, tenant_a.id)
    assert selectors.plan_limit_allows(PlanResource.RETAILERS, 10_000, tenant_a.id)  # unlimited
