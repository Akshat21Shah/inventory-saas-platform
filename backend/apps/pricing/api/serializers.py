from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.api.serializers import RefSerializer, WarningSerializer
from apps.pricing.models import (
    DiscountRule,
    DiscountSlab,
    FreeGoodsScheme,
    PriceList,
    PriceListItem,
    RetailerPrice,
)


def money(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=14, decimal_places=2, **kwargs)


def qty(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=14, decimal_places=3, **kwargs)


class ProductRefSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()


class ShopRefSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    code = serializers.CharField()
    shop_name = serializers.CharField()


class PriceListSerializer(serializers.ModelSerializer[PriceList]):
    item_count = serializers.IntegerField(read_only=True, default=0)
    shop_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = PriceList
        fields = ("id", "name", "code", "description", "item_count", "shop_count", "created_at")
        read_only_fields = ("id", "item_count", "shop_count", "created_at")


class PriceListWriteSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=120)
    code = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    description = serializers.CharField(
        max_length=300, required=False, allow_blank=True, default=""
    )


class PriceListItemSerializer(serializers.ModelSerializer[PriceListItem]):
    product = ProductRefSerializer(read_only=True)
    base_price = money(source="product.base_price", read_only=True)
    unit = serializers.CharField(source="product.unit.code", read_only=True)

    class Meta:
        model = PriceListItem
        fields = ("product", "unit", "base_price", "price", "updated_at")
        read_only_fields = fields


class ItemInputSerializer(serializers.Serializer[Any]):
    product = serializers.UUIDField()
    price = money()


class ItemsUpsertSerializer(serializers.Serializer[Any]):
    items = ItemInputSerializer(many=True)


class ItemsUpsertResultSerializer(serializers.Serializer[Any]):
    changed = serializers.IntegerField()
    warnings = serializers.SerializerMethodField()

    @extend_schema_field(WarningSerializer(many=True))
    def get_warnings(self, obj: dict[str, Any]) -> list[Any]:
        return [
            {"code": w.code, "message": w.message, "details": w.details} for w in obj["warnings"]
        ]


class RetailerPriceSerializer(serializers.ModelSerializer[RetailerPrice]):
    retailer = ShopRefSerializer(read_only=True)
    product = ProductRefSerializer(read_only=True)
    base_price = money(source="product.base_price", read_only=True)

    class Meta:
        model = RetailerPrice
        fields = (
            "id",
            "retailer",
            "product",
            "base_price",
            "price",
            "note",
            "updated_at",
            "warnings",
        )
        read_only_fields = fields

    warnings = serializers.SerializerMethodField()

    @extend_schema_field(WarningSerializer(many=True))
    def get_warnings(self, obj: Any) -> list[Any]:
        """Only after a save (e.g. FREE_GOODS); empty when reading."""
        return [
            {"code": w.code, "message": w.message, "details": w.details}
            for w in self.context.get("warnings", [])
        ]


class RetailerPriceWriteSerializer(serializers.Serializer[Any]):
    retailer = serializers.UUIDField()
    product = serializers.UUIDField()
    price = money()
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class RetailerPriceUpdateSerializer(serializers.Serializer[Any]):
    price = money()
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class RetailerPriceFilterSerializer(serializers.Serializer[Any]):
    retailer = serializers.UUIDField(required=False)
    product = serializers.UUIDField(required=False)


class SlabSerializer(serializers.ModelSerializer[DiscountSlab]):
    class Meta:
        model = DiscountSlab
        fields = ("min_qty", "value")


class DiscountRuleSerializer(serializers.ModelSerializer[DiscountRule]):
    product = ProductRefSerializer(allow_null=True, read_only=True)
    category = RefSerializer(allow_null=True, read_only=True)
    brand = RefSerializer(allow_null=True, read_only=True)
    price_list = RefSerializer(allow_null=True, read_only=True)
    retailer = ShopRefSerializer(allow_null=True, read_only=True)
    slabs = SlabSerializer(many=True, read_only=True)

    class Meta:
        model = DiscountRule
        fields = (
            "id",
            "name",
            "discount_type",
            "value",
            "scope_type",
            "product",
            "category",
            "brand",
            "audience_type",
            "price_list",
            "retailer",
            "valid_from",
            "valid_to",
            "is_active",
            "slabs",
            "created_at",
            "updated_at",
            "warnings",
        )
        read_only_fields = fields

    warnings = serializers.SerializerMethodField()

    @extend_schema_field(WarningSerializer(many=True))
    def get_warnings(self, obj: Any) -> list[Any]:
        """Only after a save (e.g. FREE_GOODS); empty when reading."""
        return [
            {"code": w.code, "message": w.message, "details": w.details}
            for w in self.context.get("warnings", [])
        ]


class SlabInputSerializer(serializers.Serializer[Any]):
    min_qty = qty()
    value = money()


class DiscountRuleWriteSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=120)
    discount_type = serializers.ChoiceField(choices=DiscountRule.Type.choices)
    value = money(required=False, default=0)
    scope_type = serializers.ChoiceField(choices=DiscountRule.Scope.choices)
    product = serializers.UUIDField(required=False, allow_null=True, default=None)
    category = serializers.UUIDField(required=False, allow_null=True, default=None)
    brand = serializers.UUIDField(required=False, allow_null=True, default=None)
    audience_type = serializers.ChoiceField(choices=DiscountRule.Audience.choices)
    price_list = serializers.UUIDField(required=False, allow_null=True, default=None)
    retailer = serializers.UUIDField(required=False, allow_null=True, default=None)
    valid_from = serializers.DateField(required=False, allow_null=True, default=None)
    valid_to = serializers.DateField(required=False, allow_null=True, default=None)
    is_active = serializers.BooleanField(required=False, default=True)
    slabs = SlabInputSerializer(many=True, required=False, default=list)


class DiscountRuleFilterSerializer(serializers.Serializer[Any]):
    active = serializers.BooleanField(required=False, allow_null=True, default=None)


FK = {
    "product": "product_id",
    "category": "category_id",
    "brand": "brand_id",
    "price_list": "price_list_id",
    "retailer": "retailer_id",
}


def rule_fields(data: dict[str, Any]) -> dict[str, Any]:
    return {FK.get(k, k): v for k, v in data.items() if k != "slabs"}


class AppliedDiscountSerializer(serializers.Serializer[Any]):
    rule_id = serializers.UUIDField()
    rule_name = serializers.CharField()
    discount_type = serializers.CharField()
    value = money()
    slab_min_qty = qty(allow_null=True)
    amount = money()


class PriceResultSerializer(serializers.Serializer[Any]):
    product_id = serializers.UUIDField()
    qty = qty()
    base_price = money()
    unit_price = money()
    price_source = serializers.ChoiceField(choices=["SPECIAL", "PRICE_LIST", "BASE"])
    discounts = AppliedDiscountSerializer(many=True, help_text="Every rule applied, in order.")
    discount_total = money()
    discount_percent = serializers.DecimalField(max_digits=6, decimal_places=2)
    gross = money()
    line_net = money()
    net_unit_price = money()
    gst_rate = serializers.DecimalField(max_digits=6, decimal_places=3)
    cess_rate = serializers.DecimalField(max_digits=6, decimal_places=3)
    prices_include_gst = serializers.BooleanField()
    on = serializers.DateField()


class PreviewLineSerializer(serializers.Serializer[Any]):
    product = serializers.UUIDField()
    qty = qty(min_value=Decimal("0.001"))


class PreviewSerializer(serializers.Serializer[Any]):
    retailer = serializers.UUIDField()
    lines = serializers.ListField(child=PreviewLineSerializer(), min_length=1, max_length=200)
    on = serializers.DateField(required=False, allow_null=True, default=None)


class PreviewRowSerializer(serializers.Serializer[Any]):
    product = ProductRefSerializer()
    result = PriceResultSerializer(allow_null=True)
    problem = serializers.CharField(allow_blank=True)


class SpecialRefSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    price = money()


class PriceSheetRowSerializer(serializers.Serializer[Any]):
    product = ProductRefSerializer()
    result = PriceResultSerializer()
    special = SpecialRefSerializer(
        allow_null=True, help_text="The shop's special price for the product, to edit in place."
    )


class SchemeTermsSerializer(serializers.Serializer[Any]):
    """A free-goods scheme as a shop sees it ("Buy 10 get 1 free"); input ``schemes.Terms``."""

    scheme_id = serializers.UUIDField()
    name = serializers.CharField()
    buy_qty = qty()
    free_qty = qty()
    repeat = serializers.BooleanField(help_text="For every ``buy_qty`` bought, else once a line.")
    max_free_qty = qty(allow_null=True, help_text="At most this many free on one order line.")
    same_product = serializers.BooleanField()
    free_product_name = serializers.CharField()
    free_unit = serializers.CharField()


class FreeGoodsSchemeSerializer(serializers.ModelSerializer[FreeGoodsScheme]):
    buy_product = ProductRefSerializer(read_only=True)
    buy_unit = serializers.CharField(source="buy_product.unit.code", read_only=True)
    free_product = ProductRefSerializer(read_only=True)
    free_unit = serializers.CharField(source="free_product.unit.code", read_only=True)
    price_list = RefSerializer(allow_null=True, read_only=True)
    retailer = ShopRefSerializer(allow_null=True, read_only=True)

    class Meta:
        model = FreeGoodsScheme
        fields = (
            "id",
            "name",
            "buy_product",
            "buy_unit",
            "buy_qty",
            "free_product",
            "free_unit",
            "free_qty",
            "repeat",
            "max_free_qty",
            "audience_type",
            "price_list",
            "retailer",
            "valid_from",
            "valid_to",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class FreeGoodsSchemeWriteSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=120)
    buy_product = serializers.UUIDField()
    buy_qty = qty()
    free_product = serializers.UUIDField()
    free_qty = qty()
    repeat = serializers.BooleanField(required=False, default=True)
    max_free_qty = qty(required=False, allow_null=True, default=None)
    audience_type = serializers.ChoiceField(choices=DiscountRule.Audience.choices)
    price_list = serializers.UUIDField(required=False, allow_null=True, default=None)
    retailer = serializers.UUIDField(required=False, allow_null=True, default=None)
    valid_from = serializers.DateField(required=False, allow_null=True, default=None)
    valid_to = serializers.DateField(required=False, allow_null=True, default=None)
    is_active = serializers.BooleanField(required=False, default=True)


class FreeGoodsSchemeFilterSerializer(serializers.Serializer[Any]):
    active = serializers.BooleanField(required=False, allow_null=True, default=None)
    search = serializers.CharField(required=False, allow_blank=True, default="")
    product = serializers.UUIDField(required=False, allow_null=True, default=None)


SCHEME_FK = {
    "buy_product": "buy_product_id",
    "free_product": "free_product_id",
    "price_list": "price_list_id",
    "retailer": "retailer_id",
}


def scheme_fields(data: dict[str, Any]) -> dict[str, Any]:
    return {SCHEME_FK.get(k, k): v for k, v in data.items()}
