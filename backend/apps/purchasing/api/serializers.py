from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Supplier, SupplierProduct
from common.dates import today_ist


class SupplierFilterSerializer(serializers.Serializer[Any]):
    search = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    active = serializers.BooleanField(required=False, allow_null=True, default=None)


class SupplierListSerializer(serializers.ModelSerializer[Supplier]):
    state_code = serializers.CharField(source="state_id", allow_null=True, read_only=True)
    product_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Supplier
        fields = [
            "id",
            "code",
            "name",
            "gstin",
            "state_code",
            "contact_name",
            "phone",
            "email",
            "city",
            "lead_time_days",
            "is_active",
            "product_count",
        ]
        read_only_fields = fields


class SupplierDetailSerializer(SupplierListSerializer):
    state_name = serializers.CharField(source="state.name", allow_null=True, read_only=True)

    class Meta(SupplierListSerializer.Meta):
        fields = [
            *SupplierListSerializer.Meta.fields,
            "state_name",
            "address_line1",
            "address_line2",
            "pincode",
            "payment_terms_days",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class SupplierWriteSerializer(serializers.Serializer[Any]):
    """Validation of shapes only; the service checks GSTINs, phone numbers and the rest."""

    name = serializers.CharField(max_length=200)
    gstin = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True)
    state_code = serializers.CharField(
        max_length=2, required=False, allow_blank=True, allow_null=True
    )
    contact_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    email = serializers.CharField(max_length=254, required=False, allow_blank=True)
    address_line1 = serializers.CharField(max_length=200, required=False, allow_blank=True)
    address_line2 = serializers.CharField(max_length=200, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    pincode = serializers.CharField(max_length=6, required=False, allow_blank=True)
    payment_terms_days = serializers.IntegerField(required=False, min_value=0, max_value=365)
    lead_time_days = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=365
    )
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)

    def to_service(self) -> dict[str, Any]:
        data = dict(self.validated_data)
        if "state_code" in data:
            data["state_id"] = data.pop("state_code") or None
        return data


class SupplierProductSerializer(serializers.ModelSerializer[SupplierProduct]):
    """``last_unit_cost`` is left out without ``costs.view`` (``context["costs"]``)."""

    supplier_id = serializers.UUIDField(read_only=True)
    supplier_code_number = serializers.CharField(source="supplier.code", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    product_id = serializers.UUIDField(read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = SupplierProduct
        fields = [
            "id",
            "supplier_id",
            "supplier_code_number",
            "supplier_name",
            "product_id",
            "product_code",
            "product_name",
            "is_preferred",
            "supplier_code",
            "lead_time_days",
            "pack_size",
            "last_unit_cost",
        ]
        read_only_fields = fields

    def to_representation(self, instance: SupplierProduct) -> dict[str, Any]:
        data = super().to_representation(instance)
        if not self.context.get("costs"):
            data["last_unit_cost"] = None
        return data


class LinkSerializer(serializers.Serializer[Any]):
    supplier_id = serializers.UUIDField()
    is_preferred = serializers.BooleanField(default=False)
    supplier_code = serializers.CharField(
        max_length=40, required=False, allow_blank=True, default=""
    )
    lead_time_days = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=1, max_value=365
    )
    pack_size = serializers.DecimalField(
        max_digits=14, decimal_places=3, required=False, allow_null=True, default=None
    )


class ProductSuppliersSerializer(serializers.Serializer[Any]):
    links = LinkSerializer(many=True, max_length=20)  # type: ignore[call-arg]


class SetPreferredSerializer(serializers.Serializer[Any]):
    product_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=1000
    )


class PreferredChangedSerializer(serializers.Serializer[Any]):
    changed = serializers.IntegerField()


class ReceiptSupplierNameSerializer(serializers.Serializer[Any]):
    name = serializers.CharField()
    receipts = serializers.IntegerField()
    last_date = serializers.DateField(allow_null=True)
    match_id = serializers.UUIDField(allow_null=True)
    match_name = serializers.CharField()


class ReceiptSupplierChoiceSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=200)
    supplier_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    new = serializers.BooleanField(default=False, help_text="Make a new supplier with this name.")


class ConfirmReceiptSuppliersSerializer(serializers.Serializer[Any]):
    choices = ReceiptSupplierChoiceSerializer(many=True, min_length=1, max_length=500)  # type: ignore[call-arg]


class ConfirmResultSerializer(serializers.Serializer[Any]):
    suppliers_created = serializers.IntegerField()
    receipts_linked = serializers.IntegerField()


# --- Purchase orders ------------------------------------------------------------------------------


def _hide_costs(data: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        data[key] = None
    return data


class PurchaseOrderFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(
        choices=PurchaseOrder.Status.choices, required=False, allow_blank=True, default=""
    )
    supplier = serializers.UUIDField(required=False, allow_null=True, default=None)
    late = serializers.BooleanField(required=False, default=False)
    search = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)


class PurchaseOrderListSerializer(serializers.ModelSerializer[PurchaseOrder]):
    """Money only with ``costs.view`` (``context["costs"]``)."""

    supplier_id = serializers.UUIDField(read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    line_count = serializers.IntegerField(read_only=True)
    is_late = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "number",
            "status",
            "supplier_id",
            "supplier_name",
            "expected_date",
            "is_late",
            "line_count",
            "subtotal",
            "revision",
            "changed_since_sent",
            "sent_at",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.BooleanField())
    def get_is_late(self, order: PurchaseOrder) -> bool:
        return bool(
            order.status in ("SENT", "PARTLY_RECEIVED")
            and order.expected_date
            and order.expected_date < today_ist()
        )

    def to_representation(self, instance: PurchaseOrder) -> dict[str, Any]:
        data = super().to_representation(instance)
        return data if self.context.get("costs") else _hide_costs(data, ("subtotal",))


class PurchaseOrderLineSerializer(serializers.ModelSerializer[PurchaseOrderLine]):
    product_id = serializers.UUIDField(read_only=True)
    entered_cost = serializers.SerializerMethodField()
    due = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)

    class Meta:
        model = PurchaseOrderLine
        fields = [
            "id",
            "line_no",
            "product_id",
            "product_code",
            "product_name",
            "supplier_code",
            "unit_code",
            "entered_unit",
            "entered_qty",
            "quantity",
            "entered_cost",
            "unit_cost",
            "gst_rate",
            "line_total",
            "qty_received",
            "qty_cancelled",
            "due",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=4, allow_null=True))
    def get_entered_cost(self, line: PurchaseOrderLine) -> str | None:
        """The cost per unit as entered (per pack for a pack line)."""
        if line.unit_cost is None:
            return None
        factor = line.quantity / line.entered_qty if line.entered_qty else Decimal("1")
        return f"{(line.unit_cost * factor).quantize(Decimal('0.0001')):.4f}"

    def to_representation(self, instance: PurchaseOrderLine) -> dict[str, Any]:
        data = super().to_representation(instance)
        if self.context.get("costs"):
            return data
        return _hide_costs(data, ("entered_cost", "unit_cost", "line_total"))


class PurchaseOrderDetailSerializer(PurchaseOrderListSerializer):
    lines = serializers.SerializerMethodField()
    sent_by = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta(PurchaseOrderListSerializer.Meta):
        fields = [
            *PurchaseOrderListSerializer.Meta.fields,
            "notes",
            "estimated_tax",
            "supplier_snapshot",
            "sent_by",
            "closed_at",
            "closed_reason",
            "pdf_status",
            "lines",
            "actions",
        ]
        read_only_fields = fields

    @extend_schema_field(PurchaseOrderLineSerializer(many=True))
    def get_lines(self, order: PurchaseOrder) -> list[dict[str, Any]]:
        return list(
            PurchaseOrderLineSerializer(order.lines.all(), many=True, context=self.context).data
        )

    @extend_schema_field(serializers.CharField())
    def get_sent_by(self, order: PurchaseOrder) -> str:
        user = order.sent_by
        return (user.full_name or user.email or "") if user else ""

    @extend_schema_field(
        serializers.ListField(
            child=serializers.ChoiceField(choices=["edit", "send", "delete", "cancel", "close"])
        )
    )
    def get_actions(self, order: PurchaseOrder) -> list[str]:
        """What may be done next (the server checks again)."""
        received = any(line.qty_received > 0 for line in order.lines.all())
        if order.status == "DRAFT":
            return ["edit", "send", "delete", "cancel"]
        if order.status == "SENT" and not received:
            return ["edit", "send", "cancel"]
        if order.status == "PARTLY_RECEIVED":
            return ["close"]
        return []

    def to_representation(self, instance: PurchaseOrder) -> dict[str, Any]:
        data = super().to_representation(instance)
        return data if self.context.get("costs") else _hide_costs(data, ("estimated_tax",))


class OrderLineInputSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(required=False, allow_null=True, default=None)
    product_id = serializers.UUIDField()
    entered_unit = serializers.ChoiceField(
        choices=PurchaseOrderLine.EnteredUnit.choices, default="BASE"
    )
    entered_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    entered_cost = serializers.DecimalField(
        max_digits=14, decimal_places=4, required=False, allow_null=True, default=None
    )


class PurchaseOrderInputSerializer(serializers.Serializer[Any]):
    supplier_id = serializers.UUIDField()
    expected_date = serializers.DateField(required=False, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    lines = OrderLineInputSerializer(many=True, allow_empty=False, max_length=300)  # type: ignore[call-arg]


class SendResultSerializer(serializers.Serializer[Any]):
    order = PurchaseOrderDetailSerializer()
    share_link = serializers.CharField(help_text="A link to the supplier's copy, to share.")
    emailed = serializers.BooleanField(help_text="False: the supplier has no email address.")


class PurchaseOrderReasonSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")

