"""Platform: tenants, reference data, plans, feature flags (PLAN §2.2). Data only, no logic.

Platform-level tables (State, TaxRate, CessType, HsnRateHint, Tenant, Plan, FeatureFlag) have no
RLS: they are reference data or the tenant registry itself. Tenant-owned rows (profile, branding,
subscription, feature overrides) inherit ``TenantScopedModel`` and are protected by RLS.
"""

import secrets

from django.conf import settings
from django.db import models
from django.db.models import F
from django.db.models.functions import Substr

from apps.platform.validators import (
    validate_business_phone,
    validate_gstin,
    validate_hex_color,
    validate_hsn_prefix,
    validate_ifsc,
    validate_pan,
    validate_pincode,
    validate_tenant_slug,
    validate_upi_id,
)
from common.crypto import EncryptedTextField
from common.fields import MoneyField, RateField
from common.models import BaseModel, TenantScopedModel

DEFAULT_BRAND_COLOR = "#2f5bea"  # keep in sync with web/lib/theme/palette.ts


def new_webhook_token() -> str:
    return secrets.token_urlsafe(32)


# --- Reference data & platform masters -----------------------------------------------------------


class State(models.Model):
    """GST state / union territory, keyed by its 2-digit GST state code (e.g. "27")."""

    code = models.CharField(max_length=2, primary_key=True)
    name = models.CharField(max_length=80)
    is_union_territory = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)  # legacy codes stay for historical GSTINs

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__regex=r"^[0-9]{2}$"), name="state_code_2_digits"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class TaxRate(BaseModel):
    """GST rate master (ADR-008). Inactive rates cannot be assigned but stay valid on history."""

    rate = RateField(unique=True)
    label = models.CharField(max_length=40)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["rate"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rate__gte=0) & models.Q(rate__lte=100), name="tax_rate_0_to_100"
            ),
        ]

    def __str__(self) -> str:
        return self.label


class CessType(BaseModel):
    class CalcMethod(models.TextChoices):
        PERCENT = "PERCENT", "Percentage of taxable value"
        SPECIFIC_PER_UNIT = "SPECIFIC_PER_UNIT", "Fixed amount per unit (reserved)"

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    calc_method = models.CharField(
        max_length=20, choices=CalcMethod.choices, default=CalcMethod.PERCENT
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class HsnRateHint(BaseModel):
    """Optional HSN prefix → GST rate suggestion. Never used to compute tax (ADR-008)."""

    hsn_prefix = models.CharField(max_length=8, validators=[validate_hsn_prefix])
    gst_rate = RateField()
    effective_from = models.DateField()
    description = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["hsn_prefix", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["hsn_prefix", "effective_from"], name="uniq_hsn_hint_prefix_date"
            ),
            models.CheckConstraint(
                condition=models.Q(hsn_prefix__regex=r"^[0-9]{2,8}$"), name="hsn_hint_prefix_digits"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.hsn_prefix} → {self.gst_rate}%"


# --- Tenants -------------------------------------------------------------------------------------


class Tenant(BaseModel):
    """A distributor (tenant). The registry of tenants itself is platform data (no RLS)."""

    class Status(models.TextChoices):
        ONBOARDING = "ONBOARDING", "Onboarding"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    class RegistrationType(models.TextChoices):
        REGULAR = "REGULAR", "Regular"
        COMPOSITION = "COMPOSITION", "Composition (reserved)"

    name = models.CharField(max_length=200)  # trade / display name
    slug = models.CharField(max_length=30, unique=True, validators=[validate_tenant_slug])
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ONBOARDING)
    legal_name = models.CharField(max_length=200)
    registration_type = models.CharField(
        max_length=20, choices=RegistrationType.choices, default=RegistrationType.REGULAR
    )
    gstin = models.CharField(max_length=15, unique=True, validators=[validate_gstin])
    pan = models.CharField(max_length=10, validators=[validate_pan])
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="+")
    address_line1 = models.CharField(max_length=200)
    address_line2 = models.CharField(max_length=200, blank=True, default="")
    city = models.CharField(max_length=100)
    pincode = models.CharField(max_length=6, validators=[validate_pincode])
    email = models.EmailField()
    phone = models.CharField(max_length=16, validators=[validate_business_phone])
    suspended_reason = models.TextField(blank=True, default="")
    suspended_at = models.DateTimeField(null=True, blank=True)
    webhook_token = models.CharField(max_length=64, unique=True, default=new_webhook_token)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(slug__regex=r"^[a-z0-9][a-z0-9-]{1,28}[a-z0-9]$"),
                name="tenant_slug_format",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["ONBOARDING", "ACTIVE", "SUSPENDED"]),
                name="tenant_status_valid",
            ),
            # ADR-012: only regular GST registration in v1 (COMPOSITION is reserved).
            models.CheckConstraint(
                condition=models.Q(registration_type="REGULAR"), name="tenant_registration_regular"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    gstin__regex=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
                ),
                name="tenant_gstin_format",
            ),
            models.CheckConstraint(
                condition=models.Q(gstin__startswith=F("state_id")),
                name="tenant_gstin_matches_state",
            ),
            models.CheckConstraint(
                condition=models.Q(pan=Substr("gstin", 3, 10)), name="tenant_pan_matches_gstin"
            ),
            models.CheckConstraint(
                condition=models.Q(pincode__regex=r"^[1-9][0-9]{5}$"), name="tenant_pincode_format"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class TenantProfile(TenantScopedModel):
    """Business data printed on documents (not settings). One row per tenant."""

    invoice_terms = models.TextField(blank=True, default="")
    invoice_footer = models.TextField(blank=True, default="")
    bank_account_name = models.CharField(max_length=200, blank=True, default="")
    bank_account_number = EncryptedTextField(blank=True, default="")
    bank_ifsc = models.CharField(max_length=11, blank=True, default="", validators=[validate_ifsc])
    bank_name = models.CharField(max_length=120, blank=True, default="")
    bank_branch = models.CharField(max_length=120, blank=True, default="")
    upi_id = models.CharField(max_length=320, blank=True, default="", validators=[validate_upi_id])
    signatory_name = models.CharField(max_length=150, blank=True, default="")
    signatory_image = models.CharField(max_length=255, blank=True, default="")  # storage key

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="uniq_profile_per_tenant"),
        ]

    def __str__(self) -> str:
        return f"profile:{self.tenant_id}"


class TenantBranding(TenantScopedModel):
    """Branding shown before and after login. The palette is derived on the client (ADR-028)."""

    display_name = models.CharField(max_length=120, blank=True, default="")
    logo = models.CharField(max_length=255, blank=True, default="")  # storage keys
    favicon = models.CharField(max_length=255, blank=True, default="")
    app_icon = models.CharField(max_length=255, blank=True, default="")
    primary_color = models.CharField(
        max_length=7, default=DEFAULT_BRAND_COLOR, validators=[validate_hex_color]
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="uniq_branding_per_tenant"),
            models.CheckConstraint(
                condition=models.Q(primary_color__regex=r"^#[0-9a-f]{6}$"),
                name="branding_color_hex",
            ),
        ]

    def __str__(self) -> str:
        return f"branding:{self.tenant_id}"


# --- Plans, subscriptions & feature flags --------------------------------------------------------


class Plan(BaseModel):
    """Subscription plan. Limits are informational until PLAN_ENFORCEMENT_ENABLED (spec 5.1)."""

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    price_monthly = MoneyField(default=0)
    max_retailers = models.PositiveIntegerField(null=True, blank=True)  # null = unlimited
    max_staff = models.PositiveIntegerField(null=True, blank=True)
    max_products = models.PositiveIntegerField(null=True, blank=True)
    features = models.JSONField(default=list, blank=True)  # feature flag codes included
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["price_monthly", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"], condition=models.Q(is_default=True), name="uniq_default_plan"
            ),
            models.CheckConstraint(
                condition=models.Q(price_monthly__gte=0), name="plan_price_non_negative"
            ),
        ]

    def __str__(self) -> str:
        return self.code


class Subscription(TenantScopedModel):
    class Status(models.TextChoices):
        TRIAL = "TRIAL", "Trial"
        ACTIVE = "ACTIVE", "Active"
        PAST_DUE = "PAST_DUE", "Past due"
        CANCELLED = "CANCELLED", "Cancelled"

    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    is_current = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant"],
                condition=models.Q(is_current=True),
                name="uniq_current_subscription",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id}:{self.plan_id}"


class FeatureFlag(BaseModel):
    """A module that can be switched on per tenant. Flags gate modules; settings tune behaviour."""

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    default_enabled = models.BooleanField(default=False)
    tenant_toggleable = models.BooleanField(default=False)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class TenantFeature(TenantScopedModel):
    """Per-tenant override of a feature flag's default."""

    flag = models.ForeignKey(FeatureFlag, on_delete=models.CASCADE, related_name="+")
    enabled = models.BooleanField()
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "flag"], name="uniq_tenant_feature"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id}:{self.flag_id}={self.enabled}"


# --- Settings overrides (ADR-016): only non-default values are stored ----------------------------


class TenantSetting(TenantScopedModel):
    """A tenant's override of a registry key. Written only via ``platform.services.set_setting``."""

    key = models.CharField(max_length=80)
    value = models.JSONField(null=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "key"], name="uniq_tenant_setting_key"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id}:{self.key}"


class PlatformSetting(BaseModel):
    """A platform-wide override of a platform-scope registry key."""

    key = models.CharField(max_length=80, unique=True)
    value = models.JSONField(null=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    def __str__(self) -> str:
        return self.key
