from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.insights.models import Segment, ShopActivity, ShopContact


class ActivityFilterSerializer(serializers.Serializer[object]):
    segment = serializers.ChoiceField(
        choices=Segment.choices, required=False, allow_blank=True, default=""
    )
    salesperson = serializers.UUIDField(required=False, allow_null=True, default=None)
    search = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    win_back = serializers.BooleanField(
        required=False, default=False, help_text="Only shops to win back (ADR-056 item 3)."
    )


class ShopActivitySerializer(serializers.ModelSerializer[ShopActivity]):
    """A shop's ordering pattern. Values (order totals incl. GST) are null without a sales-report
    permission (``context["values"]``)."""

    retailer_id = serializers.UUIDField(read_only=True)
    retailer_code = serializers.CharField(source="retailer.code", read_only=True)
    shop_name = serializers.CharField(source="retailer.shop_name", read_only=True)
    owner_name = serializers.CharField(source="retailer.owner_name", read_only=True)
    mobile = serializers.CharField(source="retailer.mobile", read_only=True)
    shop_status = serializers.CharField(source="retailer.status", read_only=True)
    salesperson_name = serializers.SerializerMethodField()
    value_90 = serializers.SerializerMethodField()
    value_prev_90 = serializers.SerializerMethodField()
    last_contact_outcome = serializers.SerializerMethodField()
    last_contact_by = serializers.SerializerMethodField()

    class Meta:
        model = ShopActivity
        fields = [
            "retailer_id",
            "retailer_code",
            "shop_name",
            "owner_name",
            "mobile",
            "shop_status",
            "salesperson_name",
            "segment",
            "computed_at",
            "first_order_date",
            "last_order_date",
            "days_since_last",
            "usual_gap_days",
            "orders_90",
            "orders_prev_90",
            "value_90",
            "value_prev_90",
            "last_contact_at",
            "last_contact_outcome",
            "last_contact_by",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_salesperson_name(self, row: ShopActivity) -> str | None:
        person = row.retailer.salesperson
        return (person.full_name or person.email) if person else None

    def _value(self, amount: Any) -> str | None:
        return str(amount) if self.context.get("values") else None

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True))
    def get_value_90(self, row: ShopActivity) -> str | None:
        return self._value(row.value_90)

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True))
    def get_value_prev_90(self, row: ShopActivity) -> str | None:
        return self._value(row.value_prev_90)

    @extend_schema_field(
        serializers.ChoiceField(choices=ShopContact.Outcome.choices, allow_null=True)
    )
    def get_last_contact_outcome(self, row: ShopActivity) -> str | None:
        return getattr(row, "last_outcome", None)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_last_contact_by(self, row: ShopActivity) -> str | None:
        return getattr(row, "last_contact_by", None) or None


class ShopContactSerializer(serializers.ModelSerializer[ShopContact]):
    by_name = serializers.SerializerMethodField()

    class Meta:
        model = ShopContact
        fields = ["id", "created_at", "channel", "outcome", "note", "by_name"]
        read_only_fields = fields

    def get_by_name(self, row: ShopContact) -> str:
        return row.by.full_name or row.by.email or ""


class ShopContactInputSerializer(serializers.Serializer[object]):
    channel = serializers.ChoiceField(choices=ShopContact.Channel.choices)
    outcome = serializers.ChoiceField(choices=ShopContact.Outcome.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)


class ShopActivityDetailSerializer(serializers.Serializer[object]):
    """A shop's activity (null until first worked out) and its latest contacts."""

    activity = ShopActivitySerializer(allow_null=True)
    contacts = ShopContactSerializer(many=True)


class ActivityRefreshSerializer(serializers.Serializer[object]):
    status = serializers.CharField(help_text="QUEUED: worked out in the background.")
