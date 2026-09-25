"""Users, permissions, roles and memberships (PLAN §2.3).

``User`` is an identity table without RLS (ADR-026): login must find users before any tenant is
known. Tenant-owned identity data (memberships) is tenant-scoped with RLS. Later Phase 1 commits
add the retailer tenant FK, per-tenant phone uniqueness (ADR-015), TOTP and lockout fields.
"""

from typing import Any, ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from common.context import tenant_id_var
from common.models import BaseModel, TenantScopedModel


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def create_user(
        self, email: str | None = None, password: str | None = None, **extra: Any
    ) -> "User":
        if email:
            email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra: Any) -> "User":
        """A super admin: PLATFORM user with the PLATFORM_ADMIN system role."""
        from apps.accounts.permissions import PLATFORM_ADMIN_ROLE

        extra.update(user_type=User.UserType.PLATFORM, is_staff=True, is_superuser=True)
        extra.setdefault(
            "platform_role", Role.objects.get(tenant__isnull=True, code=PLATFORM_ADMIN_ROLE)
        )
        return self.create_user(email, password, **extra)


class User(BaseModel, AbstractBaseUser, PermissionsMixin):
    class UserType(models.TextChoices):
        PLATFORM = "PLATFORM", "Platform"
        STAFF = "STAFF", "Distributor staff"
        RETAILER = "RETAILER", "Retailer"

    user_type = models.CharField(max_length=10, choices=UserType.choices)
    email = models.EmailField(unique=True, null=True, blank=True)
    # NULL (not '') so the Phase 1 partial unique index (tenant, phone) ignores staff without phones
    phone = models.CharField(max_length=16, null=True, blank=True)  # noqa: DJ001
    full_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Django admin access: super admins only
    # PLATFORM users only: their platform-level role (e.g. PLATFORM_ADMIN).
    platform_role = models.ForeignKey(
        "accounts.Role", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    def __str__(self) -> str:
        return self.email or self.phone or str(self.pk)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(platform_role__isnull=True) | models.Q(user_type="PLATFORM"),
                name="user_platform_role_only_for_platform_users",
            ),
        ]

    def permission_codes(self) -> frozenset[str]:
        """Permission codes in the current context (cached on the instance for the request).

        PLATFORM users: their platform role. STAFF: their active membership's role in the active
        tenant. RETAILER users have no staff permissions (retailer endpoints check the user type).
        """
        tenant_id = tenant_id_var.get()
        cache: dict[object, frozenset[str]] = self.__dict__.setdefault("_perm_cache", {})
        if tenant_id not in cache:
            from apps.accounts.selectors import resolve_permission_codes

            cache[tenant_id] = resolve_permission_codes(self, tenant_id)
        return cache[tenant_id]

    def has_permission_code(self, code: str) -> bool:
        return self.is_active and code in self.permission_codes()


class Permission(BaseModel):
    """A permission code from ``accounts/permissions.py`` (seeded by migration)."""

    code = models.CharField(max_length=60, unique=True)
    module = models.CharField(max_length=40)
    description = models.CharField(max_length=200)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class Role(BaseModel):
    """A named set of permissions. ``tenant`` NULL = system role (read-only for every tenant)."""

    tenant = models.ForeignKey(
        "platform.Tenant", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=80)
    is_system = models.BooleanField(default=False)
    is_platform = models.BooleanField(default=False)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_role_code_per_tenant", nulls_distinct=False
            ),
            models.CheckConstraint(
                condition=models.Q(is_system=False) | models.Q(tenant__isnull=True),
                name="role_system_roles_have_no_tenant",
            ),
            models.CheckConstraint(
                condition=models.Q(is_platform=False) | models.Q(tenant__isnull=True),
                name="role_platform_roles_have_no_tenant",
            ),
        ]

    def __str__(self) -> str:
        return self.code


class Membership(TenantScopedModel):
    """A staff user's membership of a tenant with one role (ADR-020: one user, many tenants)."""

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="+")
    is_active = models.BooleanField(default=True)
    invited_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user"], name="uniq_membership_per_tenant"),
        ]
        indexes = [models.Index(fields=["tenant", "role"], name="membership_tenant_role_idx")]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.tenant_id}:{self.role_id}"
