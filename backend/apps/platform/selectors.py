"""Read-side queries for the platform app (tenants, feature flags, plans, settings)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from apps.platform import registry
from apps.platform.models import (
    FeatureFlag,
    Plan,
    PlatformSetting,
    Subscription,
    Tenant,
    TenantFeature,
    TenantSetting,
)
from apps.platform.registry import Scope, SnapshotOn
from common.tenancy import require_tenant_id, tenant_context

FEATURES_CACHE_TTL = 300


# --- Tenants ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TenantInfo:
    id: UUID
    slug: str
    name: str
    status: str

    @property
    def is_active(self) -> bool:
        return self.status == Tenant.Status.ACTIVE


def _tenant_info_key(tenant_id: UUID) -> str:
    return f"tenant:info:{tenant_id}"


def tenant_info(tenant_id: UUID) -> TenantInfo | None:
    """Slug and status of a tenant, cached briefly: checked on every authenticated request so a
    suspension takes effect at once (the status-changing service invalidates this entry)."""
    key = _tenant_info_key(tenant_id)
    cached: TenantInfo | None = cache.get(key)
    if cached is not None:
        return cached
    row = Tenant.objects.filter(pk=tenant_id).values_list("slug", "name", "status").first()
    if row is None:
        return None
    info = TenantInfo(id=tenant_id, slug=row[0], name=row[1], status=row[2])
    cache.set(key, info, settings.TENANT_STATUS_CACHE_SECONDS)
    return info


def invalidate_tenant_info(tenant_id: UUID) -> None:
    cache.delete(_tenant_info_key(tenant_id))


def tenant_by_slug(slug: str) -> Tenant | None:
    tenant: Tenant | None = Tenant.objects.filter(slug=slug).first()
    return tenant


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


# --- Settings (ADR-016) -------------------------------------------------------------------------

SETTINGS_CACHE_TTL = 300
_PLATFORM_SETTINGS_KEY = "settings:platform"


def _tenant_settings_key(tenant_id: UUID) -> str:
    return f"settings:tenant:{tenant_id}"


def invalidate_tenant_settings(tenant_id: UUID) -> None:
    cache.delete(_tenant_settings_key(tenant_id))


def invalidate_platform_settings() -> None:
    cache.delete(_PLATFORM_SETTINGS_KEY)


def tenant_setting_overrides(
    tenant_id: UUID | None = None, *, fresh: bool = False
) -> dict[str, Any]:
    """Stored overrides (JSON values) for the tenant. Cached, unless ``fresh``: writers read fresh
    inside their transaction and never put uncommitted values into the shared cache."""
    tid = tenant_id or require_tenant_id()
    key = _tenant_settings_key(tid)
    if not fresh:
        cached: dict[str, Any] | None = cache.get(key)
        if cached is not None:
            return cached
    with transaction.atomic(), tenant_context(tid):
        overrides = dict(TenantSetting.objects.filter(tenant_id=tid).values_list("key", "value"))
    if not fresh:
        cache.set(key, overrides, SETTINGS_CACHE_TTL)
    return overrides


def platform_setting_overrides(*, fresh: bool = False) -> dict[str, Any]:
    if not fresh:
        cached: dict[str, Any] | None = cache.get(_PLATFORM_SETTINGS_KEY)
        if cached is not None:
            return cached
    overrides = dict(PlatformSetting.objects.values_list("key", "value"))
    if not fresh:
        cache.set(_PLATFORM_SETTINGS_KEY, overrides, SETTINGS_CACHE_TTL)
    return overrides


def _effective(defn: registry.SettingDef, overrides: dict[str, Any]) -> Any:
    if defn.key in overrides:
        return registry.from_json(defn, overrides[defn.key])
    return defn.default


def get_setting(key: str, tenant_id: UUID | None = None) -> Any:
    """Typed effective value of a tenant-scope key (override, else registry default)."""
    defn = registry.get_definition(key, Scope.TENANT)
    return _effective(defn, tenant_setting_overrides(tenant_id))


def get_platform_setting(key: str) -> Any:
    defn = registry.get_definition(key, Scope.PLATFORM)
    return _effective(defn, platform_setting_overrides())


def tenant_settings(tenant_id: UUID | None = None, *, fresh: bool = False) -> dict[str, Any]:
    """Every tenant-scope key with its typed effective value."""
    overrides = tenant_setting_overrides(tenant_id, fresh=fresh)
    return {d.key: _effective(d, overrides) for d in registry.definitions(Scope.TENANT)}


def platform_settings(*, fresh: bool = False) -> dict[str, Any]:
    overrides = platform_setting_overrides(fresh=fresh)
    return {d.key: _effective(d, overrides) for d in registry.definitions(Scope.PLATFORM)}


def settings_snapshot(target: SnapshotOn, tenant_id: UUID | None = None) -> dict[str, Any]:
    """JSON-safe values of every key snapshotted onto a ``target`` document (ADR-016). Documents
    store this when created, so later setting changes never alter them."""
    overrides = tenant_setting_overrides(tenant_id)
    return {
        d.key: registry.to_json(d, _effective(d, overrides))
        for d in registry.definitions(Scope.TENANT)
        if target in d.snapshot_on
    }
