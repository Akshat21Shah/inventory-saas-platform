"""Write-side business logic for the platform app. Every change is transactional and audited."""

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import User
from apps.audit import services as audit
from apps.platform import registry, selectors
from apps.platform.models import PlatformSetting, TenantSetting
from apps.platform.registry import Scope, SettingDef, Status
from common.error_codes import ErrorCode
from common.errors import DomainError
from common.tenancy import require_tenant_id


class SettingsInvalid(DomainError):
    status_code = 400
    code = ErrorCode.VALIDATION_ERROR
    default_message = "Some settings need attention."


def _validate(values: Mapping[str, Any], scope: Scope) -> dict[str, tuple[SettingDef, Any]]:
    """Validate every key first, so a batch is applied completely or not at all."""
    errors: dict[str, list[str]] = {}
    validated: dict[str, tuple[SettingDef, Any]] = {}
    for key, raw in values.items():
        try:
            defn = registry.get_definition(key, scope)
        except KeyError:
            errors[key] = ["This setting does not exist."]
            continue
        if defn.status is Status.RESERVED:
            errors[key] = ["This setting cannot be changed yet."]
            continue
        try:
            validated[key] = (defn, registry.to_python(defn, raw))
        except ValidationError as exc:
            errors[key] = list(exc.messages)
    if errors:
        raise SettingsInvalid(details={"fields": errors})
    return validated


def _audit_change(action: str, defn: SettingDef, old: Any, new: Any, tenant_scoped: bool) -> None:
    audit.record(
        action,
        target_type="setting",
        target_id=defn.key,
        target_repr=defn.key,
        changes={"value": [registry.to_json(defn, old), registry.to_json(defn, new)]},
        metadata={"scope": defn.scope.value, "group": defn.group.value},
        **({} if tenant_scoped else {"tenant_id": None}),
    )


@transaction.atomic
def set_tenant_settings(values: Mapping[str, Any], *, user: User | None) -> dict[str, Any]:
    """Set tenant-scope keys for the active tenant (atomic; audited per changed key).

    Permission to edit each key (``SettingDef.required_permission``) is checked by the caller.
    A value equal to the default removes the override, so defaults keep applying.
    """
    tenant_id = require_tenant_id()
    validated = _validate(values, Scope.TENANT)
    current = selectors.tenant_settings(tenant_id, fresh=True)
    after = {**current, **{key: new for key, (_, new) in validated.items()}}
    disordered = {
        (high if high in validated else low): [message]
        for low, high, message in registry.ASCENDING
        if after[high] <= after[low]
    }
    if disordered:
        raise SettingsInvalid(details={"fields": disordered})
    for key, (defn, new) in validated.items():
        old = current[key]
        if old == new:
            continue
        if new == defn.default:
            TenantSetting.objects.filter(key=key).delete()
        else:
            TenantSetting.objects.update_or_create(
                key=key, defaults={"value": registry.to_json(defn, new), "updated_by": user}
            )
        _audit_change("settings.changed", defn, old, new, tenant_scoped=True)
    transaction.on_commit(lambda: selectors.invalidate_tenant_settings(tenant_id))
    return selectors.tenant_settings(tenant_id, fresh=True)


@transaction.atomic
def reset_tenant_setting(key: str, *, user: User | None) -> Any:
    """Remove the active tenant's override of ``key`` (back to the default; audited)."""
    tenant_id = require_tenant_id()
    try:
        defn = registry.get_definition(key, Scope.TENANT)
    except KeyError as exc:
        raise SettingsInvalid(details={"fields": {key: ["This setting does not exist."]}}) from exc
    old = selectors.tenant_settings(tenant_id, fresh=True)[key]
    deleted, _ = TenantSetting.objects.filter(key=key).delete()
    if deleted:
        _audit_change("settings.reset", defn, old, defn.default, tenant_scoped=True)
    transaction.on_commit(lambda: selectors.invalidate_tenant_settings(tenant_id))
    return defn.default


@transaction.atomic
def set_platform_settings(values: Mapping[str, Any], *, user: User | None) -> dict[str, Any]:
    """Set platform-scope keys (super admin; audited as platform-level entries)."""
    validated = _validate(values, Scope.PLATFORM)
    current = selectors.platform_settings(fresh=True)
    for key, (defn, new) in validated.items():
        old = current[key]
        if old == new:
            continue
        if new == defn.default:
            PlatformSetting.objects.filter(key=key).delete()
        else:
            PlatformSetting.objects.update_or_create(
                key=key, defaults={"value": registry.to_json(defn, new), "updated_by": user}
            )
        _audit_change("settings.changed", defn, old, new, tenant_scoped=False)
    transaction.on_commit(selectors.invalidate_platform_settings)
    return selectors.platform_settings(fresh=True)
