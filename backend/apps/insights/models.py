"""Shop activity (ADR-056 items 1-4): each shop's ordering pattern, worked out nightly, and the
contacts staff log when they try to win a shop back."""

from django.conf import settings
from django.db import models

from common.fields import MoneyField
from common.models import TenantScopedModel


class Segment(models.TextChoices):
    NEW = "NEW", "New"
    ACTIVE = "ACTIVE", "Active"
    SLOWING = "SLOWING", "Slowing down"
    DORMANT = "DORMANT", "Stopped ordering"
    NEVER_ORDERED = "NEVER_ORDERED", "Never ordered"


# Shops to win back, most urgent first (``ShopActivity.urgency``).
WIN_BACK = (Segment.DORMANT, Segment.SLOWING, Segment.NEVER_ORDERED)


class ShopActivity(TenantScopedModel):
    """One row per shop, replaced by each run. Order values are order totals incl. GST."""

    retailer = models.OneToOneField(
        "retailers.Retailer", on_delete=models.CASCADE, related_name="activity"
    )
    computed_at = models.DateTimeField()
    segment = models.CharField(max_length=13, choices=Segment.choices)
    first_order_date = models.DateField(null=True, blank=True)
    last_order_date = models.DateField(null=True, blank=True)
    days_since_last = models.PositiveIntegerField(null=True, blank=True)
    # Median days between the shop's last orders (up to 10); none with fewer than 3 orders.
    usual_gap_days = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    orders_90 = models.PositiveIntegerField(default=0)
    orders_prev_90 = models.PositiveIntegerField(default=0)
    value_90 = MoneyField(default=0)
    value_prev_90 = MoneyField(default=0)
    last_contact_at = models.DateTimeField(null=True, blank=True)
    # Sorting key: the segment's weight, then days without an order (higher: act sooner).
    urgency = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "segment"], name="shop_activity_segment_idx"),
            models.Index(fields=["tenant", "-urgency"], name="shop_activity_urgency_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.retailer_id} {self.segment}"


class ShopContact(TenantScopedModel):
    """A call, message or visit to a shop, as staff logged it. Append-only."""

    class Channel(models.TextChoices):
        CALL = "CALL", "Call"
        WHATSAPP = "WHATSAPP", "WhatsApp"
        VISIT = "VISIT", "Visit"
        OTHER = "OTHER", "Other"

    class Outcome(models.TextChoices):
        REACHED = "REACHED", "Spoke to them"
        NO_ANSWER = "NO_ANSWER", "No answer"
        WILL_ORDER = "WILL_ORDER", "Will order"
        NOT_INTERESTED = "NOT_INTERESTED", "Not interested"
        OTHER = "OTHER", "Other"

    retailer = models.ForeignKey(
        "retailers.Retailer", on_delete=models.CASCADE, related_name="contacts"
    )
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    channel = models.CharField(max_length=8, choices=Channel.choices)
    outcome = models.CharField(max_length=14, choices=Outcome.choices)
    note = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        indexes = [
            models.Index(
                fields=["tenant", "retailer", "-created_at"], name="shop_contact_retailer_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.retailer_id} {self.channel} {self.outcome}"
