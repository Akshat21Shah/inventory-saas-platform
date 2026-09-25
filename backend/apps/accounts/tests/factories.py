"""Test helpers for users, roles and memberships."""

from itertools import count

from apps.accounts.models import Membership, Role, User
from apps.platform.models import Tenant
from common.tenancy import tenant_context

_seq = count(1)


def system_role(code: str) -> Role:
    return Role.objects.get(tenant__isnull=True, code=code)


def make_staff(email: str | None = None, **extra: object) -> User:
    email = email or f"staff{next(_seq)}@example.com"
    return User.objects.create_user(
        email, "a-strong-password", user_type=User.UserType.STAFF, **extra
    )


def make_membership(
    user: User, tenant: Tenant, role_code: str = "OWNER", *, is_active: bool = True
) -> Membership:
    with tenant_context(tenant.id):
        membership: Membership = Membership.objects.create(
            user=user, role=system_role(role_code), is_active=is_active
        )
    return membership


def make_staff_in(tenant: Tenant, role_code: str = "OWNER", email: str | None = None) -> User:
    user = make_staff(email)
    make_membership(user, tenant, role_code)
    return user


def make_super_admin(email: str | None = None) -> User:
    return User.objects.create_superuser(
        email or f"admin{next(_seq)}@platform.example.com", "a-strong-password"
    )


def enable_totp(user: User) -> str:
    """Turn 2FA on for ``user`` and return the secret (tests generate codes with pyotp)."""
    import pyotp

    secret = pyotp.random_base32()
    User.objects.filter(pk=user.pk).update(totp_secret=secret, totp_enabled=True)
    user.refresh_from_db()
    return secret


def make_retailer_login(
    tenant: Tenant, phone: str = "9876543210", shop_name: str = "Ganesh Kirana"
) -> User:
    """A retailer of ``tenant`` with its RETAILER login; returns the login user."""
    from apps.retailers.services import create_retailer

    with tenant_context(tenant.id):
        retailer = create_retailer(shop_name=shop_name, phone=phone)
    user: User = User.objects.get(tenant=tenant, phone=retailer.mobile)
    return user
