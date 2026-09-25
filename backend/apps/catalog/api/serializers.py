"""Catalog API shapes (PLAN §3.5). Validation of business rules happens in the services."""

from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog import selectors
from apps.catalog.images import variant_urls
from apps.catalog.models import Brand, Category, Product, ProductImage, ProductTaxRate, Unit
from common.dates import today_ist


def money_field(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=14, decimal_places=2, **kwargs)


def qty_field(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=14, decimal_places=3, **kwargs)


def rate_field(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=6, decimal_places=3, **kwargs)


class RefSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()


class WarningSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.DictField()


# --- Categories, brands, units ------------------------------------------------------------------


class CategorySerializer(serializers.ModelSerializer[Category]):
    parent_id = serializers.UUIDField(allow_null=True, read_only=True)

    class Meta:
        model = Category
        fields = ("id", "name", "slug", "parent_id", "level", "sort_order")
        read_only_fields = fields


class CategoryWriteSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=120)
    parent_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    sort_order = serializers.IntegerField(required=False, default=0)


class CategoryUpdateSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=120, required=False)
    parent_id = serializers.UUIDField(allow_null=True, required=False)
    sort_order = serializers.IntegerField(required=False)


class CategoryTreeNodeSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(source="category.id")
    name = serializers.CharField(source="category.name")
    level = serializers.IntegerField(source="category.level")
    sort_order = serializers.IntegerField(source="category.sort_order")
    children = serializers.SerializerMethodField()

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_children(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        return [CategoryTreeNodeSerializer(child).data for child in node["children"]]


class BrandSerializer(serializers.ModelSerializer[Brand]):
    class Meta:
        model = Brand
        fields = ("id", "name")


class UnitSerializer(serializers.ModelSerializer[Unit]):
    class Meta:
        model = Unit
        fields = ("id", "code", "name", "allows_decimal", "uqc", "is_active")


class UnitWriteSerializer(serializers.Serializer[Any]):
    code = serializers.CharField(max_length=10)
    name = serializers.CharField(max_length=60)
    allows_decimal = serializers.BooleanField(required=False, default=False)
    uqc = serializers.CharField(max_length=10)
    is_active = serializers.BooleanField(required=False, default=True)


# --- Products -----------------------------------------------------------------------------------


class ProductTaxRateSerializer(serializers.ModelSerializer[ProductTaxRate]):
    cess_type = RefSerializer(allow_null=True, read_only=True)
    state = serializers.SerializerMethodField()

    class Meta:
        model = ProductTaxRate
        fields = (
            "id",
            "gst_rate",
            "cess_type",
            "cess_rate",
            "effective_from",
            "reason",
            "state",
            "cancelled_at",
            "cancel_reason",
            "created_at",
        )
        read_only_fields = fields

    def get_state(self, row: ProductTaxRate) -> str:
        """CANCELLED, SCHEDULED (future), CURRENT or PAST."""
        current = self.context.get("current_id")
        if row.cancelled_at is not None:
            return "CANCELLED"
        if row.pk == current:
            return "CURRENT"
        return "SCHEDULED" if row.effective_from > self.context["today"] else "PAST"


class ImageUrlsSerializer(serializers.Serializer[Any]):
    thumb = serializers.URLField()
    medium = serializers.URLField()
    large = serializers.URLField()


class ProductImageSerializer(serializers.ModelSerializer[ProductImage]):
    urls = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ("id", "status", "sort_order", "alt_text", "urls", "created_at")
        read_only_fields = fields

    @extend_schema_field(ImageUrlsSerializer(allow_null=True))
    def get_urls(self, image: ProductImage) -> dict[str, str] | None:
        """Stable, long-cached URLs; present only once the resized versions are ready."""
        if image.status != ProductImage.Status.READY:
            return None
        return variant_urls(image.variants)


class ImageUploadSerializer(serializers.Serializer[Any]):
    file = serializers.FileField()
    alt_text = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ImageUpdateSerializer(serializers.Serializer[Any]):
    sort_order = serializers.IntegerField(required=False)
    alt_text = serializers.CharField(max_length=200, required=False, allow_blank=True)


def first_ready_thumb(product: Product) -> str | None:
    """From prefetched images (list views prefetch the ready ones in order)."""
    for image in product.images.all():
        if image.status == ProductImage.Status.READY and image.variants.get("thumb"):
            return variant_urls({"thumb": image.variants["thumb"]})["thumb"]
    return None


class ProductListSerializer(serializers.ModelSerializer[Product]):
    category = RefSerializer(allow_null=True, read_only=True)
    brand = RefSerializer(allow_null=True, read_only=True)
    unit = serializers.CharField(source="unit.code", read_only=True)
    gst_rate = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id",
            "code",
            "name",
            "category",
            "brand",
            "unit",
            "hsn_code",
            "gst_rate",
            "mrp",
            "base_price",
            "is_active",
            "show_in_shop",
            "thumbnail_url",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_thumbnail_url(self, product: Product) -> str | None:
        return first_ready_thumb(product)

    @extend_schema_field(rate_field(allow_null=True))
    def get_gst_rate(self, product: Product) -> str | None:
        """As a string like every decimal in the API (a method field would otherwise send a
        float)."""
        rates = self.context.get("rates") or {}
        row = rates.get(product.pk)
        return rate_field().to_representation(row.gst_rate) if row else None


class BarcodeSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    barcode = serializers.CharField(max_length=64)


class HsnSuggestionSerializer(serializers.Serializer[Any]):
    hsn_prefix = serializers.CharField()
    gst_rate = rate_field()
    description = serializers.CharField()


class HsnHintResultSerializer(serializers.Serializer[Any]):
    hint = HsnSuggestionSerializer(allow_null=True)


class ProductDetailSerializer(serializers.ModelSerializer[Product]):
    category = RefSerializer(allow_null=True, read_only=True)
    brand = RefSerializer(allow_null=True, read_only=True)
    unit = UnitSerializer(read_only=True)
    pack_unit = UnitSerializer(read_only=True, allow_null=True)
    barcodes = BarcodeSerializer(many=True, read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    current_rate = serializers.SerializerMethodField()
    tax_rates = serializers.SerializerMethodField()
    hsn_hint = serializers.SerializerMethodField()
    warnings = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id",
            "code",
            "name",
            "description",
            "category",
            "brand",
            "unit",
            "pack_unit",
            "pack_size",
            "hsn_code",
            "mrp",
            "base_price",
            "min_order_qty",
            "order_multiple",
            "reorder_level",
            "tags",
            "show_in_shop",
            "is_active",
            "barcodes",
            "images",
            "current_rate",
            "tax_rates",
            "hsn_hint",
            "warnings",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def _rate_context(self, product: Product) -> dict[str, Any]:
        current = selectors.tax_rate_on(product.pk)
        return {**self.context, "current_id": current.pk if current else None, "today": today_ist()}

    @extend_schema_field(ProductTaxRateSerializer(allow_null=True))
    def get_current_rate(self, product: Product) -> dict[str, Any] | None:
        current = selectors.tax_rate_on(product.pk)
        if current is None:
            return None
        return ProductTaxRateSerializer(current, context=self._rate_context(product)).data

    @extend_schema_field(ProductTaxRateSerializer(many=True))
    def get_tax_rates(self, product: Product) -> list[Any]:
        rows = product.tax_rates.all()
        return list(
            ProductTaxRateSerializer(rows, many=True, context=self._rate_context(product)).data
        )

    @extend_schema_field(HsnSuggestionSerializer(allow_null=True))
    def get_hsn_hint(self, product: Product) -> dict[str, Any] | None:
        hint = selectors.hsn_hint(product.hsn_code)
        return HsnSuggestionSerializer(hint).data if hint else None

    @extend_schema_field(WarningSerializer(many=True))
    def get_warnings(self, product: Product) -> list[Any]:
        return [
            {"code": w.code, "message": w.message, "details": w.details}
            for w in self.context.get("warnings", [])
        ]


class ProductWriteSerializer(serializers.Serializer[Any]):
    """Create: code, name, unit, hsn_code, base_price and gst_rate are required."""

    code = serializers.CharField(max_length=40)
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    category = serializers.UUIDField(required=False, allow_null=True, default=None)
    brand = serializers.UUIDField(required=False, allow_null=True, default=None)
    unit = serializers.UUIDField()
    pack_unit = serializers.UUIDField(required=False, allow_null=True, default=None)
    pack_size = qty_field(required=False, allow_null=True, default=None)
    hsn_code = serializers.CharField(max_length=20)
    mrp = money_field(required=False, allow_null=True, default=None)
    base_price = money_field()
    min_order_qty = qty_field(required=False, default=Decimal("1"))
    order_multiple = qty_field(required=False, default=Decimal("1"))
    reorder_level = qty_field(required=False, default=Decimal("0"))
    tags = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False, default=list
    )
    show_in_shop = serializers.BooleanField(required=False, default=True)
    is_active = serializers.BooleanField(required=False, default=True)
    gst_rate = rate_field()
    cess_type = serializers.UUIDField(required=False, allow_null=True, default=None)
    cess_rate = rate_field(required=False, default=Decimal("0"))
    barcodes = serializers.ListField(
        child=serializers.CharField(max_length=64), required=False, default=list
    )


class ProductUpdateSerializer(serializers.Serializer[Any]):
    """Edits; the GST rate changes only through a scheduled rate change."""

    code = serializers.CharField(max_length=40, required=False)
    name = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    category = serializers.UUIDField(required=False, allow_null=True)
    brand = serializers.UUIDField(required=False, allow_null=True)
    unit = serializers.UUIDField(required=False)
    pack_unit = serializers.UUIDField(required=False, allow_null=True)
    pack_size = qty_field(required=False, allow_null=True)
    hsn_code = serializers.CharField(max_length=20, required=False)
    mrp = money_field(required=False, allow_null=True)
    base_price = money_field(required=False)
    min_order_qty = qty_field(required=False)
    order_multiple = qty_field(required=False)
    reorder_level = qty_field(required=False)
    tags = serializers.ListField(child=serializers.CharField(max_length=40), required=False)
    show_in_shop = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)


FK_FIELDS = {
    "category": "category_id",
    "brand": "brand_id",
    "unit": "unit_id",
    "pack_unit": "pack_unit_id",
}


def to_model_fields(data: dict[str, Any]) -> dict[str, Any]:
    """API names → model attribute names (``category`` → ``category_id``)."""
    return {FK_FIELDS.get(k, k): v for k, v in data.items()}


class ProductFilterSerializer(serializers.Serializer[Any]):
    search = serializers.CharField(required=False, allow_blank=True, default="")
    category = serializers.UUIDField(required=False)
    brand = serializers.UUIDField(required=False)
    is_active = serializers.BooleanField(required=False, allow_null=True, default=None)
    show_in_shop = serializers.BooleanField(required=False, allow_null=True, default=None)
    hsn_prefix = serializers.RegexField(r"^[0-9]{1,8}$", required=False, default="")


class LookupSerializer(serializers.Serializer[Any]):
    code = serializers.CharField(required=False, default="")
    barcode = serializers.CharField(required=False, default="")


class BulkSerializer(serializers.Serializer[Any]):
    product_ids = serializers.ListField(child=serializers.UUIDField(), max_length=1000)
    action = serializers.ChoiceField(
        choices=[
            "activate",
            "deactivate",
            "show_in_shop",
            "hide_from_shop",
            "set_category",
            "set_brand",
        ]
    )
    value = serializers.UUIDField(required=False, allow_null=True, default=None)


class BulkResultSerializer(serializers.Serializer[Any]):
    changed = serializers.IntegerField()


class ScheduleRateSerializer(serializers.Serializer[Any]):
    gst_rate = rate_field()
    cess_type = serializers.UUIDField(required=False, allow_null=True, default=None)
    cess_rate = rate_field(required=False, default=Decimal("0"))
    effective_from = serializers.DateField()
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class CancelRateSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=200)


class BulkScheduleSerializer(ScheduleRateSerializer):
    hsn_prefix = serializers.RegexField(r"^[0-9]{2,8}$", required=False, default="")
    category = serializers.UUIDField(required=False, allow_null=True, default=None)
    product_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list, max_length=5000
    )
    preview = serializers.BooleanField(required=False, default=True)
    expected_count = serializers.IntegerField(required=False, min_value=0)


class BulkScheduleResultSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField()
    skipped = serializers.IntegerField(required=False)
    sample = serializers.ListField(child=serializers.DictField(), required=False)
    committed = serializers.BooleanField()
