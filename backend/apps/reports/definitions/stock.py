"""Stock reports (ADR-050): stock summary, valuation and low stock (moved into the framework),
movement history, fast / slow / dead / new stock, backorder demand and the fulfilment rate.
Stock values need ``costs.view``."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, F, Max, Min, Sum
from django.db.models.functions import Round

from apps.catalog.selectors import ProductFilters, descendant_ids
from apps.catalog.selectors import product_list as catalog_products
from apps.inventory import selectors as stock
from apps.inventory.models import MovementType, StockMovement
from apps.orders.models import (
    OPEN_STATUSES,
    BackorderAllocation,
    Order,
    OrderEvent,
    OrderLine,
    OrderStatusHistory,
)
from apps.platform.selectors import get_setting
from apps.reports.definitions.sales import INVOICE, grouped
from apps.reports.registry import (
    PERIOD,
    Column,
    Context,
    Filter,
    FilterKind,
    Group,
    Kind,
    Mapped,
    Report,
    register,
)
from common.dates import ist_bounds, to_ist, today_ist
from common.permissions import AllOf, AnyOf
from common.tenancy import require_tenant_id

STOCK = "reports.stock"
VALUE = AllOf(("costs.view", AnyOf((STOCK, "reports.financial"))))
DEMAND = AnyOf((STOCK, "reports.sales", "reports.sales_own"))
ZERO = Decimal("0")
STATUS_LABELS = {"IN_STOCK": "In stock", "LOW": "Low", "OUT": "Out of stock"}

CATEGORY = Filter("category", "Category", FilterKind.ID, entity="category")
BRAND = Filter("brand", "Brand", FilterKind.ID, entity="brand")

CODE = Column("code", "Code", width=14)
NAME = Column("name", "Product", width=36)
CATEGORY_COL = Column("category", "Category", width=22)
BRAND_COL = Column("brand", "Brand", width=16)
UNIT = Column("unit", "Unit", width=8)


def _products(ctx: Context) -> Any:
    p = ctx.params
    return stock.with_stock(
        catalog_products(ProductFilters(category_id=p.get("category"), brand_id=p.get("brand")))
    )


def _paths(ctx: Context) -> dict[Any, str]:
    paths: dict[Any, str] = ctx.once("category_paths", stock.category_paths)
    return paths


def _names(row: dict[str, Any]) -> dict[str, Any]:
    """The query's ``brand_name`` / ``unit_code`` as the report's ``brand`` / ``unit`` columns
    (annotations can't take the names of the model's own fields)."""
    return {**row, "brand": row.get("brand_name") or "", "unit": row.get("unit_code") or ""}


def _money(value: Any) -> Decimal | None:
    return None if value is None else Decimal(value).quantize(Decimal("0.01"))


# --- Stock summary ------------------------------------------------------------------------------


def summary_rows(ctx: Context) -> Mapped:
    status = ctx.params.get("status", "")
    rows: Any = stock.stock_list(
        stock.StockFilters(
            category_id=ctx.params.get("category"),
            brand_id=ctx.params.get("brand"),
            status=status,
        )
    )
    paths = _paths(ctx)

    def complete(r: dict[str, Any]) -> dict[str, Any]:
        cost = r["cost_price"]
        return {
            **_names(r),
            "category": paths.get(r["category_id"], ""),
            "status": STATUS_LABELS[stock.status_of(r["available"], r["reorder_level"])],
            "value": _money(r["on_hand"] * cost) if cost is not None else None,
        }

    values = rows.values(
        "code",
        "name",
        "category_id",
        "on_hand",
        "reserved",
        "available",
        "reorder_level",
        "cost_price",
        product_id=F("id"),
        brand_name=F("brand__name"),
        unit_code=F("unit__code"),
    ).order_by("name", "id")
    return Mapped(values, complete)


def summary_totals(ctx: Context) -> dict[str, Any]:
    rows = stock.stock_list(
        stock.StockFilters(
            category_id=ctx.params.get("category"),
            brand_id=ctx.params.get("brand"),
            status=ctx.params.get("status", ""),
        )
    ).filter(cost_price__isnull=False)
    found = rows.aggregate(value=Sum(Round(F("on_hand") * F("cost_price"), 2)))
    return {"value": found["value"] or ZERO}


register(
    Report(
        code="stock_summary",
        title="Stock summary",
        group=Group.STOCK,
        description="Every product's stock: on hand, held for orders, available and its value.",
        permission=STOCK,
        columns=(
            CODE,
            NAME,
            CATEGORY_COL,
            BRAND_COL,
            UNIT,
            Column("on_hand", "On hand", Kind.QTY),
            Column("reserved", "Held for orders", Kind.QTY),
            Column("available", "Available", Kind.QTY),
            Column("reorder_level", "Reorder level", Kind.QTY),
            Column("status", "Status", width=12),
            Column("cost_price", "Cost price", Kind.MONEY, cost=True),
            Column("value", "Stock value", Kind.MONEY, cost=True, total=True),
        ),
        filters=(
            CATEGORY,
            BRAND,
            Filter(
                "status",
                "Status",
                FilterKind.CHOICE,
                choices=("IN_STOCK", "LOW", "OUT", "BACKORDERED"),
            ),
        ),
        rows=summary_rows,
        totals=summary_totals,
    )
)


# --- Valuation and low stock (moved into the framework) -----------------------------------------


def valuation_rows(ctx: Context) -> Mapped:
    filters = stock.ReportFilters(ctx.params.get("category"), ctx.params.get("brand"))
    paths = _paths(ctx)
    products: Any = stock.valuation_products(filters, missing_cost=False)  # annotated
    rows = products.values(
        "code",
        "name",
        "category_id",
        "on_hand",
        "cost_price",
        product_id=F("id"),
        brand_name=F("brand__name"),
        unit_code=F("unit__code"),
    ).order_by("name", "id")
    return Mapped(
        rows,
        lambda r: {
            **_names(r),
            "category": paths.get(r["category_id"], ""),
            "value": _money(r["on_hand"] * r["cost_price"]),
        },
    )


def valuation_totals(ctx: Context) -> dict[str, Any]:
    result = stock.valuation(
        stock.ReportFilters(ctx.params.get("category"), ctx.params.get("brand"))
    )
    return {"value": result.total_value}


def valuation_notes(ctx: Context) -> list[str]:
    result = stock.valuation(
        stock.ReportFilters(ctx.params.get("category"), ctx.params.get("brand"))
    )
    if not result.missing_cost:
        return []
    return [f"{result.missing_cost} product(s) in stock have no cost price and are left out."]


register(
    Report(
        code="stock_valuation",
        title="Stock valuation",
        group=Group.STOCK,
        description="Stock on hand valued at cost price.",
        permission=VALUE,
        columns=(
            CODE,
            NAME,
            CATEGORY_COL,
            BRAND_COL,
            UNIT,
            Column("on_hand", "On hand", Kind.QTY),
            Column("cost_price", "Cost price", Kind.MONEY, cost=True),
            Column("value", "Stock value", Kind.MONEY, cost=True, total=True),
        ),
        filters=(CATEGORY, BRAND),
        rows=valuation_rows,
        totals=valuation_totals,
        notes=valuation_notes,
    )
)


def low_rows(ctx: Context) -> Mapped:
    filters = stock.ReportFilters(ctx.params.get("category"), ctx.params.get("brand"))
    paths = _paths(ctx)
    low: Any = stock.low_stock(filters)  # annotated with available and shortfall
    rows = low.values(
        "code",
        "name",
        "category_id",
        "available",
        "reorder_level",
        "shortfall",
        product_id=F("id"),
        brand_name=F("brand__name"),
        unit_code=F("unit__code"),
    ).order_by("name", "id")
    return Mapped(rows, lambda r: {**_names(r), "category": paths.get(r["category_id"], "")})


def low_notes(ctx: Context) -> list[str]:
    filters = stock.ReportFilters(ctx.params.get("category"), ctx.params.get("brand"))
    missing = stock.products_without_reorder_level(filters)
    if not missing:
        return []
    return [f"{missing} active product(s) have no reorder level, so they never show as low."]


register(
    Report(
        code="low_stock",
        title="Low stock",
        group=Group.STOCK,
        description="Products at or below their reorder level.",
        permission=STOCK,
        columns=(
            CODE,
            NAME,
            CATEGORY_COL,
            BRAND_COL,
            UNIT,
            Column("available", "Available", Kind.QTY),
            Column("reorder_level", "Reorder level", Kind.QTY),
            Column("shortfall", "Short by", Kind.QTY),
        ),
        filters=(CATEGORY, BRAND),
        rows=low_rows,
        notes=low_notes,
    )
)


# --- Movement history ---------------------------------------------------------------------------

MOVEMENT_LABELS = dict(MovementType.choices)


def movement_rows(ctx: Context) -> Mapped:
    p = ctx.params
    first, last = ist_bounds(p["date_from"], p["date_to"])
    rows = StockMovement.objects.filter(created_at__gte=first, created_at__lt=last)
    if p.get("product"):
        rows = rows.filter(product_id=p["product"])
    if p.get("movement_type"):
        rows = rows.filter(movement_type=p["movement_type"])
    values = rows.values(
        "created_at",
        "movement_type",
        "delta_on_hand",
        "on_hand_after",
        "reference_number",
        "reason",
        "value",
        "product_id",
        code=F("product__code"),
        name=F("product__name"),
        unit_code=F("product__unit__code"),
    ).order_by("-created_at", "-id")
    return Mapped(
        values,
        lambda r: {
            **_names(r),
            "when": to_ist(r["created_at"]).strftime("%d-%m-%Y %H:%M"),
            "type": MOVEMENT_LABELS.get(r["movement_type"], r["movement_type"]),
        },
    )


register(
    Report(
        code="stock_movements",
        title="Stock movement history",
        group=Group.STOCK,
        description="Every change to stock: received, dispatched, returned, adjusted.",
        permission=STOCK,
        columns=(
            Column("when", "When", width=18),
            CODE,
            NAME,
            Column("type", "What happened", width=22),
            Column("delta_on_hand", "Change", Kind.QTY),
            Column("on_hand_after", "On hand after", Kind.QTY),
            UNIT,
            Column("reference_number", "Reference", width=20),
            Column("reason", "Reason", width=30),
            Column("value", "Value", Kind.MONEY, cost=True),
        ),
        filters=(
            *PERIOD,
            Filter("product", "Product", FilterKind.ID, entity="product"),
            Filter(
                "movement_type",
                "What happened",
                FilterKind.CHOICE,
                choices=tuple(MovementType.values),
            ),
        ),
        rows=movement_rows,
        max_days=92,
    )
)


# --- Fast, slow, dead and new stock -------------------------------------------------------------

CLASS_ORDER = {"Fast": 0, "Slow": 1, "New": 2, "Dead": 3}
FIRST_STOCKED = (MovementType.INWARD, MovementType.ADJUSTMENT_IN)


def movement_class_rows(ctx: Context) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = ctx.once("movement_class", lambda: _movement_class(ctx))
    wanted = ctx.params.get("class")
    return [r for r in rows if not wanted or r["class"] == wanted.title()]


def _movement_class(ctx: Context) -> list[dict[str, Any]]:
    tenant = require_tenant_id()
    days = int(get_setting("reports.movement_days", tenant))
    share = int(get_setting("reports.fast_share_percent", tenant))
    end = today_ist()
    start = end - timedelta(days=days - 1)
    period = Context(
        {
            "date_from": start,
            "date_to": end,
            **{k: ctx.params.get(k) for k in ("category", "brand")},
        },
        ctx.scope,
    )
    sold = grouped(period, F(INVOICE.product + "_id"), F("invoice_line__product_id"))
    by_quantity = ctx.params.get("rank_by") == "quantity"
    ranked = sorted(
        (pk for pk, f in sold.items() if (f.qty if by_quantity else f.taxable) > 0),
        key=lambda pk: -(sold[pk].qty if by_quantity else sold[pk].taxable),
    )
    fast = set(ranked[: math.ceil(len(ranked) * share / 100)])
    products = {
        r["id"]: r
        for r in _products(ctx).values(
            "id",
            "code",
            "name",
            "category_id",
            "on_hand",
            "cost_price",
            brand_name=F("brand__name"),
        )
    }
    first_stocked = dict(
        StockMovement.objects.filter(movement_type__in=FIRST_STOCKED)
        .values("product_id")
        .annotate(first=Min("created_at"))
        .values_list("product_id", "first")
        .order_by()
    )
    last_sale = dict(stock_last_sales())
    first_moment, _ = ist_bounds(start, end)
    paths = _paths(ctx)
    out = []
    for pk, product in products.items():
        f = sold.get(pk)
        on_hand = product["on_hand"]
        if pk in fast:
            label = "Fast"
        elif pk in ranked:
            label = "Slow"
        elif pk in first_stocked and first_stocked[pk] >= first_moment:
            label = "New"
        elif on_hand > 0:
            label = "Dead"
        else:
            continue  # nothing sold and nothing in stock
        cost = product["cost_price"]
        out.append(
            {
                "product_id": pk,
                "class": label,
                "code": product["code"],
                "name": product["name"],
                "category": paths.get(product["category_id"], ""),
                "brand": product["brand_name"] or "",
                "sold_qty": f.qty if f else ZERO,
                "sales_value": _money(f.taxable) if f else ZERO,
                "on_hand": on_hand,
                "last_sale": last_sale.get(pk),
                "stock_value": _money(on_hand * cost) if cost is not None else None,
            }
        )
    out.sort(key=lambda r: (CLASS_ORDER[r["class"]], -r["sales_value"], r["name"]))
    return out


def stock_last_sales() -> Any:
    from apps.billing.models import DocumentStatus, InvoiceLine

    return (
        InvoiceLine.objects.filter(invoice__status=DocumentStatus.ISSUED)
        .values("product_id")
        .annotate(last=Max("invoice__invoice_date"))
        .values_list("product_id", "last")
        .order_by()
    )


def movement_class_totals(ctx: Context) -> dict[str, Any]:
    rows = movement_class_rows(ctx)
    return {
        "sales_value": sum((r["sales_value"] for r in rows), ZERO),
        "stock_value": sum((r["stock_value"] or ZERO for r in rows), ZERO),
    }


def movement_class_notes(ctx: Context) -> list[str]:
    tenant = require_tenant_id()
    days = int(get_setting("reports.movement_days", tenant))
    share = int(get_setting("reports.fast_share_percent", tenant))
    basis = "quantity" if ctx.params.get("rank_by") == "quantity" else "sales value"
    return [
        f"Over the last {days} days. Fast: the top {share}% of products that sold, by {basis}; "
        "slow: the rest that sold; dead: in stock, nothing sold; new: first stocked in this "
        "period and not sold yet."
    ]


register(
    Report(
        code="stock_movement_class",
        title="Fast, slow and dead stock",
        group=Group.STOCK,
        description="Which products sell fast, slowly or not at all (and which are new).",
        permission=STOCK,
        columns=(
            Column("class", "Class", width=8),
            CODE,
            NAME,
            CATEGORY_COL,
            BRAND_COL,
            Column("sold_qty", "Sold", Kind.QTY),
            Column("sales_value", "Sales (taxable)", Kind.MONEY, total=True),
            Column("on_hand", "On hand", Kind.QTY),
            Column("last_sale", "Last sold", Kind.DATE, width=12),
            Column("stock_value", "Stock value", Kind.MONEY, cost=True, total=True),
        ),
        filters=(
            Filter(
                "rank_by",
                "Rank by",
                FilterKind.CHOICE,
                choices=("value", "quantity"),
                default=lambda: "value",
            ),
            Filter("class", "Class", FilterKind.CHOICE, choices=("fast", "slow", "dead", "new")),
            CATEGORY,
            BRAND,
        ),
        rows=movement_class_rows,
        totals=movement_class_totals,
        notes=movement_class_notes,
    )
)


# --- Backorder demand ---------------------------------------------------------------------------


def demand_rows(ctx: Context) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = ctx.once("demand", lambda: _demand(ctx))
    return rows


def _demand(ctx: Context) -> list[dict[str, Any]]:
    lines = ctx.shops(
        OrderLine.objects.filter(qty_backordered__gt=0, order__status__in=OPEN_STATUSES),
        "order__retailer",
    )
    if ctx.params.get("category"):
        lines = lines.filter(product__category_id__in=descendant_ids(ctx.params["category"]))
    if ctx.params.get("brand"):
        lines = lines.filter(product__brand_id=ctx.params["brand"])
    waiting = (
        lines.values("product_id")
        .annotate(
            shops=Count("order__retailer_id", distinct=True),
            qty=Sum("qty_backordered"),
            oldest=Min("order__placed_at"),
            value=Sum(Round(F("qty_backordered") * F("unit_price"), 2)),
        )
        .order_by()
    )
    proposed = dict(
        BackorderAllocation.objects.filter(status=BackorderAllocation.Status.PROPOSED)
        .values("product_id")
        .annotate(q=Sum("quantity"))
        .values_list("product_id", "q")
        .order_by()
    )
    found = {r["product_id"]: r for r in waiting}
    stocked: Any = stock.with_stock(catalog_products(ProductFilters()).filter(pk__in=found))
    products = {
        p["id"]: p
        for p in stocked.values("id", "code", "name", "available", unit_code=F("unit__code"))
    }
    rows = []
    for pk, r in found.items():
        p = products.get(pk, {})
        rows.append(
            {
                "product_id": pk,
                "code": p.get("code", ""),
                "name": p.get("name", ""),
                "unit": p.get("unit_code", ""),
                "shops": r["shops"],
                "qty": r["qty"],
                "oldest": to_ist(r["oldest"]).date() if r["oldest"] else None,
                "available": p.get("available", ZERO),
                "proposed": proposed.get(pk, ZERO),
                "value": r["value"],
            }
        )
    rows.sort(key=lambda r: (-r["qty"], r["name"]))
    return rows


register(
    Report(
        code="backorder_demand",
        title="Backorder demand",
        group=Group.STOCK,
        description="What shops are waiting for, how long, and what could go out now.",
        permission=DEMAND,
        full="reports.sales",
        columns=(
            CODE,
            NAME,
            UNIT,
            Column("shops", "Shops waiting", Kind.INT, width=10),
            Column("qty", "Waiting", Kind.QTY),
            Column("oldest", "Oldest order", Kind.DATE, width=12),
            Column("available", "Available now", Kind.QTY),
            Column("proposed", "Proposed to send", Kind.QTY),
            Column("value", "Value waiting", Kind.MONEY, total=True),
        ),
        filters=(CATEGORY, BRAND),
        rows=demand_rows,
        totals=lambda ctx: {"value": sum((r["value"] or ZERO for r in demand_rows(ctx)), ZERO)},
    )
)


# --- Fulfilment rate ----------------------------------------------------------------------------


def _period_start(day: date, by: str) -> date:
    if by == "month":
        return day.replace(day=1)
    return day - timedelta(days=day.weekday())


def fulfilment_rows(ctx: Context) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = ctx.once("fulfilment", lambda: _fulfilment(ctx))
    return rows


def _fulfilment(ctx: Context) -> list[dict[str, Any]]:
    p = ctx.params
    by = p.get("group_by", "month")
    first, last = ist_bounds(p["date_from"], p["date_to"])
    orders = ctx.shops(Order.objects.filter(placed_at__gte=first, placed_at__lt=last))
    if p.get("shop"):
        orders = orders.filter(retailer_id=p["shop"])
    if p.get("salesperson"):
        orders = orders.filter(salesperson_id=p["salesperson"])
    by_shop = OrderStatusHistory.ActorType.RETAILER
    cancelled_by_shop = set(
        OrderStatusHistory.objects.filter(
            order__in=orders, event=OrderEvent.CANCEL, actor_type=by_shop
        ).values_list("order_id", flat=True)
    )
    # Backorder quantities the shop cancelled, per order and product code (the history's
    # payload): left out of what was ordered.
    shop_cancelled: dict[tuple[Any, str], Decimal] = defaultdict(lambda: ZERO)
    for order_id, payload in OrderStatusHistory.objects.filter(
        order__in=orders, event=OrderEvent.BACKORDER_CANCELLED, actor_type=by_shop
    ).values_list("order_id", "payload"):
        shop_cancelled[(order_id, payload.get("product", ""))] += Decimal(
            str(payload.get("quantity") or "0")
        )
    periods: dict[date, dict[str, Any]] = {}
    lines = OrderLine.objects.filter(order__in=orders).values(
        "order_id",
        "product_code",
        "qty_ordered",
        "qty_delivered",
        "order__status",
        "order__placed_at",
    )
    per_order: dict[Any, dict[str, Any]] = {}
    for line in lines:
        if line["order_id"] in cancelled_by_shop:
            continue
        o = per_order.setdefault(
            line["order_id"],
            {
                "day": to_ist(line["order__placed_at"]).date(),
                "open": line["order__status"] in OPEN_STATUSES,
                "ordered": ZERO,
                "delivered": ZERO,
                "full": True,
            },
        )
        ordered = (
            Decimal(line["qty_ordered"]) - shop_cancelled[(line["order_id"], line["product_code"])]
        )
        o["ordered"] += max(ordered, ZERO)
        o["delivered"] += Decimal(line["qty_delivered"])
        if Decimal(line["qty_delivered"]) < ordered:
            o["full"] = False
    for o in per_order.values():
        start = _period_start(o["day"], by)
        row = periods.setdefault(
            start,
            {
                "start": start,
                "orders": 0,
                "open": 0,
                "in_full": 0,
                "ordered": ZERO,
                "delivered": ZERO,
            },
        )
        row["orders"] += 1
        if o["open"]:
            row["open"] += 1
            continue
        row["ordered"] += o["ordered"]
        row["delivered"] += o["delivered"]
        row["in_full"] += 1 if o["full"] else 0
    out = []
    for start in sorted(periods):
        row = periods[start]
        closed = row["orders"] - row["open"]
        out.append(
            {
                "period": f"{start:%b %Y}" if by == "month" else f"Week of {start:%d-%m-%Y}",
                **row,
                "in_full_pct": Decimal(row["in_full"] * 100) / closed if closed else None,
                "delivered_pct": row["delivered"] * 100 / row["ordered"]
                if row["ordered"]
                else None,
            }
        )
    return out


def fulfilment_totals(ctx: Context) -> dict[str, Any]:
    rows = fulfilment_rows(ctx)
    total = {
        k: sum((r[k] for r in rows), ZERO)
        for k in ("orders", "open", "in_full", "ordered", "delivered")
    }
    closed = total["orders"] - total["open"]
    total["in_full_pct"] = total["in_full"] * 100 / closed if closed else None
    total["delivered_pct"] = (
        total["delivered"] * 100 / total["ordered"] if total["ordered"] else None
    )
    return total


register(
    Report(
        code="fulfilment_rate",
        title="Order fulfilment rate",
        group=Group.STOCK,
        description="How much of what shops ordered was delivered, by order date.",
        permission=AnyOf(("reports.sales", "reports.sales_own", STOCK)),
        full="reports.sales",
        columns=(
            Column("period", "Period", width=18),
            Column("orders", "Orders", Kind.INT, total=True, width=8),
            Column("open", "Still open", Kind.INT, total=True, width=10),
            Column("in_full", "Delivered in full", Kind.INT, total=True, width=12),
            Column("in_full_pct", "In full %", Kind.PERCENT, total=True, width=10),
            Column("delivered_pct", "Quantity delivered %", Kind.PERCENT, total=True, width=12),
        ),
        filters=(
            *PERIOD,
            Filter(
                "group_by",
                "By",
                FilterKind.CHOICE,
                choices=("week", "month"),
                default=lambda: "month",
            ),
            Filter("shop", "Shop", FilterKind.ID, entity="shop"),
            Filter("salesperson", "Salesperson", FilterKind.ID, entity="staff"),
        ),
        rows=fulfilment_rows,
        totals=fulfilment_totals,
        notes=lambda ctx: [
            "Orders the shop cancelled, and waiting quantities the shop cancelled, are left out. "
            "Percentages count orders that are no longer open."
        ],
    )
)
