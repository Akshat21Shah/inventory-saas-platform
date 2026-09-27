"""Order shapes shared by the shop and the distributor panel."""

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.orders.models import Order, OrderLine, OrderStatusHistory
from apps.pricing.api.serializers import money, qty


class OrderLineSerializer(serializers.ModelSerializer[OrderLine]):
    product = serializers.UUIDField(source="product_id", read_only=True)
    ready_qty = serializers.SerializerMethodField(help_text="Held for the shop, not yet sent.")

    class Meta:
        model = OrderLine
        fields = (
            "id",
            "line_no",
            "product",
            "product_code",
            "product_name",
            "unit_code",
            "unit_price",
            "discount_per_unit",
            "gst_rate",
            "qty_ordered",
            "qty_pending",
            "qty_reserved",
            "qty_backordered",
            "qty_allocated",
            "qty_cancelled",
            "qty_dispatched",
            "qty_delivered",
            "ready_qty",
            "line_total",
        )
        read_only_fields = fields

    @extend_schema_field(qty())
    def get_ready_qty(self, line: OrderLine) -> str:
        return f"{line.qty_reserved + line.qty_allocated - line.qty_dispatched:.3f}"


class HistorySerializer(serializers.ModelSerializer[OrderStatusHistory]):
    by = serializers.SerializerMethodField()

    class Meta:
        model = OrderStatusHistory
        fields = (
            "id",
            "created_at",
            "event",
            "from_status",
            "to_status",
            "actor_type",
            "by",
            "note",
            "payload",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_by(self, row: OrderStatusHistory) -> str:
        if row.actor is None:
            return ""
        return str(row.actor.full_name or row.actor.email or row.actor.phone or "")


class OrderSerializer(serializers.ModelSerializer[Order]):
    retailer = serializers.UUIDField(source="retailer_id", read_only=True)
    retailer_name = serializers.CharField(source="retailer.shop_name", read_only=True)
    lines = OrderLineSerializer(many=True, read_only=True)
    history = HistorySerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "number",
            "status",
            "backorder_state",
            "hold_reason",
            "retailer",
            "retailer_name",
            "placed_via",
            "placed_by_label",
            "placed_at",
            "accepted_at",
            "closed_at",
            "shipping_address",
            "retailer_note",
            "prices_include_tax",
            "gross_total",
            "discount_total",
            "taxable_total",
            "tax_total",
            "round_off",
            "grand_total",
            "rejection_reason",
            "cancellation_reason",
            "lines",
            "history",
        )
        read_only_fields = fields


class PlaceOrderSerializer(serializers.Serializer[Any]):
    expected_total = money(help_text="The cart's expected_total: a price change is caught.")
    address = serializers.UUIDField(required=False, allow_null=True, default=None)
    note = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=500,
        help_text="Delivery instructions (landmark, timing).",
    )
