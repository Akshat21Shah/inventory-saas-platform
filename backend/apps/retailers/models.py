"""Retailers (PLAN §2.6, spec 5.5). A shop belongs to exactly one distributor; the same shop under
another distributor is a separate, unrelated retailer (ADR-015)."""

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Substr

from common.fields import MoneyField
from common.models import SoftDeleteMixin, TenantScopedModel


class Retailer(SoftDeleteMixin, TenantScopedModel):
    class WhatsAppOptInSource(models.TextChoices):
        SHOP_APP = "SHOP_APP", "The shop, in the app"
        STAFF = "STAFF", "Staff"
        IMPORT = "IMPORT", "Import"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        BLOCKED = "BLOCKED", "On hold"

    code = models.CharField(max_length=20)  # R-00001, allocated per tenant
    shop_name = models.CharField(max_length=200)
    owner_name = models.CharField(max_length=150, blank=True, default="")
    mobile = models.CharField(max_length=16)  # +91XXXXXXXXXX, the sign-in number
    email = models.EmailField(blank=True, default="")
    # NULL (not "") for unregistered shops, so uniqueness applies only to real GSTINs.
    gstin = models.CharField(max_length=15, null=True, blank=True)  # noqa: DJ001
    pan = models.CharField(max_length=10, blank=True, default="")
    state = models.ForeignKey("platform.State", on_delete=models.PROTECT, related_name="+")
    price_list = models.ForeignKey(
        "pricing.PriceList", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )  # none = the product base price (spec 5.6)
    credit_limit = MoneyField(null=True, blank=True)  # empty = no limit; 0 = no credit (PLAN C2)
    payment_terms_days = models.PositiveSmallIntegerField(default=30)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    blocked_reason = models.CharField(max_length=300, blank=True, default="")
    salesperson = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    notes = models.TextField(blank=True, default="")
    tags = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    # A code from common/languages.json; empty: the distributor's default (ADR-060).
    preferred_language = models.CharField(max_length=5, blank=True, default="")
    # WhatsApp consent (ADR-048 item 5): no WhatsApp message without opt-in.
    whatsapp_opt_in = models.BooleanField(default=False)
    whatsapp_opt_in_at = models.DateTimeField(null=True, blank=True)
    whatsapp_opt_in_source = models.CharField(
        max_length=8,
        blank=True,
        default="",
        choices=WhatsAppOptInSource.choices,
    )
    whatsapp_opt_out_at = models.DateTimeField(null=True, blank=True)
    whatsapp_prompted_at = models.DateTimeField(null=True, blank=True)  # the one-time prompt
    welcome_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["shop_name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_retailer_code"),
            # ADR-015: unique per tenant (never across tenants); a deleted shop frees the number.
            models.UniqueConstraint(
                fields=["tenant", "mobile"],
                condition=Q(deleted_at__isnull=True),
                name="uniq_retailer_mobile_per_tenant",
            ),
            models.UniqueConstraint(
                fields=["tenant", "gstin"],
                condition=Q(gstin__isnull=False, deleted_at__isnull=True),
                name="uniq_retailer_gstin_per_tenant",
            ),
            models.CheckConstraint(
                condition=Q(gstin__isnull=True) | Q(gstin__startswith=F("state_id")),
                name="retailer_gstin_matches_state",
            ),
            models.CheckConstraint(
                condition=Q(gstin__isnull=True) | Q(pan=Substr("gstin", 3, 10)),
                name="retailer_pan_matches_gstin",
            ),
            models.CheckConstraint(
                condition=Q(credit_limit__isnull=True) | Q(credit_limit__gte=0),
                name="retailer_credit_limit_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["ACTIVE", "BLOCKED"]), name="retailer_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(mobile__regex=r"^\+91[6-9][0-9]{9}$"), name="retailer_mobile_format"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "shop_name"], name="retailer_tenant_name_idx"),
            models.Index(fields=["tenant", "salesperson"], name="retailer_salesperson_idx"),
            models.Index(fields=["tenant", "status"], name="retailer_status_idx"),
            GinIndex(fields=["shop_name"], name="retailer_name_trgm", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        return self.shop_name


class RetailerAddress(TenantScopedModel):
    class Kind(models.TextChoices):
        BILLING = "BILLING", "Billing"
        SHIPPING = "SHIPPING", "Shipping"

    retailer = models.ForeignKey(Retailer, on_delete=models.CASCADE, related_name="addresses")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    label = models.CharField(max_length=60, blank=True, default="")
    line1 = models.CharField(max_length=200)
    line2 = models.CharField(max_length=200, blank=True, default="")
    city = models.CharField(max_length=100)
    district = models.CharField(max_length=100, blank=True, default="")
    pincode = models.CharField(max_length=6)
    state = models.ForeignKey("platform.State", on_delete=models.PROTECT, related_name="+")
    is_default = models.BooleanField(default=False)
    # Road distance from the distributor, for e-way bills (Phase 7); editable at dispatch.
    distance_km = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["kind", "-is_default", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["retailer", "kind"],
                condition=Q(is_default=True),
                name="uniq_default_address_per_kind",
            ),
            models.CheckConstraint(
                condition=Q(pincode__regex=r"^[1-9][0-9]{5}$"), name="retailer_address_pincode"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.line1}, {self.city}"


class RetailerUser(TenantScopedModel):
    """Links a RETAILER login to its retailer (one login per retailer now; more later)."""

    retailer = models.ForeignKey(Retailer, on_delete=models.PROTECT, related_name="logins")
    user = models.OneToOneField(
        "accounts.User", on_delete=models.PROTECT, related_name="retailer_link"
    )

    def __str__(self) -> str:
        return f"{self.user_id}->{self.retailer_id}"
