"""Retailers (PLAN §2.6). PHASE 1 STUB: enough for OTP sign-in (ADR-015); Phase 2 completes it
(GSTIN, addresses, price list, salesperson, credit terms)."""

from django.db import models

from common.models import TenantScopedModel


class Retailer(TenantScopedModel):
    """A shop buying from this distributor. The same shop under another distributor is a separate,
    unrelated retailer (ADR-015)."""

    shop_name = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=150, blank=True, default="")
    phone = models.CharField(max_length=16)  # +91XXXXXXXXXX
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "phone"], name="uniq_retailer_phone_per_tenant"
            ),
        ]
        indexes = [models.Index(fields=["tenant", "shop_name"], name="retailer_tenant_name_idx")]

    def __str__(self) -> str:
        return self.shop_name


class RetailerUser(TenantScopedModel):
    """Links a RETAILER login to its retailer (one login per retailer now; more later)."""

    retailer = models.ForeignKey(Retailer, on_delete=models.PROTECT, related_name="logins")
    user = models.OneToOneField(
        "accounts.User", on_delete=models.PROTECT, related_name="retailer_link"
    )

    def __str__(self) -> str:
        return f"{self.user_id}->{self.retailer_id}"
