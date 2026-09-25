"""Pricing (PLAN §2.5, spec 5.6): price lists, retailer special prices, discount rules with slabs.
How a price is resolved lives in ``services.resolve_price`` only."""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from common.fields import MoneyField, QtyField
from common.models import SoftDeleteMixin, TenantScopedModel


class PriceList(SoftDeleteMixin, TenantScopedModel):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=30, blank=True, default="")
    description = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                "tenant",
                Lower("name"),
                condition=Q(deleted_at__isnull=True),
                name="uniq_price_list_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class PriceListItem(TenantScopedModel):
    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="+")
    price = MoneyField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["price_list", "product"], name="uniq_price_list_item"),
            models.CheckConstraint(condition=Q(price__gte=0), name="price_list_item_nonneg"),
        ]
        indexes = [models.Index(fields=["tenant", "product"], name="price_list_item_product_idx")]

    def __str__(self) -> str:
        return f"{self.price_list_id}:{self.product_id}={self.price}"


class RetailerPrice(TenantScopedModel):
    """A retailer's special price for one product (spec 5.6 step 1)."""

    retailer = models.ForeignKey(
        "retailers.Retailer", on_delete=models.CASCADE, related_name="special_prices"
    )
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="+")
    price = MoneyField()
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["retailer", "product"], name="uniq_retailer_price"),
            models.CheckConstraint(condition=Q(price__gte=0), name="retailer_price_nonneg"),
        ]
        indexes = [models.Index(fields=["tenant", "product"], name="retailer_price_product_idx")]

    def __str__(self) -> str:
        return f"{self.retailer_id}:{self.product_id}={self.price}"


class DiscountRule(TenantScopedModel):
    class Type(models.TextChoices):
        PERCENT = "PERCENT", "Percentage"
        FLAT_PER_UNIT = "FLAT_PER_UNIT", "Rupees off per unit"

    class Scope(models.TextChoices):
        ALL = "ALL", "All products"
        PRODUCT = "PRODUCT", "One product"
        CATEGORY = "CATEGORY", "A category (and its sub-categories)"
        BRAND = "BRAND", "A brand"

    class Audience(models.TextChoices):
        ALL = "ALL", "All shops"
        PRICE_LIST = "PRICE_LIST", "Shops on a price list"
        RETAILER = "RETAILER", "One shop"

    name = models.CharField(max_length=120)
    discount_type = models.CharField(max_length=15, choices=Type.choices)
    # Used when the rule has no slabs; with slabs, each slab carries its own value.
    value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    scope_type = models.CharField(max_length=10, choices=Scope.choices)
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    category = models.ForeignKey(
        "catalog.Category", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    brand = models.ForeignKey(
        "catalog.Brand", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    audience_type = models.CharField(max_length=12, choices=Audience.choices)
    price_list = models.ForeignKey(
        PriceList, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    retailer = models.ForeignKey(
        "retailers.Retailer", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    valid_from = models.DateField(null=True, blank=True)  # IST dates, inclusive
    valid_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    stackable = models.BooleanField(default=False)  # reserved: no stacking in v1

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        scope_type="ALL",
                        product__isnull=True,
                        category__isnull=True,
                        brand__isnull=True,
                    )
                    | Q(
                        scope_type="PRODUCT",
                        product__isnull=False,
                        category__isnull=True,
                        brand__isnull=True,
                    )
                    | Q(
                        scope_type="CATEGORY",
                        product__isnull=True,
                        category__isnull=False,
                        brand__isnull=True,
                    )
                    | Q(
                        scope_type="BRAND",
                        product__isnull=True,
                        category__isnull=True,
                        brand__isnull=False,
                    )
                ),
                name="discount_scope_matches_target",
            ),
            models.CheckConstraint(
                condition=(
                    Q(audience_type="ALL", price_list__isnull=True, retailer__isnull=True)
                    | Q(audience_type="PRICE_LIST", price_list__isnull=False, retailer__isnull=True)
                    | Q(audience_type="RETAILER", price_list__isnull=True, retailer__isnull=False)
                ),
                name="discount_audience_matches_target",
            ),
            models.CheckConstraint(condition=Q(value__gte=0), name="discount_value_nonneg"),
            models.CheckConstraint(
                condition=~Q(discount_type="PERCENT") | Q(value__lte=100),
                name="discount_percent_max_100",
            ),
            models.CheckConstraint(
                condition=Q(valid_from__isnull=True)
                | Q(valid_to__isnull=True)
                | Q(valid_to__gte=models.F("valid_from")),
                name="discount_valid_range",
            ),
            models.CheckConstraint(condition=Q(stackable=False), name="discount_no_stacking_v1"),
        ]
        indexes = [
            models.Index(fields=["tenant", "is_active", "scope_type"], name="discount_scope_idx"),
            models.Index(fields=["tenant", "audience_type"], name="discount_audience_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class DiscountSlab(TenantScopedModel):
    """A quantity break: the slab with the highest ``min_qty`` not above the line quantity wins;
    a rule with slabs and none reached does not apply (PLAN §2.5)."""

    rule = models.ForeignKey(DiscountRule, on_delete=models.CASCADE, related_name="slabs")
    min_qty = QtyField()
    value = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["min_qty"]
        constraints = [
            models.UniqueConstraint(fields=["rule", "min_qty"], name="uniq_slab_min_qty"),
            models.CheckConstraint(condition=Q(min_qty__gt=0), name="slab_min_qty_pos"),
            models.CheckConstraint(condition=Q(value__gt=0), name="slab_value_pos"),
        ]

    def __str__(self) -> str:
        return f"{self.rule_id} ≥{self.min_qty}: {self.value}"
