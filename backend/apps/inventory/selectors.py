"""Inventory reads (PLAN §3.7): stock lists, movements, receipts, adjustments, alerts, reports."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import (
    Count,
    DecimalField,
    F,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce

from apps.billing.tax import stock_value
from apps.catalog.models import Category, Product
from apps.catalog.selectors import ProductFilters
from apps.catalog.selectors import product_list as catalog_products
from apps.inventory.models import (
    StockAdjustment,
    StockAlert,
    StockInward,
    StockLevel,
    StockMovement,
    Warehouse,
)
from apps.inventory.services import default_warehouse

QTY = DecimalField(max_digits=14, decimal_places=3)
ZERO = Value(Decimal("0"), output_field=QTY)


class StockStatus:
    """The staff-facing state of one product's stock (the shop has its own labels)."""

    IN_STOCK = "IN_STOCK"
    LOW = "LOW"
    OUT = "OUT"


STOCK_STATUS_CHOICES = [StockStatus.IN_STOCK, StockStatus.LOW, StockStatus.OUT]


def warehouses() -> QuerySet[Warehouse]:
    return Warehouse.objects.all()


# --- Stock list --------------------------------------------------------------------------------


@dataclass(frozen=True)
class StockFilters:
    search: str = ""
    category_id: UUID | None = None
    brand_id: UUID | None = None
    status: str = ""  # IN_STOCK, LOW, OUT, BACKORDERED
    is_active: bool | None = None
    no_reorder_level: bool = False  # reorder level 0: never "low" (the report prompts to set it)


def with_stock(qs: QuerySet[Product], warehouse: Warehouse | None = None) -> QuerySet[Product]:
    """Annotate products with on_hand, reserved, backordered and available (0 without a level)."""
    level = StockLevel.objects.filter(
        product=OuterRef("pk"), warehouse=warehouse or default_warehouse()
    )

    def column(name: str) -> Coalesce:
        return Coalesce(Subquery(level.values(name)[:1], output_field=QTY), ZERO)

    return qs.annotate(
        on_hand=column("quantity_on_hand"),
        reserved=column("quantity_reserved"),
        backordered=column("quantity_backordered"),
    ).annotate(available=F("on_hand") - F("reserved"))


LOW_Q = Q(available__gt=0, reorder_level__gt=0, available__lte=F("reorder_level"))
OUT_Q = Q(available__lte=0)


def stock_list(filters: StockFilters | None = None) -> QuerySet[Product]:
    f = filters or StockFilters()
    qs = with_stock(
        catalog_products(
            ProductFilters(
                search=f.search,
                category_id=f.category_id,
                brand_id=f.brand_id,
                is_active=f.is_active,
            )
        )
    )
    if f.status == StockStatus.OUT:
        qs = qs.filter(OUT_Q)
    elif f.status == StockStatus.LOW:
        qs = qs.filter(LOW_Q)
    elif f.status == StockStatus.IN_STOCK:
        qs = qs.filter(Q(available__gt=0)).exclude(LOW_Q)
    elif f.status == "BACKORDERED":
        qs = qs.filter(Q(backordered__gt=0))
    if f.no_reorder_level:
        qs = qs.filter(reorder_level=0)
    return qs


def status_of(available: Decimal, reorder_level: Decimal) -> str:
    if available <= 0:
        return StockStatus.OUT
    if reorder_level > 0 and available <= reorder_level:
        return StockStatus.LOW
    return StockStatus.IN_STOCK


def stock_product(product_id: UUID) -> Product | None:
    found: Product | None = (
        with_stock(catalog_products()).prefetch_related("barcodes").filter(pk=product_id).first()
    )
    return found


# --- Lookup for scanning ---------------------------------------------------------------------


def lookup(code: str) -> Product | None:
    """A product by barcode or code (exact, case-insensitive for codes), with its stock."""
    code = "".join(code.split())
    if not code:
        return None
    qs = with_stock(catalog_products())
    found: Product | None = (
        qs.filter(barcodes__barcode=code).first() or qs.filter(code__iexact=code).first()
    )
    return found


# --- Movements ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class MovementFilters:
    product_id: UUID | None = None
    movement_type: str = ""
    reference_type: str = ""
    reference_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


def movements(filters: MovementFilters | None = None) -> QuerySet[StockMovement]:
    f = filters or MovementFilters()
    qs = StockMovement.objects.select_related("product", "product__unit", "created_by")
    if f.product_id:
        qs = qs.filter(product_id=f.product_id)
    if f.movement_type:
        qs = qs.filter(movement_type=f.movement_type)
    if f.reference_type:
        qs = qs.filter(reference_type=f.reference_type)
    if f.reference_id:
        qs = qs.filter(reference_id=f.reference_id)
    if f.date_from:
        qs = qs.filter(created_at__date__gte=f.date_from)
    if f.date_to:
        qs = qs.filter(created_at__date__lte=f.date_to)
    return qs


# --- Receipts and adjustments ------------------------------------------------------------------


def receipts(*, status: str = "", awaiting_cost: bool = False) -> QuerySet[StockInward]:
    qs: QuerySet[StockInward] = StockInward.objects.select_related(
        "posted_by", "created_by"
    ).annotate(line_count=Count("lines"))
    if status:
        qs = qs.filter(status=status)
    if awaiting_cost:
        qs = qs.filter(cost_pending_lines__gt=0)
    return qs


def receipt(inward_id: UUID) -> StockInward | None:
    found: StockInward | None = (
        receipts()
        .prefetch_related("lines__product__unit", "lines__product__pack_unit")
        .filter(pk=inward_id)
        .first()
    )
    return found


def receipts_awaiting_cost_count() -> int:
    return StockInward.objects.filter(cost_pending_lines__gt=0).count()


def adjustments() -> QuerySet[StockAdjustment]:
    qs: QuerySet[StockAdjustment] = StockAdjustment.objects.select_related("created_by").annotate(
        line_count=Count("lines")
    )
    return qs


def adjustment(adjustment_id: UUID) -> StockAdjustment | None:
    found: StockAdjustment | None = (
        adjustments().prefetch_related("lines__product__unit").filter(pk=adjustment_id).first()
    )
    return found


# --- Alerts ------------------------------------------------------------------------------------


def alerts(*, status: str = "OPEN", alert_type: str = "") -> QuerySet[StockAlert]:
    qs = StockAlert.objects.select_related("product", "product__unit")
    if status:
        qs = qs.filter(status=status)
    if alert_type:
        qs = qs.filter(alert_type=alert_type)
    return qs


def alert_counts() -> dict[str, int]:
    counts = dict(
        StockAlert.objects.filter(status="OPEN")
        .values_list("alert_type")
        .annotate(n=Count("id"))
        .values_list("alert_type", "n")
    )
    return {t: counts.get(t, 0) for t in StockAlert.Type.values}


# --- Reports -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportFilters:
    category_id: UUID | None = None
    brand_id: UUID | None = None


def _report_products(filters: ReportFilters) -> QuerySet[Product]:
    return with_stock(
        catalog_products(ProductFilters(category_id=filters.category_id, brand_id=filters.brand_id))
    )


def low_stock(filters: ReportFilters | None = None) -> QuerySet[Product]:
    """Products at or below their reorder level (reorder level above 0), with the shortfall."""
    qs = _report_products(filters or ReportFilters()).filter(
        Q(reorder_level__gt=0, available__lte=F("reorder_level"))
    )
    return qs.annotate(shortfall=F("reorder_level") - F("available"))


def products_without_reorder_level(filters: ReportFilters | None = None) -> int:
    """Active products whose reorder level is 0, so they can never show as low."""
    f = filters or ReportFilters()
    return (
        catalog_products(ProductFilters(category_id=f.category_id, brand_id=f.brand_id))
        .filter(is_active=True, reorder_level=0)
        .count()
    )


def category_paths() -> dict[UUID, str]:
    """``Food > Biscuits`` for every category (3 levels at most)."""
    rows = {c.pk: c for c in Category.objects.all()}

    def path(category: Category) -> str:
        parent = rows.get(category.parent_id) if category.parent_id else None
        return f"{path(parent)} > {category.name}" if parent else category.name

    return {pk: path(c) for pk, c in rows.items()}


@dataclass
class Bucket:
    name: str
    value: Decimal = Decimal("0.00")
    products: int = 0
    missing_cost: int = 0


@dataclass
class Valuation:
    total_value: Decimal = Decimal("0.00")
    products_valued: int = 0
    missing_cost: int = 0
    by_category: list[Bucket] = field(default_factory=list)
    by_brand: list[Bucket] = field(default_factory=list)


def valuation_products(
    filters: ReportFilters | None = None, *, missing_cost: bool | None = None
) -> QuerySet[Product]:
    """Products with stock on hand, valued at quantity x cost price (ADR-041 item 9)."""
    qs = _report_products(filters or ReportFilters()).filter(Q(on_hand__gt=0))
    if missing_cost is True:
        qs = qs.filter(cost_price__isnull=True)
    elif missing_cost is False:
        qs = qs.filter(cost_price__isnull=False)
    return qs


def product_value(product: Any) -> Decimal | None:
    if product.cost_price is None:
        return None
    return stock_value(Decimal(product.on_hand), Decimal(product.cost_price))


def valuation(filters: ReportFilters | None = None) -> Valuation:
    """Totals, and totals by category and brand. Products without a cost price are counted and
    left out of every total. Each product's value is rounded to the paisa before summing, so the
    totals match the rows of the export."""
    categories = category_paths()
    result = Valuation()
    by_category: dict[str, Bucket] = defaultdict(lambda: Bucket(""))
    by_brand: dict[str, Bucket] = defaultdict(lambda: Bucket(""))
    columns = ("on_hand", "cost_price", "category_id", "brand__name")  # on_hand is annotated
    rows = valuation_products(filters).values(*columns)
    for row in rows.iterator(chunk_size=2000):
        category = categories.get(row["category_id"], "") if row["category_id"] else ""
        brand = row["brand__name"] or ""
        buckets = (by_category[category], by_brand[brand])
        for bucket, name in zip(buckets, (category, brand), strict=True):
            bucket.name = name
            bucket.products += 1
        if row["cost_price"] is None:
            result.missing_cost += 1
            for bucket in buckets:
                bucket.missing_cost += 1
            continue
        value = stock_value(row["on_hand"], row["cost_price"])
        result.total_value += value
        result.products_valued += 1
        for bucket in buckets:
            bucket.value += value
    result.by_category = sorted(by_category.values(), key=lambda b: (b.name == "", b.name))
    result.by_brand = sorted(by_brand.values(), key=lambda b: (b.name == "", b.name))
    return result
