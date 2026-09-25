"""Read-side queries for the platform app (tenants, feature flags, plans)."""

from enum import StrEnum
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from apps.platform.models import FeatureFlag, Plan, Subscription, TenantFeature
from common.tenancy import require_tenant_id, tenant_context

FEATURES_CACHE_TTL = 300
_FLAGS_VERSION_KEY = "features:version"


class UnknownFeatureFlag(LookupError):
    """A code path asked for a flag that does not exist (a programming error, not user input)."""


def _flags_version() -> int:
    version = cache.get(_FLAGS_VERSION_KEY)
    if version is None:
        cache.add(_FLAGS_VERSION_KEY, 1, timeout=None)
        version = cache.get(_FLAGS_VERSION_KEY, 1)
    return int(version)


def _features_key(tenant_id: UUID) -> str:
    return f"features:{tenant_id}:v{_flags_version()}"


def invalidate_tenant_features(tenant_id: UUID) -> None:
    """Call after a tenant's flag override changes (use ``transaction.on_commit``)."""
    cache.delete(_features_key(tenant_id))


def invalidate_all_features() -> None:
    """Call after a flag's default changes: every tenant's cached map becomes stale."""
    try:
        cache.incr(_FLAGS_VERSION_KEY)
    except ValueError:
        cache.set(_FLAGS_VERSION_KEY, 2, timeout=None)


def effective_features(tenant_id: UUID | None = None) -> dict[str, bool]:
    """``{flag_code: enabled}`` for the tenant: its override, else the flag's default."""
    tid = tenant_id or require_tenant_id()
    key = _features_key(tid)
    cached: dict[str, bool] | None = cache.get(key)
    if cached is not None:
        return cached
    defaults = dict(FeatureFlag.objects.values_list("code", "default_enabled"))
    # A transaction is required for SET LOCAL: without it RLS would silently return no overrides.
    with transaction.atomic(), tenant_context(tid):
        overrides = dict(
            TenantFeature.objects.filter(tenant_id=tid).values_list("flag__code", "enabled")
        )
    result = {code: overrides.get(code, default) for code, default in defaults.items()}
    cache.set(key, result, FEATURES_CACHE_TTL)
    return result


def is_feature_enabled(code: str, tenant_id: UUID | None = None) -> bool:
    features = effective_features(tenant_id)
    if code not in features:
        raise UnknownFeatureFlag(code)
    return features[code]


def current_plan(tenant_id: UUID | None = None) -> Plan:
    """The tenant's current plan, falling back to the default plan (every tenant gets Beta)."""
    tid = tenant_id or require_tenant_id()
    with transaction.atomic(), tenant_context(tid):
        subscription: Subscription | None = (
            Subscription.objects.filter(tenant_id=tid, is_current=True)
            .select_related("plan")
            .first()
        )
    if subscription is not None:
        return subscription.plan
    return Plan.objects.get(is_default=True)


class PlanResource(StrEnum):
    RETAILERS = "max_retailers"
    STAFF = "max_staff"
    PRODUCTS = "max_products"


def plan_limit_allows(
    resource: PlanResource, current_count: int, tenant_id: UUID | None = None
) -> bool:
    """Whether one more ``resource`` fits the tenant's plan.

    Limits apply only when PLAN_ENFORCEMENT_ENABLED is on for the platform **and** the tenant's
    ``subscriptions_enforcement`` flag is on (spec 5.1: enforcement is off by default).
    """
    tid = tenant_id or require_tenant_id()
    if not settings.PLAN_ENFORCEMENT_ENABLED:
        return True
    if not is_feature_enabled("subscriptions_enforcement", tid):
        return True
    limit: int | None = getattr(current_plan(tid), resource.value)
    return limit is None or current_count < limit
