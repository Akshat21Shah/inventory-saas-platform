"""Catalog reads (PLAN §2.4). Everything is scoped to the active tenant by the default managers."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Exists, OuterRef, Prefetch, Q, QuerySet

from apps.catalog.models import Brand, Category, Product, ProductImage, ProductTaxRate, Unit
from apps.platform.models import HsnRateHint
from apps.platform.selectors import get_platform_setting
from common.dates import today_ist


def categories(*, include_deleted: bool = False) -> QuerySet[Category]:
    qs = Category.objects.all()
    return qs if include_deleted else qs.filter(deleted_at__isnull=True)


def category(category_id: UUID) -> Category | None:
    found: Category | None = categories().filter(pk=category_id).first()
    return found


def category_tree() -> list[dict[str, Any]]:
    """Nested categories (≤ 3 levels), ordered by sort order then name."""
    rows = list(categories().order_by("level", "sort_order", "name"))
    nodes: dict[UUID, dict[str, Any]] = {c.pk: {"category": c, "children": []} for c in rows}
    roots: list[dict[str, Any]] = []
    for c in rows:
        parent = nodes.get(c.parent_id) if c.parent_id else None
        (parent["children"] if parent else roots).append(nodes[c.pk])
    return roots


def descendant_ids(category_id: UUID) -> set[UUID]:
    """The category and every category below it (a category filter or rule covers them all)."""
    found = {category_id}
    frontier = {category_id}
    while frontier:
        frontier = (
            set(
                Category.objects.filter(
                    parent_id__in=frontier, deleted_at__isnull=True
                ).values_list("pk", flat=True)
            )
            - found
        )
        found |= frontier
    return found


def brands() -> QuerySet[Brand]:
    return Brand.objects.filter(deleted_at__isnull=True)


def units() -> QuerySet[Unit]:
    return Unit.objects.all()


@dataclass(frozen=True)
class ProductFilters:
    search: str = ""
    category_id: UUID | None = None
    brand_id: UUID | None = None
    is_active: bool | None = None
    show_in_shop: bool | None = None
    hsn_prefix: str = ""


def products(filters: ProductFilters | None = None) -> QuerySet[Product]:
    """The product list (not deleted), with the relations the list needs."""
    f = filters or ProductFilters()
    qs = Product.objects.filter(deleted_at__isnull=True).select_related(
        "category", "brand", "unit", "pack_unit"
    )
    if f.category_id:
        qs = qs.filter(category_id__in=descendant_ids(f.category_id))
    if f.brand_id:
        qs = qs.filter(brand_id=f.brand_id)
    if f.is_active is not None:
        qs = qs.filter(is_active=f.is_active)
    if f.show_in_shop is not None:
        qs = qs.filter(show_in_shop=f.show_in_shop)
    if f.hsn_prefix:
        qs = qs.filter(hsn_code__startswith=f.hsn_prefix)
    if f.search.strip():
        from apps.catalog.search import search_filter

        qs = qs.filter(search_filter(f.search))
    return qs


def product_list(filters: ProductFilters | None = None) -> QuerySet[Product]:
    """``products`` plus each product's ready images in order (for list thumbnails)."""
    return products(filters).prefetch_related(
        Prefetch(
            "images",
            queryset=ProductImage.objects.filter(status=ProductImage.Status.READY).order_by(
                "sort_order", "created_at"
            ),
        )
    )


def product(product_id: UUID) -> Product | None:
    found: Product | None = (
        products()
        .prefetch_related(
            "barcodes",
            Prefetch("images", queryset=ProductImage.objects.order_by("sort_order", "created_at")),
            Prefetch("tax_rates", queryset=ProductTaxRate.objects.select_related("cess_type")),
        )
        .filter(pk=product_id)
        .first()
    )
    return found


def product_by_code_or_barcode(*, code: str = "", barcode: str = "") -> Product | None:
    qs = products()
    if code:
        found: Product | None = qs.filter(code__iexact=code.strip()).first()
        return found
    if barcode:
        return qs.filter(barcodes__barcode=barcode.strip()).first()
    return None


# --- Effective-dated GST rates (PLAN G1b) ------------------------------------------------------


def _in_effect(on: date) -> Q:
    return Q(cancelled_at__isnull=True, effective_from__lte=on)


def has_rate_on(on: date) -> Exists:
    """For filtering products: a GST rate is in effect on ``on``."""
    return Exists(ProductTaxRate.objects.filter(_in_effect(on), product_id=OuterRef("pk")))


def tax_rate_on(product_id: UUID, on: date | None = None) -> ProductTaxRate | None:
    """The one place that answers "which GST/cess rate applies to this product on this day"."""
    rate: ProductTaxRate | None = (
        ProductTaxRate.objects.filter(_in_effect(on or today_ist()), product_id=product_id)
        .select_related("cess_type")
        .order_by("-effective_from")
        .first()
    )
    return rate


def tax_rates_on(product_ids: list[UUID], on: date | None = None) -> dict[UUID, ProductTaxRate]:
    """``tax_rate_on`` for many products in one query."""
    rows = (
        ProductTaxRate.objects.filter(_in_effect(on or today_ist()), product_id__in=product_ids)
        .order_by("product_id", "-effective_from")
        .distinct("product_id")
    )
    return {row.product_id: row for row in rows}


def scheduled_rates(product_id: UUID) -> QuerySet[ProductTaxRate]:
    """Rate changes that have not taken effect yet (and were not cancelled)."""
    return ProductTaxRate.objects.filter(
        product_id=product_id, cancelled_at__isnull=True, effective_from__gt=today_ist()
    ).order_by("effective_from")


def is_sellable(product_id: UUID, on: date | None = None) -> bool:
    """A product can be sold only while a rate is in effect."""
    return tax_rate_on(product_id, on) is not None


# --- HSN hints (platform suggestions, never used to compute tax; ADR-008) ------------------------


def hsn_hint(hsn_code: str, on: date | None = None) -> HsnRateHint | None:
    """The suggestion for the longest matching HSN prefix in effect on the day, if hints are on."""
    if not hsn_code or not get_platform_setting("platform.hsn_rate_hints_enabled"):
        return None
    prefixes = [hsn_code[:n] for n in range(len(hsn_code), 1, -1)]
    hints = HsnRateHint.objects.filter(
        hsn_prefix__in=prefixes, effective_from__lte=on or today_ist()
    ).order_by("-effective_from")
    best: HsnRateHint | None = None
    for hint in hints:
        if best is None or len(hint.hsn_prefix) > len(best.hsn_prefix):
            best = hint
    return best


def hint_differs(hsn_code: str, gst_rate: Decimal) -> HsnRateHint | None:
    hint = hsn_hint(hsn_code)
    return hint if hint is not None and hint.gst_rate != gst_rate else None
