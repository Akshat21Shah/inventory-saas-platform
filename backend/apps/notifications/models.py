"""Notifications (PLAN §2.13, spec 5.13, ADR-048). Delivery and every ledger of what was sent go
through the services; these are data only."""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from common.crypto import EncryptedTextField
from common.models import BaseModel, TenantScopedModel

USER = settings.AUTH_USER_MODEL


class Channel(models.TextChoices):
    IN_APP = "IN_APP", "In-app"
    EMAIL = "EMAIL", "Email"
    WHATSAPP = "WHATSAPP", "WhatsApp"
    SMS = "SMS", "SMS"


class Recipient(models.TextChoices):
    SHOP = "SHOP", "The shop"
    SALESPERSON = "SALESPERSON", "The shop's salesperson"
    COLLECTOR = "COLLECTOR", "The salesman who collected"
    STAFF_PERMISSION = "STAFF_PERMISSION", "Staff who can…"
    OWNERS = "OWNERS", "Owners"


class WhatsAppCategory(models.TextChoices):
    UTILITY = "UTILITY", "Utility"
    MARKETING = "MARKETING", "Marketing"
    AUTHENTICATION = "AUTHENTICATION", "Authentication"


class _TemplateFields(models.Model):
    event_code = models.CharField(max_length=40)
    channel = models.CharField(max_length=8, choices=Channel.choices)
    locale = models.CharField(max_length=5, default="en")
    subject = models.CharField(
        max_length=200, blank=True, default=""
    )  # email subject, in-app title
    body = models.TextField()
    whatsapp_template_name = models.CharField(max_length=100, blank=True, default="")
    whatsapp_language = models.CharField(max_length=10, blank=True, default="")
    whatsapp_category = models.CharField(
        max_length=14, choices=WhatsAppCategory.choices, blank=True, default=""
    )
    variables = models.JSONField(default=list)  # ordered: WhatsApp template parameters
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class PlatformTemplate(BaseModel, _TemplateFields):
    """The platform's default text for an event and channel (managed by the super admin)."""

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event_code", "channel", "locale"], name="uniq_platform_template"
            )
        ]

    def __str__(self) -> str:
        return f"{self.event_code} {self.channel} {self.locale}"


class NotificationTemplate(TenantScopedModel, _TemplateFields):
    """A distributor's own text for an event and channel (overrides the platform's)."""

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "event_code", "channel", "locale"], name="uniq_tenant_template"
            )
        ]

    def __str__(self) -> str:
        return f"{self.event_code} {self.channel} {self.locale}"


class NotificationRule(TenantScopedModel):
    """A distributor's choice for one event and recipient (the defaults live in
    ``apps.notifications.catalog``; a row overrides the default with the same key)."""

    event_code = models.CharField(max_length=40)
    recipient = models.CharField(max_length=16, choices=Recipient.choices)
    permission = models.CharField(max_length=60, blank=True, default="")  # STAFF_PERMISSION
    channels = ArrayField(models.CharField(max_length=8, choices=Channel.choices), default=list)
    is_enabled = models.BooleanField(default=True)
    is_compulsory = models.BooleanField(default=False)  # shop rules: can't be switched off

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "event_code", "recipient", "permission"],
                name="uniq_notification_rule",
            ),
            models.CheckConstraint(
                condition=~Q(recipient="STAFF_PERMISSION") | ~Q(permission=""),
                name="rule_permission_required",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_code} → {self.recipient} {self.permission}".strip()


class Notification(TenantScopedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Waiting to be sent"
        SENDING = "SENDING", "Being sent"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"
        SKIPPED = "SKIPPED", "Not sent"

    class SkipReason(models.TextChoices):
        NO_ADDRESS = "NO_ADDRESS", "No email or mobile number"
        NO_WHATSAPP_OPT_IN = "NO_WHATSAPP_OPT_IN", "The shop has not agreed to WhatsApp"
        TURNED_OFF = "TURNED_OFF", "Switched off by the recipient"
        FEATURE_OFF = "FEATURE_OFF", "WhatsApp is not enabled"
        PAUSED = "PAUSED", "Reminders paused for this shop"

    event_id = models.UUIDField()  # the OutboxEvent
    event_code = models.CharField(max_length=40)
    recipient = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="+")
    retailer = models.ForeignKey(
        "retailers.Retailer", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    channel = models.CharField(max_length=8, choices=Channel.choices)
    address = models.CharField(max_length=254, blank=True, default="")  # email or phone
    title = models.CharField(max_length=200)
    body = models.TextField()
    data = models.JSONField(default=dict)  # deep link, document link, template variables
    urgent = models.BooleanField(default=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    skip_reason = models.CharField(
        max_length=18, choices=SkipReason.choices, blank=True, default=""
    )
    send_after = models.DateTimeField(null=True, blank=True)  # held for quiet hours
    read_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    provider = models.CharField(max_length=30, blank=True, default="")
    provider_message_id = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "recipient", "channel"], name="uniq_notification_delivery"
            )
        ]
        indexes = [
            models.Index(
                fields=["tenant", "recipient", "channel", "read_at"], name="notification_inbox_idx"
            ),
            models.Index(fields=["tenant", "status", "created_at"], name="notification_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event_code} {self.channel} {self.status}"


class DeliveryAttempt(TenantScopedModel):
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="delivery_attempts"
    )
    attempt_no = models.PositiveSmallIntegerField()
    provider = models.CharField(max_length=30)
    status = models.CharField(max_length=8)  # SENT, FAILED
    response = models.JSONField(default=dict)
    error = models.CharField(max_length=500, blank=True, default="")
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["tenant", "notification"], name="attempt_notification_idx")]

    def __str__(self) -> str:
        return f"attempt {self.attempt_no} {self.status}"


class NotificationPreference(TenantScopedModel):
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="+")
    event_code = models.CharField(max_length=40)
    channel = models.CharField(max_length=8, choices=Channel.choices)
    enabled = models.BooleanField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "user", "event_code", "channel"], name="uniq_preference"
            )
        ]

    def __str__(self) -> str:
        return f"{self.event_code} {self.channel} {self.enabled}"


class DocumentLink(TenantScopedModel):
    """A link to one document that opens without signing in (ADR-048 item 8)."""

    class Kind(models.TextChoices):
        INVOICE = "INVOICE", "Invoice"
        CREDIT_NOTE = "CREDIT_NOTE", "Credit note"
        RECEIPT = "RECEIPT", "Receipt"
        REFUND_VOUCHER = "REFUND_VOUCHER", "Refund voucher"
        ORDER_CONFIRMATION = "ORDER_CONFIRMATION", "Order Confirmation"

    token_hash = models.CharField(max_length=64, unique=True)
    kind = models.CharField(max_length=18, choices=Kind.choices)
    object_id = models.UUIDField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    open_count = models.PositiveIntegerField(default=0)
    last_opened_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["tenant", "kind", "object_id"], name="document_link_idx")]

    def __str__(self) -> str:
        return f"{self.kind} {self.object_id}"


class ReminderPause(TenantScopedModel):
    """Payment reminders paused for one shop (``credit.manage``; ADR-048 item 10)."""

    retailer = models.ForeignKey("retailers.Retailer", on_delete=models.CASCADE, related_name="+")
    reason = models.CharField(max_length=300)
    until = models.DateField(null=True, blank=True)  # none: until resumed
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "retailer"],
                condition=Q(ended_at__isnull=True),
                name="one_open_reminder_pause",
            )
        ]

    def __str__(self) -> str:
        return f"pause {self.retailer_id}"


class WhatsAppSender(TenantScopedModel):
    """A distributor's own WhatsApp number (later; ADR-048 item 4). Without an active row the
    platform's number is used (configured in the environment)."""

    provider = models.CharField(max_length=30)
    phone_number = models.CharField(max_length=16)
    display_name = models.CharField(max_length=100)
    credentials = EncryptedTextField(blank=True, default="")
    is_active = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant"], condition=Q(is_active=True), name="one_active_whatsapp_sender"
            )
        ]

    def __str__(self) -> str:
        return f"{self.display_name} {self.phone_number}"


class Announcement(TenantScopedModel):
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=1000)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    send_whatsapp = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)  # when it was sent

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "is_active", "starts_at"], name="announcement_idx")
        ]

    def __str__(self) -> str:
        return self.title
