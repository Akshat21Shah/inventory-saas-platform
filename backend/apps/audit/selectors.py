"""Reading the audit log: a tenant's own trail, and the all-tenant platform view."""

from datetime import datetime
from typing import TypedDict
from uuid import UUID

from django.db.models import QuerySet

from apps.audit.models import AuditLog
from common.platform_db import platform_db
from common.tenancy import require_tenant_id


class AuditFilters(TypedDict, total=False):
    action: str  # exact code, or a prefix ending in "." (e.g. "settings.")
    actor_id: UUID
    target_type: str
    target_id: str
    since: datetime
    until: datetime


def _apply(qs: QuerySet[AuditLog], filters: AuditFilters) -> QuerySet[AuditLog]:
    action = filters.get("action")
    if action:
        qs = (
            qs.filter(action__startswith=action)
            if action.endswith(".")
            else qs.filter(action=action)
        )
    if "actor_id" in filters:
        qs = qs.filter(actor_id=filters["actor_id"])
    if "target_type" in filters:
        qs = qs.filter(target_type=filters["target_type"])
    if "target_id" in filters:
        qs = qs.filter(target_id=filters["target_id"])
    if "since" in filters:
        qs = qs.filter(created_at__gte=filters["since"])
    if "until" in filters:
        qs = qs.filter(created_at__lt=filters["until"])
    return qs


def tenant_audit_logs(filters: AuditFilters | None = None) -> QuerySet[AuditLog]:
    """The active tenant's audit trail (including platform actions taken on this tenant)."""
    qs = AuditLog.objects.filter(tenant_id=require_tenant_id()).select_related(
        "actor", "impersonator"
    )
    return _apply(qs, filters or {}).order_by("-created_at")


def platform_audit_logs(
    filters: AuditFilters | None = None, tenant_id: UUID | None = None
) -> QuerySet[AuditLog]:
    """All tenants' and platform-level entries (super admin; audited platform alias)."""
    qs = AuditLog.objects.using(platform_db("audit.platform_audit_logs")).select_related(
        "actor", "impersonator", "tenant"
    )
    if tenant_id is not None:
        qs = qs.filter(tenant_id=tenant_id)
    return _apply(qs, filters or {}).order_by("-created_at")
