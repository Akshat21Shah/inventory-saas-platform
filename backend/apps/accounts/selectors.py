"""Read-side queries for accounts: permission resolution, memberships, retailer logins."""

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from apps.accounts.models import Membership, Permission, User
from apps.platform.models import Tenant
from common.platform_db import platform_db
from common.tenancy import tenant_context


def role_codes(role_id: UUID) -> frozenset[str]:
    return frozenset(Permission.objects.filter(roles__id=role_id).values_list("code", flat=True))


def active_membership(user: User, tenant_id: UUID) -> Membership | None:
    """The user's active membership in ``tenant_id`` (read under that tenant's RLS context)."""
    with transaction.atomic(), tenant_context(tenant_id):
        membership: Membership | None = (
            Membership.objects.filter(user=user, is_active=True).select_related("role").first()
        )
    return membership


def resolve_permission_codes(user: User, tenant_id: UUID | None) -> frozenset[str]:
    """Permission codes for ``user`` acting in ``tenant_id`` (fails closed to no permissions)."""
    if not user.is_active:
        return frozenset()
    if user.user_type == User.UserType.PLATFORM:
        return role_codes(user.platform_role_id) if user.platform_role_id else frozenset()
    if user.user_type == User.UserType.STAFF and tenant_id is not None:
        membership = active_membership(user, tenant_id)
        return role_codes(membership.role_id) if membership else frozenset()
    return frozenset()


def staff_memberships_for_login(user: User) -> list[Tenant]:
    """Active tenants in which ``user`` has an active membership, for generic-domain login.

    ADR-026: one of the two cross-tenant login lookups. Runs on the platform alias only after the
    password was verified, and returns tenants only (never another user's data).
    """
    alias = platform_db("accounts.staff_memberships_for_login")
    tenant_ids = (
        Membership.objects.unscoped()
        .using(alias)
        .filter(user_id=user.pk, is_active=True)
        .values_list("tenant_id", flat=True)
    )
    return list(
        Tenant.objects.using(alias)
        .filter(pk__in=list(tenant_ids), status=Tenant.Status.ACTIVE)
        .order_by("name")
    )


def has_membership_in_suspended_tenant(user: User) -> bool:
    alias = platform_db("accounts.has_membership_in_suspended_tenant")
    tenant_ids = (
        Membership.objects.unscoped()
        .using(alias)
        .filter(user_id=user.pk, is_active=True)
        .values_list("tenant_id", flat=True)
    )
    return (
        Tenant.objects.using(alias)
        .filter(pk__in=list(tenant_ids), status=Tenant.Status.SUSPENDED)
        .exists()
    )


@dataclass(frozen=True)
class RetailerAccount:
    user: User
    tenant: Tenant
    shop_name: str
    distributor_name: str


def retailer_accounts_for_verified_phone(phone: str) -> list[RetailerAccount]:
    """Active retailer logins for ``phone`` in active tenants, for the generic-domain chooser.

    ADR-026: the second cross-tenant login lookup. Call only after the OTP for ``phone`` was
    verified; the result is shown only to that phone's owner, never to any distributor.
    """
    from apps.platform.models import TenantBranding
    from apps.retailers.models import RetailerUser

    alias = platform_db("accounts.retailer_accounts_for_verified_phone")
    users = list(
        User.objects.using(alias)
        .filter(
            user_type=User.UserType.RETAILER,
            phone=phone,
            is_active=True,
            tenant__status=Tenant.Status.ACTIVE,
        )
        .select_related("tenant")
    )
    links = {
        link.user_id: link
        for link in RetailerUser.objects.unscoped()
        .using(alias)
        .filter(user__in=users, retailer__is_active=True)
        .select_related("retailer")
    }
    brand_names = dict(
        TenantBranding.objects.unscoped()
        .using(alias)
        .filter(tenant_id__in=[u.tenant_id for u in users])
        .values_list("tenant_id", "display_name")
    )
    accounts = [
        RetailerAccount(
            user=u,
            tenant=u.tenant,  # type: ignore[arg-type]
            shop_name=links[u.pk].retailer.shop_name,
            distributor_name=brand_names.get(u.tenant_id) or u.tenant.name,  # type: ignore[union-attr]
        )
        for u in users
        if u.pk in links
    ]
    return sorted(accounts, key=lambda a: a.distributor_name.lower())


def retailer_login_for_tenant(phone: str, tenant_id: UUID) -> User | None:
    """The active retailer login for ``phone`` in this tenant (subdomain sign-in)."""
    from apps.retailers.models import RetailerUser

    user: User | None = User.objects.filter(
        user_type=User.UserType.RETAILER, phone=phone, tenant_id=tenant_id, is_active=True
    ).first()
    if user is None:
        return None
    with transaction.atomic(), tenant_context(tenant_id):
        active = RetailerUser.objects.filter(user=user, retailer__is_active=True).exists()
    return user if active else None
