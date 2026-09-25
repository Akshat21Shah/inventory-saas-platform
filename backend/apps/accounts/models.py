"""Custom user model. PHASE 0 STUB: must exist before the first migration (AUTH_USER_MODEL).

Phase 1 adds the retailer tenant FK, per-tenant phone uniqueness (ADR-015), TOTP, lockout, and
``has_permission_code`` backed by Membership → Role → Permission.
"""

from typing import Any, ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from common.models import BaseModel


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
        extra.update(user_type=User.UserType.PLATFORM, is_staff=True, is_superuser=True)
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

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    def __str__(self) -> str:
        return self.email or self.phone or str(self.pk)

    def has_permission_code(self, code: str) -> bool:
        """Phase 1: resolve via Membership → Role → Permission. Fails closed until then."""
        return False
