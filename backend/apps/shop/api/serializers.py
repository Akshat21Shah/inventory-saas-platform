"""What a shop sees. Prices come only from ``resolve_price``. The shop never sees how its price was
reached (base price, price list, rule names)."""

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.api.serializers import ImageUrlsSerializer, RefSerializer, first_ready_thumb
from apps.catalog.images import variant_urls
from apps.catalog.models import ProductImage
from apps.pricing.api.serializers import money, qty
from apps.pricing.models import DiscountRule


class ShopDiscountSerializer(serializers.Serializer[Any]):
    discount_type = serializers.ChoiceField(choices=DiscountRule.Type.choices)
    value = money(help_text="The percentage, or rupees off each unit.")
    slab_min_qty = qty(allow_null=True, help_text="Set when a quantity slab gave the discount.")
    amount = money(help_text="The discount on the quoted quantity (``qty`` of the price).")


class ShopPriceSerializer(serializers.Serializer[Any]):
    qty = qty(help_text="The quantity this price is for (the minimum order quantity).")
    unit_price = money()
    discount = ShopDiscountSerializer(allow_null=True)
    discount_per_unit = money(help_text="Rupees off each unit; 0.00 without a discount.")
    net_unit_price = money(help_text="After the discount; for display only.")
    gst_rate = serializers.DecimalField(max_digits=6, decimal_places=3)
    prices_include_gst = serializers.BooleanField()


class ShopUnitSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    name = serializers.CharField()


class ShopProductSerializer(serializers.Serializer[Any]):
    """One product row with its price; input is ``{"product": Product, "price": PriceResult}``."""

    id = serializers.UUIDField(source="product.id")
    code = serializers.CharField(source="product.code")
    name = serializers.CharField(source="product.name")
    brand = RefSerializer(source="product.brand", allow_null=True)
    category = RefSerializer(source="product.category", allow_null=True)
    unit = ShopUnitSerializer(source="product.unit")
    pack_unit = ShopUnitSerializer(source="product.pack_unit", allow_null=True)
    pack_size = qty(source="product.pack_size", allow_null=True)
    mrp = money(source="product.mrp", allow_null=True)
    min_order_qty = qty(source="product.min_order_qty")
    order_multiple = qty(source="product.order_multiple")
    thumbnail_url = serializers.SerializerMethodField()
    price = ShopPriceSerializer()

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_thumbnail_url(self, row: dict[str, Any]) -> str | None:
        return first_ready_thumb(row["product"])


class ShopImageSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    alt_text = serializers.CharField()
    urls = serializers.SerializerMethodField()

    @extend_schema_field(ImageUrlsSerializer())
    def get_urls(self, image: ProductImage) -> dict[str, str]:
        return variant_urls(image.variants)


class SlabHintSerializer(serializers.Serializer[Any]):
    min_qty = qty()
    net_unit_price = money()


class ShopProductDetailSerializer(ShopProductSerializer):
    description = serializers.CharField(source="product.description")
    images = ShopImageSerializer(source="product.images.all", many=True)
    slab_hints = SlabHintSerializer(
        many=True, help_text="Lower prices for larger quantities, e.g. 24 or more."
    )


class ShopCategorySerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(source="category.id")
    name = serializers.CharField(source="category.name")
    level = serializers.IntegerField(source="category.level")
    product_count = serializers.IntegerField()
    children = serializers.SerializerMethodField()

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_children(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        return list(ShopCategorySerializer(node["children"], many=True).data)


class ShopBrandSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()
