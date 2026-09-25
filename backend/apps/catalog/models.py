"""Catalog (PLAN §2.4, spec 5.4): categories, brands, units, products, barcodes, effective-dated
GST rates and product images. Data only; write logic lives in ``services.py``."""

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from common.fields import MoneyField, QtyField, RateField
from common.models import SoftDeleteMixin, TenantScopedModel

MAX_CATEGORY_DEPTH = 3


class Category(SoftDeleteMixin, TenantScopedModel):
    """Nested up to 3 levels. A category rule or filter covers all its descendants."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    level = models.PositiveSmallIntegerField(default=1)
    sort_order = models.IntegerField(default=0)
    image = models.CharField(max_length=300, blank=True, default="")  # storage key

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["sort_order", "name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(level__gte=1) & Q(level__lte=MAX_CATEGORY_DEPTH),
                name="category_level_1_to_3",
            ),
            models.CheckConstraint(
                condition=(Q(parent__isnull=True) & Q(level=1))
                | (Q(parent__isnull=False) & Q(level__gt=1)),
                name="category_level_matches_parent",
            ),
            models.UniqueConstraint(
                "tenant",
                "parent",
                Lower("name"),
                condition=Q(deleted_at__isnull=True),
                nulls_distinct=False,
                name="uniq_category_name_per_parent",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "parent"], name="category_tenant_parent_idx")]

    def __str__(self) -> str:
        return self.name


class Brand(SoftDeleteMixin, TenantScopedModel):
    name = models.CharField(max_length=120)
    logo = models.CharField(max_length=300, blank=True, default="")  # storage key

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                "tenant",
                Lower("name"),
                condition=Q(deleted_at__isnull=True),
                name="uniq_brand_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Unit(TenantScopedModel):
    """A unit of measure. Stock and orders use the product's base unit; packs are for entry and
    display (PLAN S5). ``uqc`` is the GST Unit Quantity Code printed on invoices."""

    code = models.CharField(max_length=10)
    name = models.CharField(max_length=60)
    allows_decimal = models.BooleanField(default=False)
    uqc = models.CharField(max_length=10)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_unit_code"),
            models.CheckConstraint(
                condition=Q(code=models.functions.Upper("code")), name="unit_code_uppercase"
            ),
        ]

    def __str__(self) -> str:
        return self.code


class Product(SoftDeleteMixin, TenantScopedModel):
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, null=True, blank=True, related_name="products"
    )
    brand = models.ForeignKey(
        Brand, on_delete=models.PROTECT, null=True, blank=True, related_name="products"
    )
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="+")
    pack_unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    pack_size = QtyField(null=True, blank=True)  # base units in one pack, e.g. 1 BOX = 12 PCS
    hsn_code = models.CharField(max_length=8)
    mrp = MoneyField(null=True, blank=True)
    base_price = MoneyField()
    min_order_qty = QtyField(default=1)
    order_multiple = QtyField(default=1)
    reorder_level = QtyField(default=0)
    tags = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    # Independent of is_active: keeps internal items out of the shop (ADR-034).
    show_in_shop = models.BooleanField(default=True)
    # Maintained by a database trigger (name, codes/barcodes, brand, tags, category).
    search_vector = SearchVectorField(null=True, editable=False)

    class Meta:
        ordering = ["name"]
        constraints = [
            # Codes are never reused, even after a product is deleted (plan decision).
            models.UniqueConstraint("tenant", Lower("code"), name="uniq_product_code"),
            models.CheckConstraint(condition=Q(base_price__gte=0), name="product_price_nonneg"),
            models.CheckConstraint(
                condition=Q(mrp__isnull=True) | Q(mrp__gte=0), name="product_mrp_nonneg"
            ),
            models.CheckConstraint(condition=Q(min_order_qty__gt=0), name="product_min_qty_pos"),
            models.CheckConstraint(condition=Q(order_multiple__gt=0), name="product_multiple_pos"),
            models.CheckConstraint(
                condition=Q(reorder_level__gte=0), name="product_reorder_nonneg"
            ),
            models.CheckConstraint(
                condition=(Q(pack_unit__isnull=True) & Q(pack_size__isnull=True))
                | (Q(pack_unit__isnull=False) & Q(pack_size__isnull=False) & Q(pack_size__gt=0)),
                name="product_pack_complete",
            ),
            models.CheckConstraint(
                condition=Q(hsn_code__regex=r"^[0-9]{2,8}$"), name="product_hsn_digits"
            ),
        ]
        indexes = [
            GinIndex(fields=["tenant", "search_vector"], name="product_search_gin"),
            GinIndex(fields=["name"], name="product_name_trgm", opclasses=["gin_trgm_ops"]),
            GinIndex(fields=["code"], name="product_code_trgm", opclasses=["gin_trgm_ops"]),
            models.Index(fields=["tenant", "category"], name="product_tenant_category_idx"),
            models.Index(fields=["tenant", "brand"], name="product_tenant_brand_idx"),
            models.Index(fields=["tenant", "is_active", "name"], name="product_tenant_active_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class ProductBarcode(TenantScopedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="barcodes")
    barcode = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "barcode"], name="uniq_barcode"),
        ]

    def __str__(self) -> str:
        return self.barcode


class ProductTaxRate(TenantScopedModel):
    """Append-only history of a product's GST/cess rate (PLAN G1b). The rate on date *d* is the
    non-cancelled row with the latest ``effective_from ≤ d``. A future row may be cancelled before
    it takes effect (ADR-034); the database allows no other update and no delete."""

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="tax_rates")
    gst_rate = RateField()
    cess_type = models.ForeignKey(
        "platform.CessType", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    cess_rate = RateField(default=0)
    effective_from = models.DateField()  # IST calendar date
    reason = models.CharField(max_length=200, blank=True, default="")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    cancel_reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "effective_from"],
                condition=Q(cancelled_at__isnull=True),
                name="uniq_product_rate_per_day",
            ),
            models.CheckConstraint(
                condition=Q(gst_rate__gte=0) & Q(gst_rate__lte=100), name="product_rate_range"
            ),
            models.CheckConstraint(
                condition=Q(cess_rate__gte=0) & Q(cess_rate__lte=100), name="product_cess_range"
            ),
            models.CheckConstraint(
                condition=Q(cess_type__isnull=False) | Q(cess_rate=0),
                name="product_cess_needs_type",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "product", "-effective_from"], name="product_rate_lookup_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product_id} {self.gst_rate}% from {self.effective_from}"


class ProductImage(TenantScopedModel):
    """An uploaded image and its resized WebP variants (ADR-034). Variants live under an
    unguessable, content-versioned prefix with long cache headers; the original stays private."""

    class Status(models.TextChoices):
        PROCESSING = "PROCESSING", "Processing"
        READY = "READY", "Ready"
        FAILED = "FAILED", "Failed"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    original_key = models.CharField(max_length=300)
    # {"thumb": {"key": ..., "width": ..., "height": ...}, "medium": {...}, "large": {...}}
    variants = models.JSONField(default=dict, blank=True)
    sort_order = models.IntegerField(default=0)
    alt_text = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PROCESSING)

    class Meta:
        ordering = ["sort_order", "created_at"]
        indexes = [
            models.Index(fields=["tenant", "product", "sort_order"], name="product_image_order_idx")
        ]

    def __str__(self) -> str:
        return f"{self.product_id} image {self.sort_order}"
