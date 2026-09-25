from typing import Any

from rest_framework import serializers

from apps.catalog.api.serializers import RefSerializer
from apps.pricing.models import DiscountRule, DiscountSlab, PriceList, PriceListItem, RetailerPrice


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


class RetailerPriceSerializer(serializers.ModelSerializer[RetailerPrice]):
    retailer = ShopRefSerializer(read_only=True)
    product = ProductRefSerializer(read_only=True)
    base_price = money(source="product.base_price", read_only=True)

    class Meta:
        model = RetailerPrice
        fields = ("id", "retailer", "product", "base_price", "price", "note", "updated_at")
        read_only_fields = fields


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
        )
        read_only_fields = fields


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
