"""Writing audit entries (spec 5.16). Call ``record()`` inside the business transaction, so an entry
exists exactly when the audited change commits."""

import json
from collections.abc import Iterable, Mapping
from typing import Any, Final
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction

from apps.audit.models import AuditLog
from common.context import Actor, actor_var, request_id_var, request_meta_var
from common.crypto import mask
from common.tenancy import get_current_tenant_id, tenant_context


class _CurrentTenant:
    def __repr__(self) -> str:
        return "CURRENT_TENANT"


CURRENT_TENANT: Final = _CurrentTenant()


def to_jsonable(value: Any) -> Any:
    """Decimals, UUIDs, dates and enums as JSON-safe values (Decimal stays exact, as a string)."""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def snapshot(instance: models.Model, fields: Iterable[str]) -> dict[str, Any]:
    """Current values of ``fields`` (use ``attname`` values for FKs, e.g. ``state_id``)."""
    return {name: getattr(instance, name) for name in fields}


def diff(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    masked: Iterable[str] = (),
) -> dict[str, list[Any]]:
    """``{field: [before, after]}`` for changed fields only. Masked fields never store plaintext."""
    masked_set = set(masked)
    changes: dict[str, list[Any]] = {}
    for field in sorted(set(before) | set(after)):
        old, new = before.get(field), after.get(field)
        if old == new:
            continue
        if field in masked_set:
            changes[field] = [mask(old), mask(new)]
        else:
            changes[field] = [to_jsonable(old), to_jsonable(new)]
    return changes


def _target_fields(
    target: models.Model | None, target_type: str, target_id: str | UUID, target_repr: str
) -> dict[str, str]:
    if target is not None:
        target_type = target_type or target._meta.label_lower
        target_id = target_id or str(target.pk)
        target_repr = target_repr or str(target)
    return {
        "target_type": target_type,
        "target_id": str(target_id),
        "target_repr": target_repr[:200],
    }


def _actor_fields(who: Actor | None) -> dict[str, Any]:
    if who is None:
        return {"actor_type": AuditLog.ActorType.SYSTEM}
    return {
        "actor_id": who.user_id,
        "actor_type": who.actor_type,
        "impersonator_id": who.impersonator_id,
        "impersonation_session_id": who.impersonation_session_id,
    }


def _request_fields() -> dict[str, Any]:
    meta = request_meta_var.get()
    return {
        "ip": meta.ip if meta else None,
        "user_agent": meta.user_agent if meta else "",
        "request_id": request_id_var.get() or "",
    }


def record(
    action: str,
    *,
    target: models.Model | None = None,
    target_type: str = "",
    target_id: str | UUID = "",
    target_repr: str = "",
    changes: Mapping[str, list[Any]] | None = None,
    metadata: Mapping[str, Any] | None = None,
    tenant_id: UUID | _CurrentTenant | None = CURRENT_TENANT,
    actor: Actor | None = None,
) -> AuditLog:
    """Write one audit entry.

    - ``tenant_id``: defaults to the active tenant; pass ``None`` for a platform-level entry, or a
      tenant id when a platform user acts on that tenant (it then appears in the tenant's own log).
    - ``actor``: defaults to the authenticated actor (with impersonation context); SYSTEM if none.
    """
    resolved = get_current_tenant_id() if isinstance(tenant_id, _CurrentTenant) else tenant_id
    entry = AuditLog(
        tenant_id=resolved,
        action=action,
        changes=to_jsonable(dict(changes or {})),
        metadata=to_jsonable(dict(metadata or {})),
        **_target_fields(target, target_type, target_id, target_repr),
        **_actor_fields(actor or actor_var.get()),
        **_request_fields(),
    )
    # A savepoint inside the caller's transaction. The RLS tenant is set explicitly to the row's
    # tenant (and restored), so the insert passes the policy whatever context the caller is in.
    with transaction.atomic():
        if resolved is not None:
            with tenant_context(resolved):
                entry.save(force_insert=True)
        else:
            entry.save(force_insert=True)
    return entry
