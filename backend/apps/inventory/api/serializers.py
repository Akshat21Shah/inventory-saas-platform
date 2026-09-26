"""Inventory API shapes (PLAN §3.7). Cost fields are null unless the viewer has ``costs.view``
(context ``show_cost``, ADR-042). Business rules are checked in the services."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.api.serializers import first_ready_thumb, money_field, qty_field
from apps.catalog.models import Product
from apps.inventory import selectors
from apps.inventory.models import (
    AdjustmentReason,
    StockAdjustment,
    StockAdjustmentLine,
    StockAlert,
    StockInward,
    StockInwardLine,
    StockMovement,
    Warehouse,
)


def unit_cost_field(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=14, decimal_places=4, **kwargs)


def _cost(context: Mapping[str, Any], value: Decimal | None, places: int) -> str | None:
    if not context.get("show_cost") or value is None:
        return None
    return f"{value:.{places}f}"


def _person(user: Any) -> str:
    if user is None:
        return ""
    return str(user.full_name or user.email)


class StockUnitRefSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    allows_decimal = serializers.BooleanField()


class StockProductRefSerializer(serializers.ModelSerializer[Product]):
    unit = StockUnitRefSerializer(read_only=True)
    pack_unit = StockUnitRefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Product
        fields = ("id", "code", "name", "unit", "pack_unit", "pack_size")
        read_only_fields = fields


class WarehouseSerializer(serializers.ModelSerializer[Warehouse]):
    class Meta:
        model = Warehouse
        fields = (
            "id",
            "code",
            "name",
            "address_line1",
            "address_line2",
            "city",
            "pincode",
            "state",
            "is_default",
            "is_active",
        )
        read_only_fields = ("id", "code", "is_default", "is_active")


# --- Stock -------------------------------------------------------------------------------------


class StockRowSerializer(serializers.ModelSerializer[Product]):
    unit = StockUnitRefSerializer(read_only=True)
    pack_unit = StockUnitRefSerializer(read_only=True, allow_null=True)
    category = serializers.CharField(source="category.name", default="", read_only=True)
    brand = serializers.CharField(source="brand.name", default="", read_only=True)
    on_hand = qty_field(read_only=True)
    reserved = qty_field(read_only=True)
    available = qty_field(read_only=True)
    backordered = qty_field(read_only=True)
    status = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields: tuple[str, ...] = (
            "id",
            "code",
            "name",
            "unit",
            "pack_unit",
            "pack_size",
            "category",
            "brand",
            "is_active",
            "reorder_level",
            "on_hand",
            "reserved",
            "available",
            "backordered",
            "status",
            "thumbnail_url",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.ChoiceField(choices=selectors.STOCK_STATUS_CHOICES))
    def get_status(self, product: Any) -> str:
        return selectors.status_of(product.available, product.reorder_level)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_thumbnail_url(self, product: Product) -> str | None:
        return first_ready_thumb(product)


class MovementSerializer(serializers.ModelSerializer[StockMovement]):
    product = StockProductRefSerializer(read_only=True)
    unit_cost = serializers.SerializerMethodField()
    value = serializers.SerializerMethodField(method_name="get_movement_value")
    by = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = (
            "id",
            "created_at",
            "product",
            "movement_type",
            "quantity",
            "delta_on_hand",
            "delta_reserved",
            "on_hand_after",
            "reserved_after",
            "unit_cost",
            "value",
            "reference_type",
            "reference_id",
            "reference_number",
            "reason",
            "by",
        )
        read_only_fields = fields

    @extend_schema_field(unit_cost_field(allow_null=True))
    def get_unit_cost(self, movement: StockMovement) -> str | None:
        return _cost(self.context, movement.unit_cost, 4)

    @extend_schema_field(money_field(allow_null=True))
    def get_movement_value(self, movement: StockMovement) -> str | None:
        return _cost(self.context, movement.value, 2)

    @extend_schema_field(serializers.CharField())
    def get_by(self, movement: StockMovement) -> str:
        return _person(movement.created_by)


class AlertSerializer(serializers.ModelSerializer[StockAlert]):
    product = StockProductRefSerializer(read_only=True)

    class Meta:
        model = StockAlert
        fields = (
            "id",
            "product",
            "alert_type",
            "status",
            "opened_at",
            "resolved_at",
            "value_at_open",
        )
        read_only_fields = fields


class StockDetailSerializer(StockRowSerializer):
    barcodes = serializers.SerializerMethodField()
    open_alerts = serializers.SerializerMethodField()
    recent_movements = serializers.SerializerMethodField()
    cost_price = serializers.SerializerMethodField()

    class Meta(StockRowSerializer.Meta):
        fields = (
            *StockRowSerializer.Meta.fields,
            "barcodes",
            "cost_price",
            "open_alerts",
            "recent_movements",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_barcodes(self, product: Product) -> list[str]:
        return [b.barcode for b in product.barcodes.all()]

    @extend_schema_field(money_field(allow_null=True))
    def get_cost_price(self, product: Product) -> str | None:
        return _cost(self.context, product.cost_price, 2)

    @extend_schema_field(AlertSerializer(many=True))
    def get_open_alerts(self, product: Product) -> list[dict[str, Any]]:
        rows = selectors.alerts().filter(product=product)
        return list(AlertSerializer(rows, many=True).data)

    @extend_schema_field(MovementSerializer(many=True))
    def get_recent_movements(self, product: Product) -> list[dict[str, Any]]:
        rows = selectors.movements(selectors.MovementFilters(product_id=product.pk))[:20]
        return list(MovementSerializer(rows, many=True, context=self.context).data)


class LookupSerializer(StockRowSerializer):
    """A scanned or typed code: the product, its units and its stock."""


class ReorderLevelSerializer(serializers.Serializer[Any]):
    reorder_level = qty_field(min_value=Decimal("0"))


class SummarySerializer(serializers.Serializer[Any]):
    alerts = serializers.DictField(child=serializers.IntegerField())
    receipts_awaiting_cost = serializers.IntegerField(allow_null=True)


# --- Goods receipts ----------------------------------------------------------------------------


class ReceiptLineSerializer(serializers.ModelSerializer[StockInwardLine]):
    product = StockProductRefSerializer(read_only=True)
    entered_cost = serializers.SerializerMethodField()
    unit_cost = serializers.SerializerMethodField()
    line_cost = serializers.SerializerMethodField()

    class Meta:
        model = StockInwardLine
        fields = (
            "id",
            "line_no",
            "product",
            "entered_unit",
            "entered_qty",
            "quantity",
            "entered_cost",
            "unit_cost",
            "line_cost",
            "cost_status",
        )
        read_only_fields = fields

    @extend_schema_field(unit_cost_field(allow_null=True))
    def get_entered_cost(self, line: StockInwardLine) -> str | None:
        return _cost(self.context, line.entered_cost, 4)

    @extend_schema_field(unit_cost_field(allow_null=True))
    def get_unit_cost(self, line: StockInwardLine) -> str | None:
        return _cost(self.context, line.unit_cost, 4)

    @extend_schema_field(money_field(allow_null=True))
    def get_line_cost(self, line: StockInwardLine) -> str | None:
        return _cost(self.context, line.line_cost, 2)


class ReceiptSerializer(serializers.ModelSerializer[StockInward]):
    line_count = serializers.IntegerField(read_only=True)
    total_cost = serializers.SerializerMethodField()
    posted_by = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = StockInward
        fields: tuple[str, ...] = (
            "id",
            "number",
            "status",
            "supplier_name",
            "supplier_ref",
            "bill_number",
            "bill_date",
            "notes",
            "line_count",
            "total_cost",
            "cost_pending_lines",
            "posted_at",
            "posted_by",
            "created_at",
            "created_by",
        )
        read_only_fields = fields

    @extend_schema_field(money_field(allow_null=True))
    def get_total_cost(self, inward: StockInward) -> str | None:
        return _cost(self.context, inward.total_cost, 2)

    @extend_schema_field(serializers.CharField())
    def get_posted_by(self, inward: StockInward) -> str:
        return _person(inward.posted_by)

    @extend_schema_field(serializers.CharField())
    def get_created_by(self, inward: StockInward) -> str:
        return _person(inward.created_by)


class ReceiptDetailSerializer(ReceiptSerializer):
    lines = serializers.SerializerMethodField()

    class Meta(ReceiptSerializer.Meta):
        fields = (*ReceiptSerializer.Meta.fields, "lines")
        read_only_fields = fields

    @extend_schema_field(ReceiptLineSerializer(many=True))
    def get_lines(self, inward: StockInward) -> list[dict[str, Any]]:
        return list(ReceiptLineSerializer(inward.lines.all(), many=True, context=self.context).data)


class ReceiptLineInputSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(required=False, allow_null=True)
    product_id = serializers.UUIDField()
    entered_unit = serializers.ChoiceField(
        choices=StockInwardLine.EnteredUnit.choices, default="BASE"
    )
    entered_qty = qty_field()
    entered_cost = unit_cost_field(required=False, allow_null=True)


class ReceiptInputSerializer(serializers.Serializer[Any]):
    supplier_name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    supplier_ref = serializers.CharField(required=False, allow_blank=True, max_length=60)
    bill_number = serializers.CharField(required=False, allow_blank=True, max_length=60)
    bill_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    lines = ReceiptLineInputSerializer(many=True, allow_empty=False, max_length=500)  # type: ignore[call-arg]


class ReceiptCreateSerializer(ReceiptInputSerializer):
    post = serializers.BooleanField(default=False, help_text="Save and post in one step (phones).")


class CostInputSerializer(serializers.Serializer[Any]):
    line_id = serializers.UUIDField()
    entered_cost = unit_cost_field(min_value=Decimal("0"))


class CompleteCostsSerializer(serializers.Serializer[Any]):
    costs = CostInputSerializer(many=True, allow_empty=False, max_length=500)  # type: ignore[call-arg]


# --- Adjustments -------------------------------------------------------------------------------


class AdjustmentLineSerializer(serializers.ModelSerializer[StockAdjustmentLine]):
    product = StockProductRefSerializer(read_only=True)

    class Meta:
        model = StockAdjustmentLine
        fields = (
            "id",
            "line_no",
            "product",
            "mode",
            "entered_qty",
            "quantity_change",
            "on_hand_before",
        )
        read_only_fields = fields


class AdjustmentSerializer(serializers.ModelSerializer[StockAdjustment]):
    line_count = serializers.IntegerField(read_only=True)
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = StockAdjustment
        fields: tuple[str, ...] = (
            "id",
            "number",
            "reason_code",
            "note",
            "line_count",
            "created_at",
            "created_by",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_created_by(self, adjustment: StockAdjustment) -> str:
        return _person(adjustment.created_by)


class AdjustmentDetailSerializer(AdjustmentSerializer):
    lines = AdjustmentLineSerializer(many=True, read_only=True)
    unchanged = serializers.ListField(child=serializers.CharField(), read_only=True, default=list)

    class Meta(AdjustmentSerializer.Meta):
        fields = (*AdjustmentSerializer.Meta.fields, "lines", "unchanged")
        read_only_fields = fields


class AdjustmentLineInputSerializer(serializers.Serializer[Any]):
    product_id = serializers.UUIDField()
    mode = serializers.ChoiceField(choices=StockAdjustmentLine.Mode.choices)
    quantity = qty_field()


class AdjustmentInputSerializer(serializers.Serializer[Any]):
    reason_code = serializers.ChoiceField(choices=AdjustmentReason.choices)
    note = serializers.CharField(max_length=500)
    lines = AdjustmentLineInputSerializer(many=True, allow_empty=False, max_length=500)  # type: ignore[call-arg]


# --- Reports -----------------------------------------------------------------------------------


class LowStockRowSerializer(StockRowSerializer):
    shortfall = qty_field(read_only=True)

    class Meta(StockRowSerializer.Meta):
        fields = (*StockRowSerializer.Meta.fields, "shortfall")
        read_only_fields = fields


class LowStockSummarySerializer(serializers.Serializer[Any]):
    low_stock = serializers.IntegerField()
    without_reorder_level = serializers.IntegerField(
        help_text="Active products with no reorder level: they never show as low."
    )


class BucketSerializer(serializers.Serializer[Any]):
    name = serializers.CharField()
    value = money_field()
    products = serializers.IntegerField()
    missing_cost = serializers.IntegerField()


class ValuationSerializer(serializers.Serializer[Any]):
    total_value = money_field()
    products_valued = serializers.IntegerField()
    missing_cost = serializers.IntegerField()
    by_category = BucketSerializer(many=True)
    by_brand = BucketSerializer(many=True)


class ValuationRowSerializer(StockRowSerializer):
    cost_price = money_field(read_only=True, allow_null=True)
    value = serializers.SerializerMethodField(method_name="get_stock_value")

    class Meta(StockRowSerializer.Meta):
        fields = (*StockRowSerializer.Meta.fields, "cost_price", "value")
        read_only_fields = fields

    @extend_schema_field(money_field(allow_null=True))
    def get_stock_value(self, product: Product) -> str | None:
        value = selectors.product_value(product)
        return None if value is None else f"{value:.2f}"
