"""Read-side queries for accounts: permission resolution, memberships."""

from uuid import UUID

from django.db import transaction

from apps.accounts.models import Membership, Permission, User
from common.tenancy import tenant_context


def _role_codes(role_id: UUID) -> frozenset[str]:
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
        return _role_codes(user.platform_role_id) if user.platform_role_id else frozenset()
    if user.user_type == User.UserType.STAFF and tenant_id is not None:
        membership = active_membership(user, tenant_id)
        return _role_codes(membership.role_id) if membership else frozenset()
    return frozenset()
