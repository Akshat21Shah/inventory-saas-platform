from typing import Any

from rest_framework import serializers

from apps.purchasing.models import Supplier, SupplierProduct


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
