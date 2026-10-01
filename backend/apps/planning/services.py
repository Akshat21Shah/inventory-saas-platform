"""Product stats (ADR-053 item 3): worked out per distributor, nightly and when staff ask.

- **Demand:** the quantity ordered (base unit) in the last ⚙ ``planning.demand_days`` days, from
  orders placed in that period: rejected orders and orders the shop itself cancelled are left out;
  orders the distributor cancelled still count (the shop wanted the goods).
- **Per day** is demand ÷ days; **days of stock** is what is available (on hand less reserved) ÷
  per day in whole days, rounded down, none when nothing was ordered.
- **ABC class** by sales value (taxable, net of credit notes) over ⚙ ``reports.movement_days``:
  ranked from the top, a product is A while the products above it make less than
  ⚙ ``planning.abc_a_percent`` of the value, B while they make less than ⚙
  ``planning.abc_b_percent``, then C; none when it sold nothing.
- **Movement class** exactly as the "Fast, slow and dead stock" report ranks by value: fast, the top
  ⚙ ``reports.fast_share_percent`` of products that sold; slow, the rest that sold; new, first
  stocked in the period and not sold; dead, in stock and not sold.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import F, Min, Q, Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.selectors import ProductFilters
from apps.catalog.selectors import product_list as catalog_products
from apps.inventory import selectors as stock
from apps.inventory.models import MovementType, StockMovement
from apps.orders.models import OrderLine, OrderStatus
from apps.planning.models import AbcClass, MovementClass, ProductStats
from apps.platform.selectors import get_setting
from apps.reports.definitions.sales import grouped
from apps.reports.definitions.stock import stock_last_sales
from apps.reports.registry import Context, Scope
from common.dates import ist_bounds, today_ist
from common.tenancy import require_tenant_id

ZERO = Decimal("0")
QTY = Decimal("0.001")
TENTH = Decimal("0.1")
NOBODY = UUID(int=0)  # the reports' scope needs a user; the stats cover every shop
FIRST_STOCKED = (MovementType.INWARD, MovementType.ADJUSTMENT_IN)


def demand_by_product(start: date, end: date) -> dict[UUID, Decimal]:
    """Quantity ordered per product on the Indian dates ``start`` to ``end``."""
    first, last = ist_bounds(start, end)
    rows = (
        OrderLine.objects.filter(order__placed_at__gte=first, order__placed_at__lt=last)
        .exclude(order__status=OrderStatus.REJECTED)
        .exclude(
            Q(order__status=OrderStatus.CANCELLED)
            & Q(order__cancelled_by__user_type=User.UserType.RETAILER)
        )
        .values("product_id")
        .annotate(qty=Sum("qty_ordered"))
        .order_by()
    )
    return {row["product_id"]: row["qty"] for row in rows}


def sales_value_by_product(start: date, end: date) -> dict[UUID, Decimal]:
    """Taxable value sold per product (invoices less credit notes), as the sales reports count."""
    period = Context(
        {"date_from": start, "date_to": end}, Scope(NOBODY, own_shops=False, costs=False)
    )
    sold = grouped(
        period, F("product_id"), F("invoice_line__product_id"), costs=False, counts=False
    )
    return {pk: figures.taxable for pk, figures in sold.items()}


def abc_classes(values: dict[UUID, Decimal], a_percent: int, b_percent: int) -> dict[UUID, str]:
    ranked = sorted((pk for pk, v in values.items() if v > 0), key=lambda pk: -values[pk])
    total = sum((values[pk] for pk in ranked), ZERO)
    out: dict[UUID, str] = {}
    above = ZERO  # the value of the products ranked above this one
    for pk in ranked:
        share = above * 100 / total
        out[pk] = (
            AbcClass.A if share < a_percent else AbcClass.B if share < b_percent else AbcClass.C
        )
        above += values[pk]
    return out


def movement_classes(
    values: dict[UUID, Decimal],
    on_hand: dict[UUID, Decimal],
    first_stocked: dict[UUID, Any],
    period_start: Any,
    fast_percent: int,
) -> dict[UUID, str]:
    ranked = sorted((pk for pk, v in values.items() if v > 0), key=lambda pk: -values[pk])
    fast = set(ranked[: math.ceil(len(ranked) * fast_percent / 100)])
    sold = set(ranked)
    out: dict[UUID, str] = {}
    for pk, quantity in on_hand.items():
        if pk in fast:
            out[pk] = MovementClass.FAST
        elif pk in sold:
            out[pk] = MovementClass.SLOW
        elif pk in first_stocked and first_stocked[pk] >= period_start:
            out[pk] = MovementClass.NEW
        elif quantity > 0:
            out[pk] = MovementClass.DEAD
    return out


def _first_stocked() -> dict[UUID, Any]:
    return dict(
        StockMovement.objects.filter(movement_type__in=FIRST_STOCKED)
        .values("product_id")
        .annotate(first=Min("created_at"))
        .values_list("product_id", "first")
        .order_by()
    )


def refresh_stats(*, today: date | None = None) -> int:
    """Work out every product's figures for the active distributor; returns how many."""
    tenant = require_tenant_id()
    today = today or today_ist()
    demand_days = int(get_setting("planning.demand_days", tenant))
    movement_days = int(get_setting("reports.movement_days", tenant))
    fast_percent = int(get_setting("reports.fast_share_percent", tenant))
    a_percent = int(get_setting("planning.abc_a_percent", tenant))
    b_percent = int(get_setting("planning.abc_b_percent", tenant))

    demand = demand_by_product(today - timedelta(days=demand_days - 1), today)
    movement_start = today - timedelta(days=movement_days - 1)
    values = sales_value_by_product(movement_start, today)
    listed: Any = stock.with_stock(catalog_products(ProductFilters()))  # annotated: on_hand, …
    products = {row["id"]: row for row in listed.values("id", "on_hand", "available")}
    abc = abc_classes(values, a_percent, b_percent)
    movement = movement_classes(
        values,
        {pk: row["on_hand"] for pk, row in products.items()},
        _first_stocked(),
        ist_bounds(movement_start, today)[0],
        fast_percent,
    )
    last_sale = dict(stock_last_sales())
    now = timezone.now()
    rows = []
    for pk, product in products.items():
        ordered = demand.get(pk, ZERO)
        per_day = (ordered / demand_days).quantize(QTY, ROUND_HALF_UP)
        available = product["available"]
        days = None
        if per_day > 0:  # whole days, rounded down (urgency first)
            days = Decimal(int(max(available, ZERO) / per_day)).quantize(TENTH)
        rows.append(
            ProductStats(
                tenant_id=tenant,
                product_id=pk,
                computed_at=now,
                demand_days=demand_days,
                demand_qty=ordered,
                per_day=per_day,
                movement_days=movement_days,
                sold_value=values.get(pk, ZERO).quantize(Decimal("0.01")),
                abc_class=abc.get(pk),
                movement_class=movement.get(pk),
                last_sale_date=last_sale.get(pk),
                available=available,
                days_of_stock=days,
            )
        )
    with transaction.atomic():
        # Products deleted since the last run lose their figures.
        ProductStats.objects.exclude(product_id__in=list(products)).delete()
        ProductStats.objects.bulk_create(
            rows,
            batch_size=1000,
            update_conflicts=True,
            unique_fields=["product"],
            update_fields=[
                "computed_at",
                "demand_days",
                "demand_qty",
                "per_day",
                "movement_days",
                "sold_value",
                "abc_class",
                "movement_class",
                "last_sale_date",
                "available",
                "days_of_stock",
            ],
        )
    return len(rows)
