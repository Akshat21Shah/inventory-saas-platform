"""Users, permissions, roles and memberships (PLAN §2.3).

``User`` is an identity table without RLS (ADR-026): login must find users before any tenant is
known. Tenant-owned identity data (memberships) is tenant-scoped with RLS. Later Phase 1 commits
add the retailer tenant FK, per-tenant phone uniqueness (ADR-015), TOTP and lockout fields.
"""

from datetime import datetime
from typing import Any, ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from common.context import tenant_id_var
from common.crypto import EncryptedTextField
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
    # A code from common/languages.json (ADR-060); validated against it, no choices, so a new
    # language needs no migration.
    preferred_language = models.CharField(max_length=5, default="en")
    # TOTP second factor (spec 5.2): secret encrypted at rest (ADR-031); each time step used once.
    totp_secret = EncryptedTextField(blank=True, default="")
    totp_enabled = models.BooleanField(default=False)
    totp_last_step = models.BigIntegerField(null=True, blank=True)
    # Lockout (ADR-030): consecutive failures; reset on success or password reset.
    failed_login_count = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    # RETAILER users only: the distributor this login belongs to (ADR-015: one user per tenant).
    tenant = models.ForeignKey(
        "platform.Tenant", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
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
            # Emails are stored lower-cased, so uniqueness is case-insensitive.
            models.CheckConstraint(
                condition=models.Q(email__isnull=True) | models.Q(email=Lower("email")),
                name="user_email_lowercase",
            ),
            models.CheckConstraint(
                condition=models.Q(user_type="RETAILER") | models.Q(email__isnull=False),
                name="user_staff_and_platform_have_email",
            ),
            # ADR-015: retailer logins belong to one tenant and are unique by phone within it;
            # staff and platform users never carry a tenant.
            models.CheckConstraint(
                condition=(
                    models.Q(user_type="RETAILER", tenant__isnull=False, phone__isnull=False)
                    | (~models.Q(user_type="RETAILER") & models.Q(tenant__isnull=True))
                ),
                name="user_tenant_only_for_retailers",
            ),
            models.UniqueConstraint(
                fields=["tenant", "phone"],
                condition=models.Q(user_type="RETAILER"),
                name="uniq_retailer_user_phone_per_tenant",
            ),
        ]

    def is_locked(self, now: datetime | None = None) -> bool:
        return self.locked_until is not None and self.locked_until > (now or timezone.now())

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


# --- Login flow tables (identity data, no RLS: used before a tenant is known; ADR-026) ----------


class LoginChallenge(BaseModel):
    """A short-lived, single-use step in a login flow, referenced by an opaque token.

    Only the SHA-256 of the token is stored. ``candidates`` holds the ids offered in a chooser.
    """

    class Kind(models.TextChoices):
        STAFF_TENANT_CHOICE = "STAFF_TENANT_CHOICE", "Staff: choose a tenant"
        RETAILER_ACCOUNT_CHOICE = "RETAILER_ACCOUNT_CHOICE", "Retailer: choose a distributor"
        MFA = "MFA", "Second factor"
        MFA_ENROLMENT = "MFA_ENROLMENT", "Second factor set-up required at sign-in"
        MFA_SETUP = "MFA_SETUP", "Second factor set-up from account security"

    kind = models.CharField(max_length=30, choices=Kind.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    phone = models.CharField(max_length=16, blank=True, default="")
    tenant = models.ForeignKey(
        "platform.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    candidates = models.JSONField(default=list, blank=True)
    payload = models.JSONField(default=dict, blank=True)  # where the login continues; never secrets
    secret = EncryptedTextField(blank=True, default="")  # e.g. a TOTP secret pending confirmation
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["expires_at"], name="login_challenge_expiry_idx")]

    def __str__(self) -> str:
        return f"{self.kind}:{self.user_id or self.phone}"


class HandoffCode(BaseModel):
    """Single-use, 60-second code moving a verified login to the tenant subdomain (ADR-020)."""

    code_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    tenant = models.ForeignKey("platform.Tenant", on_delete=models.CASCADE, related_name="+")
    session_expires_at = models.DateTimeField(null=True, blank=True)
    # Set when the handoff starts an impersonation session instead of a normal sign-in.
    impersonation_session_id = models.UUIDField(null=True, blank=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["expires_at"], name="handoff_expiry_idx")]

    def __str__(self) -> str:
        return f"handoff:{self.user_id}->{self.tenant_id}"


class RecoveryCode(BaseModel):
    """Single-use 2FA recovery code. Only a SHA-256 is stored (the code has 80 bits of entropy)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "code_hash"], name="uniq_recovery_code"),
        ]

    def __str__(self) -> str:
        return f"recovery:{self.user_id}"


class OTPRequest(BaseModel):
    """A one-time code sent to a retailer's mobile (spec 5.2).

    RLS (ADR-026): rows requested on a tenant subdomain belong to that tenant; rows requested on the
    generic domain have no tenant. Only a hash of the code is stored. A row is created for every
    request, whether or not the number is known, so responses never reveal registration.
    """

    class Purpose(models.TextChoices):
        LOGIN = "LOGIN", "Sign in"

    class Channel(models.TextChoices):
        SMS = "SMS", "SMS"
        WHATSAPP = "WHATSAPP", "WhatsApp"

    tenant = models.ForeignKey(
        "platform.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    phone = models.CharField(max_length=16)
    purpose = models.CharField(max_length=10, choices=Purpose.choices, default=Purpose.LOGIN)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.SMS)
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["phone", "-created_at"], name="otp_phone_created_idx"),
            models.Index(fields=["expires_at"], name="otp_expiry_idx"),
        ]

    def __str__(self) -> str:
        return f"otp:{self.phone}"


class Invitation(TenantScopedModel):
    """An email invitation to join a tenant's staff with a role. Only a hash of the token is
    stored; the link goes to the tenant's subdomain (``/invite/<token>``)."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        REVOKED = "REVOKED", "Revoked"
        EXPIRED = "EXPIRED", "Expired"

    email = models.EmailField()
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="+")
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    invited_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "email"],
                condition=models.Q(status="PENDING"),
                name="uniq_pending_invitation_per_email",
            ),
            models.CheckConstraint(
                condition=models.Q(email=Lower("email")), name="invitation_email_lowercase"
            ),
        ]
        indexes = [models.Index(fields=["tenant", "status"], name="invitation_tenant_status_idx")]

    def __str__(self) -> str:
        return f"invite:{self.email}@{self.tenant_id}"


class ImpersonationSession(TenantScopedModel):
    """A super admin acting as a tenant user for support (ADR-029). READ_ONLY until the admin
    switches to ACT with a separate reason. Events go to the tenant's own audit log."""

    class Mode(models.TextChoices):
        READ_ONLY = "READ_ONLY", "Read only"
        ACT = "ACT", "Act"

    class EndReason(models.TextChoices):
        ENDED = "ENDED", "Ended"
        EXPIRED = "EXPIRED", "Expired"

    impersonator = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    target_user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField()
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.READ_ONLY)
    act_reason = models.TextField(blank=True, default="")
    act_started_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=10, choices=EndReason.choices, blank=True, default="")
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["tenant", "created_at"], name="impersonation_tenant_idx")]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(impersonator=models.F("target_user")),
                name="impersonation_not_self",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.impersonator_id}->{self.target_user_id}"

    def is_open(self) -> bool:
        return self.ended_at is None and self.expires_at > timezone.now()
