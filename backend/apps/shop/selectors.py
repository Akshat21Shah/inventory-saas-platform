"""What a shop may see of its distributor's catalog (ADR-034), with its own prices (ADR-036).

A product is shown only if it is active, not deleted, "Show in shop" is on, a GST rate is in
effect today, and ``resolve_price`` gives this shop a price above zero at the product's minimum
order quantity. With backorders off and ⚙ ``stock.show_out_of_stock_in_shop`` off, products with
nothing available are hidden too. The first four and "unit price above zero" are filtered in SQL,
so counts and pages stay cheap; the rare product that a 100% discount brings to zero is dropped
from the page after pricing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Count, F, OuterRef, Prefetch, QuerySet, Subquery
from django.db.models.functions import Coalesce

from apps.catalog import selectors as catalog
from apps.catalog.models import Brand, Product, ProductImage
from apps.catalog.search import ranked_queryset
from apps.inventory import availability
from apps.pricing.models import PriceListItem, RetailerPrice
from apps.pricing.resolve import PriceResult, resolve_prices, slab_quantities
from apps.retailers.models import Retailer
from common.dates import today_ist

SEARCH_LIMIT = 40


def _ready_images() -> Prefetch[Any]:
    return Prefetch(
        "images",
        queryset=ProductImage.objects.filter(status=ProductImage.Status.READY).order_by(
            "sort_order", "created_at"
        ),
    )


def visible_products(retailer: Retailer, on: date | None = None) -> QuerySet[Product]:
    day = on or today_ist()
    special = RetailerPrice.objects.filter(retailer=retailer, product=OuterRef("pk")).values(
        "price"
    )[:1]
    sources: list[Any] = [Subquery(special)]
    if retailer.price_list_id:
        listed = PriceListItem.objects.filter(
            price_list_id=retailer.price_list_id,
            price_list__deleted_at__isnull=True,
            product=OuterRef("pk"),
        ).values("price")[:1]
        sources.append(Subquery(listed))
    qs: QuerySet[Product] = (
        Product.objects.filter(is_active=True, deleted_at__isnull=True, show_in_shop=True)
        .filter(catalog.has_rate_on(day))
        .annotate(shop_unit_price=Coalesce(*sources, F("base_price")))
        .filter(shop_unit_price__gt=0)
    )
    # Stock available to the shop; products that can't be ordered are hidden when the
    # distributor chooses so (ADR-041 item 12).
    return availability.for_shop(qs, availability.ShopStockRules.for_tenant(retailer.tenant_id))


@dataclass(frozen=True)
class ShopFilters:
    search: str = ""
    category_id: UUID | None = None
    brand_id: UUID | None = None


def shop_products(retailer: Retailer, filters: ShopFilters) -> QuerySet[Product]:
    """Browse (by name) or search (best match first, top ``SEARCH_LIMIT``)."""
    qs = visible_products(retailer).select_related("brand", "category", "unit", "pack_unit")
    if filters.category_id:
        qs = qs.filter(category_id__in=catalog.descendant_ids(filters.category_id))
    if filters.brand_id:
        qs = qs.filter(brand_id=filters.brand_id)
    qs = qs.prefetch_related(_ready_images())
    if filters.search.strip():
        return ranked_queryset(qs, filters.search)
    return qs.order_by("name", "id")


def priced(retailer: Retailer, products: list[Product]) -> list[tuple[Product, PriceResult]]:
    """Each product with this shop's price at its minimum order quantity; products without a
    valid price are left out (ADR-034)."""
    results = resolve_prices(retailer, [(p, p.min_order_qty) for p in products])
    return [(p, r) for p, r in zip(products, results, strict=True) if r.valid]


@dataclass(frozen=True)
class SlabHint:
    min_qty: Decimal
    net_unit_price: Decimal


@dataclass(frozen=True)
class ShopProduct:
    product: Product
    price: PriceResult
    slab_hints: list[SlabHint]


def shop_product(retailer: Retailer, product_id: UUID) -> ShopProduct | None:
    product: Product | None = (
        visible_products(retailer)
        .select_related("brand", "category", "unit", "pack_unit")
        .prefetch_related(_ready_images())
        .filter(pk=product_id)
        .first()
    )
    if product is None:
        return None
    thresholds = [q for q in slab_quantities(retailer, product) if q > product.min_order_qty]
    results = resolve_prices(
        retailer, [(product, product.min_order_qty)] + [(product, q) for q in thresholds]
    )
    price, at_slabs = results[0], results[1:]
    if not price.valid:
        return None
    hints: list[SlabHint] = []
    lowest = price.net_unit_price
    for result in at_slabs:
        if result.net_unit_price < lowest:
            hints.append(SlabHint(result.qty, result.net_unit_price))
            lowest = result.net_unit_price
    return ShopProduct(product, price, hints)


def shop_category_tree(retailer: Retailer) -> list[dict[str, Any]]:
    """Categories that hold at least one visible product (counted with their sub-categories)."""
    direct = dict(
        visible_products(retailer)
        .filter(category__isnull=False)
        .values("category_id")
        .annotate(n=Count("pk"))
        .values_list("category_id", "n")
    )
    rows = list(catalog.categories().order_by("level", "sort_order", "name"))
    nodes: dict[UUID, dict[str, Any]] = {
        c.pk: {"category": c, "product_count": direct.get(c.pk, 0), "children": []} for c in rows
    }
    for c in sorted(rows, key=lambda c: -c.level):  # deepest first, so counts roll up
        if c.parent_id and c.parent_id in nodes:
            nodes[c.parent_id]["product_count"] += nodes[c.pk]["product_count"]
    roots: list[dict[str, Any]] = []
    for c in rows:
        node = nodes[c.pk]
        if not node["product_count"]:
            continue
        parent = nodes.get(c.parent_id) if c.parent_id else None
        (parent["children"] if parent else roots).append(node)
    return roots


def shop_brands(retailer: Retailer, category_id: UUID | None = None) -> QuerySet[Brand]:
    """Brands with at least one visible product (in the category, when given)."""
    products = visible_products(retailer)
    if category_id:
        products = products.filter(category_id__in=catalog.descendant_ids(category_id))
    return (
        catalog.brands()
        .filter(pk__in=products.filter(brand__isnull=False).values("brand_id"))
        .order_by("name", "pk")
    )


def repeat_items(retailer: Retailer, wanted: list[tuple[UUID, Decimal]]) -> list[dict[str, Any]]:
    """Product cards for "Repeat last order": products the shop can still see, priced today, in
    the order's line order, each with the quantity ordered last time."""
    ids = [product_id for product_id, _ in wanted]
    found = {
        p.pk: p
        for p in visible_products(retailer)
        .filter(pk__in=ids)
        .select_related("brand", "category", "unit", "pack_unit")
        .prefetch_related(_ready_images())
    }
    products = [found[pid] for pid in ids if pid in found]
    last = dict(wanted)
    return [
        {"product": p, "price": r, "last_quantity": last[p.pk]}
        for p, r in priced(retailer, products)
    ]
