"""Super-admin read models across tenants (spec 5.1). Every query here runs on the audited
platform alias (``platform_db``), because tenant-owned rows are protected by RLS."""

from typing import Any
from uuid import UUID

from django.db.models import Count, OuterRef, Q, QuerySet, Subquery

from apps.accounts.models import Invitation, Membership
from apps.accounts.permissions import OWNER_ROLE
from apps.platform.models import Subscription, Tenant
from apps.retailers.models import Retailer
from common.platform_db import platform_db


def tenants_overview(*, status: str | None = None, search: str | None = None) -> QuerySet[Tenant]:
    alias = platform_db("platform.tenants_overview")
    current = (
        Subscription.objects.unscoped().using(alias).filter(tenant=OuterRef("pk"), is_current=True)
    )
    qs = (
        Tenant.objects.using(alias)
        .select_related("state")
        .annotate(
            plan_code=Subquery(current.values("plan__code")[:1]),
            plan_name=Subquery(current.values("plan__name")[:1]),
        )
    )
    if status:
        qs = qs.filter(status=status)
    if search:
        term = search.strip()
        qs = qs.filter(Q(name__icontains=term) | Q(slug__icontains=term) | Q(gstin__iexact=term))
    return qs


def tenant_detail(tenant_id: UUID) -> Tenant | None:
    tenant: Tenant | None = tenants_overview().filter(pk=tenant_id).first()
    return tenant


def tenant_usage(tenant_id: UUID) -> dict[str, int]:
    alias = platform_db("platform.tenant_usage")
    return {
        "staff": Membership.objects.unscoped()
        .using(alias)
        .filter(tenant_id=tenant_id, is_active=True)
        .count(),
        "retailers": Retailer.objects.unscoped()
        .using(alias)
        .filter(tenant_id=tenant_id, is_active=True)
        .count(),
        "pending_invitations": Invitation.objects.unscoped()
        .using(alias)
        .filter(tenant_id=tenant_id, status=Invitation.Status.PENDING)
        .count(),
    }


def tenant_owner(tenant_id: UUID) -> dict[str, Any] | None:
    """The owner (or the pending owner invitation) for the tenant detail page."""
    alias = platform_db("platform.tenant_owner")
    member = (
        Membership.objects.unscoped()
        .using(alias)
        .filter(tenant_id=tenant_id, role__code=OWNER_ROLE, is_active=True)
        .select_related("user")
        .order_by("joined_at")
        .first()
    )
    if member is not None:
        return {"email": member.user.email, "full_name": member.user.full_name, "status": "JOINED"}
    invitation = (
        Invitation.objects.unscoped()
        .using(alias)
        .filter(tenant_id=tenant_id, role__code=OWNER_ROLE)
        .order_by("-created_at")
        .first()
    )
    if invitation is None:
        return None
    return {"email": invitation.email, "full_name": "", "status": f"INVITATION_{invitation.status}"}


def tenant_staff(tenant_id: UUID) -> QuerySet[Membership]:
    alias = platform_db("platform.tenant_staff")
    return (
        Membership.objects.unscoped()
        .using(alias)
        .filter(tenant_id=tenant_id)
        .select_related("user", "role")
        .order_by("user__full_name", "pk")
    )


def platform_counts() -> dict[str, int]:
    alias = platform_db("platform.platform_counts")
    counts = Tenant.objects.using(alias).aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(status=Tenant.Status.ACTIVE)),
        onboarding=Count("pk", filter=Q(status=Tenant.Status.ONBOARDING)),
        suspended=Count("pk", filter=Q(status=Tenant.Status.SUSPENDED)),
    )
    return {k: int(v or 0) for k, v in counts.items()}
