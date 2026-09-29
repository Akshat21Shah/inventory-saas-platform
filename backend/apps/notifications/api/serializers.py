"""Notification API shapes (validation and representation only)."""

from typing import Any

from rest_framework import serializers

from apps.accounts.models import LANGUAGE_CHOICES
from apps.notifications.models import (
    Announcement,
    Audience,
    Channel,
    DeliveryAttempt,
    DocumentLink,
    Notification,
    Recipient,
    ReminderPause,
    WhatsAppCategory,
)


class InboxItemSerializer(serializers.ModelSerializer[Notification]):
    path = serializers.SerializerMethodField()
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "event_code", "title", "body", "path", "is_read", "read_at", "created_at"]

    def get_path(self, obj: Notification) -> str:
        return str(obj.data.get("path", ""))

    def get_is_read(self, obj: Notification) -> bool:
        return obj.read_at is not None


class UnreadCountSerializer(serializers.Serializer[Any]):
    unread = serializers.IntegerField()


class MarkedReadSerializer(serializers.Serializer[Any]):
    marked = serializers.IntegerField()


# --- Rules --------------------------------------------------------------------------------------


class RuleSerializer(serializers.Serializer[Any]):
    recipient = serializers.ChoiceField(choices=Recipient.choices)
    permission = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    channels = serializers.ListField(
        child=serializers.ChoiceField(choices=Channel.choices), max_length=4
    )
    enabled = serializers.BooleanField(default=True)
    compulsory = serializers.BooleanField(default=False)
    is_default = serializers.BooleanField(read_only=True)


class RulesUpdateSerializer(serializers.Serializer[Any]):
    rules = RuleSerializer(many=True)


class WhatsAppEstimateSerializer(serializers.Serializer[Any]):
    enabled = serializers.BooleanField()
    messages_30_days = serializers.IntegerField()
    price = serializers.DecimalField(max_digits=10, decimal_places=4, allow_null=True)
    cost_30_days = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)


class EventRulesSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    group = serializers.CharField()
    urgent = serializers.BooleanField()
    category = serializers.ChoiceField(choices=WhatsAppCategory.choices)
    shop_facing = serializers.BooleanField()
    rules = RuleSerializer(many=True)
    customised = serializers.BooleanField()
    whatsapp = WhatsAppEstimateSerializer()


class ShopConsentCountSerializer(serializers.Serializer[Any]):
    opted_in = serializers.IntegerField()
    shops = serializers.IntegerField()


class PermissionChoiceSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    description = serializers.CharField()


class RulesMatrixSerializer(serializers.Serializer[Any]):
    events = EventRulesSerializer(many=True)
    recipients = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        help_text="Channels each recipient can use.",
    )
    whatsapp_feature_enabled = serializers.BooleanField()
    prices_set = serializers.BooleanField()
    whatsapp_cost_30_days = serializers.DecimalField(
        max_digits=14, decimal_places=2, allow_null=True
    )
    shops = ShopConsentCountSerializer()
    permissions = PermissionChoiceSerializer(
        many=True, help_text="For 'Staff who can…' rules (any staff member's permissions)."
    )


# --- Texts --------------------------------------------------------------------------------------


class TextSerializer(serializers.Serializer[Any]):
    audience = serializers.ChoiceField(
        choices=Audience.choices, help_text="Whose words: the shop's or the office's."
    )
    channel = serializers.ChoiceField(choices=Channel.choices)
    subject = serializers.CharField(allow_blank=True)
    body = serializers.CharField()
    source = serializers.ChoiceField(  # type: ignore[assignment]
        choices=["tenant", "platform", "catalogue"]
    )
    editable = serializers.BooleanField()
    variables = serializers.ListField(child=serializers.CharField())


class TextInputSerializer(serializers.Serializer[Any]):
    audience = serializers.ChoiceField(choices=Audience.choices, default=Audience.SHOP)
    locale = serializers.ChoiceField(choices=LANGUAGE_CHOICES, default="en")
    subject = serializers.CharField(max_length=200, allow_blank=True, default="")
    body = serializers.CharField(max_length=2000)


class TextPreviewInputSerializer(TextInputSerializer):
    event = serializers.CharField(max_length=40)
    channel = serializers.ChoiceField(choices=Channel.choices)


class TextPreviewSerializer(serializers.Serializer[Any]):
    subject = serializers.CharField(allow_blank=True)
    body = serializers.CharField()


class PlatformTextInputSerializer(TextInputSerializer):
    whatsapp_template_name = serializers.CharField(max_length=100, required=False, default="")
    whatsapp_language = serializers.CharField(max_length=10, required=False, default="")
    whatsapp_category = serializers.ChoiceField(
        choices=WhatsAppCategory.choices, required=False, allow_blank=True, default=""
    )


# --- Delivery log -------------------------------------------------------------------------------


class DeliveryAttemptSerializer(serializers.ModelSerializer[DeliveryAttempt]):
    class Meta:
        model = DeliveryAttempt
        fields = ["attempt_no", "provider", "status", "error", "duration_ms", "created_at"]


class DeliveryRowSerializer(serializers.ModelSerializer[Notification]):
    recipient_name = serializers.SerializerMethodField()
    shop_name = serializers.CharField(source="retailer.shop_name", default="", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "event_code",
            "channel",
            "status",
            "skip_reason",
            "recipient_name",
            "shop_name",
            "address",
            "title",
            "attempts",
            "last_error",
            "send_after",
            "sent_at",
            "created_at",
        ]

    def get_recipient_name(self, obj: Notification) -> str:
        user = obj.recipient
        return user.full_name or user.email or user.phone or ""


class DeliveryDetailSerializer(DeliveryRowSerializer):
    delivery_attempts = DeliveryAttemptSerializer(many=True, read_only=True)

    class Meta(DeliveryRowSerializer.Meta):
        fields = [*DeliveryRowSerializer.Meta.fields, "body", "provider", "delivery_attempts"]


class DeliveryCountsSerializer(serializers.Serializer[Any]):
    PENDING = serializers.IntegerField()
    SENDING = serializers.IntegerField()
    SENT = serializers.IntegerField()
    FAILED = serializers.IntegerField()
    SKIPPED = serializers.IntegerField()


class PlatformFailureSerializer(DeliveryRowSerializer):
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    tenant_id = serializers.UUIDField(read_only=True)

    class Meta(DeliveryRowSerializer.Meta):
        fields = [*DeliveryRowSerializer.Meta.fields, "tenant_id", "tenant_name"]

    def get_recipient_name(self, obj: Notification) -> str:
        return ""  # other tenants' people stay out of the platform list


# --- Announcements, links, pauses, consent -----------------------------------------------------


class AnnouncementSerializer(serializers.ModelSerializer[Announcement]):
    class Meta:
        model = Announcement
        fields = [
            "id",
            "title",
            "body",
            "starts_at",
            "ends_at",
            "is_active",
            "send_whatsapp",
            "published_at",
            "created_at",
        ]
        read_only_fields = ["id", "published_at", "created_at"]


class ShopAnnouncementSerializer(serializers.ModelSerializer[Announcement]):
    class Meta:
        model = Announcement
        fields = ["id", "title", "body", "starts_at", "ends_at"]


class DocumentLinkRowSerializer(serializers.ModelSerializer[DocumentLink]):
    is_live = serializers.SerializerMethodField()

    class Meta:
        model = DocumentLink
        fields = [
            "id",
            "kind",
            "object_id",
            "expires_at",
            "revoked_at",
            "open_count",
            "last_opened_at",
            "created_at",
            "is_live",
        ]

    def get_is_live(self, obj: DocumentLink) -> bool:
        from django.utils import timezone

        return obj.revoked_at is None and obj.expires_at > timezone.now()


class DocumentRefSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(choices=DocumentLink.Kind.choices)
    object_id = serializers.UUIDField()


class RevokedSerializer(serializers.Serializer[Any]):
    revoked = serializers.IntegerField()


class ReminderPauseSerializer(serializers.ModelSerializer[ReminderPause]):
    class Meta:
        model = ReminderPause
        fields = ["id", "reason", "until", "created_at"]


class ReminderPauseInputSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=300)
    until = serializers.DateField(required=False, allow_null=True, default=None)


class ReminderPauseStateSerializer(serializers.Serializer[Any]):
    pause = ReminderPauseSerializer(allow_null=True)


class StaffConsentInputSerializer(serializers.Serializer[Any]):
    agreed = serializers.BooleanField()
    confirmed = serializers.BooleanField(
        default=False, help_text="Staff confirm the shop agreed (needed to opt in)."
    )


class ConsentStateSerializer(serializers.Serializer[Any]):
    opted_in = serializers.BooleanField()
    source = serializers.CharField(allow_blank=True)  # type: ignore[assignment]
    opted_in_at = serializers.DateTimeField(allow_null=True)
    opted_out_at = serializers.DateTimeField(allow_null=True)
    prompt = serializers.BooleanField(help_text="Show the one-time question after sign-in.")
    whatsapp_available = serializers.BooleanField(
        help_text="The distributor sends WhatsApp messages at all."
    )


class ShopConsentInputSerializer(serializers.Serializer[Any]):
    agreed = serializers.BooleanField()


# --- Preferences ----------------------------------------------------------------------------


class PreferenceChannelSerializer(serializers.Serializer[Any]):
    channel = serializers.ChoiceField(choices=Channel.choices)
    enabled = serializers.BooleanField()
    locked = serializers.BooleanField()


class PreferenceRowSerializer(serializers.Serializer[Any]):
    event = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    group = serializers.CharField()
    compulsory = serializers.BooleanField()
    channels = PreferenceChannelSerializer(many=True)


class PreferenceInputSerializer(serializers.Serializer[Any]):
    event = serializers.CharField(max_length=40)
    channel = serializers.ChoiceField(choices=Channel.choices)
    enabled = serializers.BooleanField()


class RateChangeSerializer(serializers.Serializer[Any]):
    product_id = serializers.UUIDField()
    product = serializers.CharField()
    code = serializers.CharField()
    effective_from = serializers.DateField()
    old_rate = serializers.DecimalField(max_digits=6, decimal_places=3)
    new_rate = serializers.DecimalField(max_digits=6, decimal_places=3)
