"""Order shapes shared by the shop and the distributor panel."""

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.orders.models import (
    BackorderAllocation,
    Fulfilment,
    FulfilmentLine,
    Order,
    OrderLine,
    OrderStatusHistory,
)
from apps.pricing.api.serializers import money, qty


class OrderLineSerializer(serializers.ModelSerializer[OrderLine]):
    product = serializers.UUIDField(source="product_id", read_only=True)
    ready_qty = serializers.SerializerMethodField(help_text="Held for the shop, not yet sent.")

    class Meta:
        model = OrderLine
        fields: tuple[str, ...] = (
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
        read_only_fields: tuple[str, ...] = fields

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


class FulfilmentLineSerializer(serializers.ModelSerializer[FulfilmentLine]):
    order_line = serializers.UUIDField(source="order_line_id", read_only=True)
    product = serializers.UUIDField(source="product_id", read_only=True)
    product_code = serializers.CharField(source="order_line.product_code", read_only=True)
    product_name = serializers.CharField(source="order_line.product_name", read_only=True)
    unit_code = serializers.CharField(source="order_line.unit_code", read_only=True)
    ordered_price = money(source="order_line.unit_price", read_only=True)

    class Meta:
        model = FulfilmentLine
        fields = (
            "id",
            "order_line",
            "product",
            "product_code",
            "product_name",
            "unit_code",
            "quantity",
            "qty_packed",
            "unit_price",
            "ordered_price",
            "price_source",
            "price_increased",
            "cancelled_by_retailer_at",
        )
        read_only_fields = fields


class FulfilmentSerializer(serializers.ModelSerializer[Fulfilment]):
    lines = FulfilmentLineSerializer(many=True, read_only=True)
    distance_km = serializers.SerializerMethodField(
        help_text="For its e-way bill: the distance given at dispatch, or before that the shop "
        "address's (null when unknown)."
    )

    def get_distance_km(self, obj: Fulfilment) -> int | None:
        if obj.distance_km is not None or obj.status != Fulfilment.Status.PACKED:
            return obj.distance_km
        from apps.compliance.ewaybill import address_distance

        return address_distance(obj)

    class Meta:
        model = Fulfilment
        fields: tuple[str, ...] = (
            "id",
            "number",
            "kind",
            "status",
            "created_at",
            "packed_at",
            "dispatched_at",
            "delivered_at",
            "vehicle_number",
            "transporter_name",
            "lr_number",
            "distance_km",
            "cancelled_reason",
            "lines",
        )
        read_only_fields: tuple[str, ...] = fields


class OrderInvoiceSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    number = serializers.CharField()
    invoice_date = serializers.DateField()
    grand_total = money()
    balance_due = money()
    payment_status = serializers.CharField()


class OrderSerializer(serializers.ModelSerializer[Order]):
    retailer = serializers.UUIDField(source="retailer_id", read_only=True)
    retailer_name = serializers.CharField(source="retailer.shop_name", read_only=True)
    lines = OrderLineSerializer(many=True, read_only=True)
    fulfilments = FulfilmentSerializer(many=True, read_only=True)
    hold_reason = serializers.ChoiceField(
        choices=Order.HoldReason.choices,
        allow_blank=True,
        read_only=True,
        help_text="Why it waits for approval; blank when it doesn't.",
    )
    history = HistorySerializer(many=True, read_only=True)
    items_to_follow = serializers.SerializerMethodField(
        help_text='Products still to be delivered ("N items to follow").'
    )
    invoices = OrderInvoiceSerializer(many=True, read_only=True)
    has_confirmation = serializers.SerializerMethodField(
        help_text="An Order Confirmation PDF exists (made at acceptance when the setting is on)."
    )

    def get_has_confirmation(self, order: Order) -> bool:
        return hasattr(order, "confirmation")

    @extend_schema_field(serializers.IntegerField())
    def get_items_to_follow(self, order: Order) -> int:
        return sum(
            1
            for line in order.lines.all()
            if line.qty_ordered - line.qty_cancelled - line.qty_delivered > 0
        )

    class Meta:
        model = Order
        fields: tuple[str, ...] = (
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
            "items_to_follow",
            "lines",
            "fulfilments",
            "invoices",
            "has_confirmation",
            "history",
        )
        read_only_fields: tuple[str, ...] = fields


class LineOnOrderSerializer(serializers.Serializer[Any]):
    quantity = qty()
    expected_date = serializers.DateField(allow_null=True, help_text="The earliest.")
    late = serializers.BooleanField()


class StaffOrderLineSerializer(OrderLineSerializer):
    """Staff also see, for a waiting line, how much of the product is on order and when it is
    expected (purchasing on; never the supplier or the price; not shown to shops yet)."""

    on_order = serializers.SerializerMethodField()

    class Meta(OrderLineSerializer.Meta):
        fields = (*OrderLineSerializer.Meta.fields, "on_order")
        read_only_fields = fields

    @extend_schema_field(LineOnOrderSerializer(allow_null=True))
    def get_on_order(self, line: OrderLine) -> dict[str, Any] | None:
        found = (self.context.get("on_order") or {}).get(line.product_id)
        if found is None or line.qty_backordered <= 0:
            return None
        return dict(LineOnOrderSerializer(found).data)


class StaffOrderSerializer(OrderSerializer):
    """The distributor's view adds the credit approval (not shown to the shop) and what is on
    order for waiting lines."""

    lines = StaffOrderLineSerializer(many=True, read_only=True)

    class Meta(OrderSerializer.Meta):
        fields = (*OrderSerializer.Meta.fields, "credit_approved_value")
        read_only_fields = fields


class OrderRowSerializer(serializers.ModelSerializer[Order]):
    """A row on the order board."""

    retailer = serializers.UUIDField(source="retailer_id", read_only=True)
    retailer_name = serializers.CharField(source="retailer.shop_name", read_only=True)
    hold_reason = serializers.ChoiceField(
        choices=Order.HoldReason.choices,
        allow_blank=True,
        read_only=True,
        help_text="Why it waits for approval; blank when it doesn't.",
    )
    line_count = serializers.IntegerField(read_only=True)
    items_to_follow = serializers.IntegerField(read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "number",
            "status",
            "items_to_follow",
            "backorder_state",
            "hold_reason",
            "retailer",
            "retailer_name",
            "placed_via",
            "placed_by_label",
            "placed_at",
            "grand_total",
            "line_count",
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


class StaffPlaceOrderSerializer(PlaceOrderSerializer):
    retailer = serializers.UUIDField()


# --- Distributor actions -------------------------------------------------------------------------


class ReasonSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class RequiredReasonSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=500)


class LineQuantitySerializer(serializers.Serializer[Any]):
    line = serializers.UUIDField()
    quantity = qty(min_value=0)


class AdditionSerializer(serializers.Serializer[Any]):
    product = serializers.UUIDField()
    quantity = qty(min_value=0)


class ModifyOrderSerializer(serializers.Serializer[Any]):
    lines = LineQuantitySerializer(many=True, required=False, default=list)
    additions = AdditionSerializer(many=True, required=False, default=list)
    override_reason = serializers.CharField(
        max_length=300,
        allow_blank=True,
        required=False,
        default="",
        help_text="credit.manage only: accept going over the credit limit (audited).",
    )


class PackSerializer(serializers.Serializer[Any]):
    lines = LineQuantitySerializer(
        many=True,
        required=False,
        default=list,
        help_text="Packed quantity per shipment line; lines left out are packed in full.",
    )


class DispatchSerializer(serializers.Serializer[Any]):
    vehicle_number = serializers.CharField(max_length=20, allow_blank=True, default="")
    transporter_name = serializers.CharField(max_length=120, allow_blank=True, default="")
    lr_number = serializers.CharField(max_length=40, allow_blank=True, default="")
    distance_km = serializers.IntegerField(
        min_value=1,
        max_value=4000,
        required=False,
        allow_null=True,
        default=None,
        help_text="Road distance for the e-way bill; default: the shop address's.",
    )


class CancelShipmentSerializer(serializers.Serializer[Any]):
    to_backorder = serializers.BooleanField(
        help_text="Put the quantities back on backorder (true) or cancel them (false)."
    )
    reason = serializers.CharField(max_length=300)


class OrderCountsSerializer(serializers.Serializer[Any]):
    new = serializers.IntegerField()
    on_hold = serializers.IntegerField()
    backorders = serializers.IntegerField()
    in_progress = serializers.IntegerField()
    proposals = serializers.IntegerField(help_text="Backorder allocations to confirm.")
    to_pack = serializers.IntegerField()


class FulfilmentRowSerializer(serializers.ModelSerializer[Fulfilment]):
    order = serializers.UUIDField(source="order_id", read_only=True)
    order_number = serializers.CharField(source="order.number", read_only=True)
    retailer_name = serializers.CharField(source="order.retailer.shop_name", read_only=True)
    line_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Fulfilment
        fields = (
            "id",
            "number",
            "kind",
            "status",
            "order",
            "order_number",
            "retailer_name",
            "created_at",
            "packed_at",
            "dispatched_at",
            "line_count",
        )
        read_only_fields = fields


class FulfilmentDetailSerializer(FulfilmentSerializer):
    order = serializers.UUIDField(source="order_id", read_only=True)
    order_number = serializers.CharField(source="order.number", read_only=True)
    retailer_name = serializers.CharField(source="order.retailer.shop_name", read_only=True)
    shipping_address = serializers.JSONField(source="order.shipping_address", read_only=True)
    retailer_note = serializers.CharField(source="order.retailer_note", read_only=True)

    class Meta(FulfilmentSerializer.Meta):
        fields = (
            *FulfilmentSerializer.Meta.fields,
            "order",
            "order_number",
            "retailer_name",
            "shipping_address",
            "retailer_note",
        )
        read_only_fields = fields


# --- Backorders ----------------------------------------------------------------------------------


class BackorderGroupSerializer(serializers.Serializer[Any]):
    product_id = serializers.UUIDField()
    product_code = serializers.CharField()
    product_name = serializers.CharField()
    unit_code = serializers.CharField()
    waiting = qty(help_text="Total quantity shops wait for.")
    lines = serializers.IntegerField()
    oldest_placed_at = serializers.DateTimeField()
    available = qty(help_text="Free stock that could be allocated now.")
    proposed = qty(help_text="Held for proposals awaiting confirmation.")
    skipped_credit = serializers.IntegerField(help_text="Waiting lines of shops over the limit.")
    blocked = serializers.IntegerField(
        help_text="Waiting lines of blocked shops (never allocated)."
    )
    approved_over_limit = serializers.IntegerField(
        help_text="Waiting lines on orders approved from a credit hold."
    )


class WaitingLineSerializer(serializers.ModelSerializer[OrderLine]):
    order = serializers.UUIDField(source="order_id", read_only=True)
    order_number = serializers.CharField(source="order.number", read_only=True)
    placed_at = serializers.DateTimeField(source="order.placed_at", read_only=True)
    retailer = serializers.UUIDField(source="order.retailer_id", read_only=True)
    retailer_name = serializers.CharField(source="order.retailer.shop_name", read_only=True)
    over_credit_limit = serializers.SerializerMethodField()
    approved_over_limit = serializers.SerializerMethodField(
        help_text="The order was approved from a credit hold: its backorders are covered."
    )
    shop_blocked = serializers.SerializerMethodField(help_text="Blocked shops never get stock.")

    class Meta:
        model = OrderLine
        fields = (
            "id",
            "order",
            "order_number",
            "placed_at",
            "retailer",
            "retailer_name",
            "product_code",
            "qty_ordered",
            "qty_backordered",
            "unit_price",
            "over_credit_limit",
            "approved_over_limit",
            "shop_blocked",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.BooleanField())
    def get_approved_over_limit(self, line: OrderLine) -> bool:
        return line.order.credit_approved_value is not None

    @extend_schema_field(serializers.BooleanField())
    def get_shop_blocked(self, line: OrderLine) -> bool:
        return bool(line.order.retailer.status == "BLOCKED")

    @extend_schema_field(serializers.BooleanField())
    def get_over_credit_limit(self, line: OrderLine) -> bool:
        return getattr(line, "last_allocation_status", None) == "SKIPPED_CREDIT"


class AllocationSerializer(serializers.ModelSerializer[BackorderAllocation]):
    order = serializers.UUIDField(source="order_line.order_id", read_only=True)
    order_number = serializers.CharField(source="order_line.order.number", read_only=True)
    retailer_name = serializers.CharField(
        source="order_line.order.retailer.shop_name", read_only=True
    )
    order_line = serializers.UUIDField(source="order_line_id", read_only=True)
    product = serializers.UUIDField(source="product_id", read_only=True)
    product_code = serializers.CharField(source="order_line.product_code", read_only=True)
    product_name = serializers.CharField(source="order_line.product_name", read_only=True)
    fulfilment = serializers.UUIDField(source="fulfilment_id", read_only=True, allow_null=True)

    class Meta:
        model = BackorderAllocation
        fields = (
            "id",
            "status",
            "trigger",
            "quantity",
            "order",
            "order_number",
            "retailer_name",
            "order_line",
            "product",
            "product_code",
            "product_name",
            "fulfilment",
            "note",
            "created_at",
            "decided_at",
        )
        read_only_fields = fields


class AllocationAmountSerializer(serializers.Serializer[Any]):
    order_line = serializers.UUIDField()
    quantity = qty()


class AllocateSerializer(serializers.Serializer[Any]):
    product = serializers.UUIDField()
    allocations = AllocationAmountSerializer(
        many=True, required=False, default=list, help_text="Chosen lines; empty with auto."
    )
    auto = serializers.BooleanField(
        default=False, help_text="Offer the free stock to waiting orders, oldest first."
    )
    override_reason = serializers.CharField(
        max_length=300,
        allow_blank=True,
        required=False,
        default="",
        help_text="credit.manage only: allocate to a shop over its credit limit (audited).",
    )


class ConfirmAllocationsSerializer(serializers.Serializer[Any]):
    allocations = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=200)
