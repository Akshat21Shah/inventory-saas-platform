"""The distributor's dashboard (ADR-050 item 11): first what needs action today, then today's
"Orders received" and "Billed", then trends. Each part is worked out only for someone with its
permission (``None`` otherwise), and sales staff who see only their own shops get their own
shops' figures."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, Min, Sum
from django.db.models.functions import TruncDay

from apps.accounts.models import User
from apps.inventory import selectors as stock
from apps.ledger.selectors import receivables_summary
from apps.orders.selectors import orders_for, tab_counts
from apps.platform.selectors import is_feature_enabled
from apps.reports import engine
from apps.reports.definitions.sales import CREDIT, INVOICE, grouped, product_rows, shop_rows
from apps.reports.registry import Context, Scope
from apps.retailers.selectors import retailers_for
from common.dates import ist_bounds, today_ist
from common.tenancy import require_tenant_id

ZERO = Decimal("0")
TREND_DAYS = 30
TOP = 5


def _money(value: Any) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _sales_scope(user: User) -> Scope | None:
    """The scope of money figures (sales reports' rule), or None without a sales report."""
    if not (
        user.has_permission_code("reports.sales") or user.has_permission_code("reports.sales_own")
    ):
        return None
    return Scope(user.pk, engine.own_shops_only(user, "reports.sales"), costs=False)


def action(user: User) -> dict[str, Any]:
    has = user.has_permission_code
    tenant = require_tenant_id()
    out: dict[str, Any] = dict.fromkeys(
        (
            "new_orders",
            "on_hold",
            "backorders_to_confirm",
            "to_pack",
            "failed_irns",
            "failed_ewaybills",
            "handover",
            "overdue",
            "low_stock",
            "to_reorder",
            "late_purchase_orders",
        )
    )
    if has("orders.view"):
        counts = tab_counts(user)
        out.update(
            new_orders=counts["new"],
            on_hold=counts["on_hold"],
            backorders_to_confirm=counts["proposals"],
            to_pack=counts["to_pack"],
        )
    if has("compliance.manage"):
        from apps.compliance import selectors as compliance

        if is_feature_enabled("einvoice", tenant):
            out["failed_irns"] = compliance.counts()["failed"]
        if is_feature_enabled("ewaybill", tenant):
            out["failed_ewaybills"] = compliance.ewaybill_counts()["failed"]
    if has("payments.record"):
        from apps.payments.selectors import collections_pending_handover

        pending = collections_pending_handover()
        out["handover"] = {
            "count": sum(p.count for p in pending),
            "amount": sum((p.amount for p in pending), ZERO),
        }
    if has("ledger.view"):
        summary = receivables_summary(retailers_for(user).values_list("pk", flat=True))
        out["overdue"] = {"shops": summary["shops_overdue"], "amount": summary["overdue"]}
    if has("stock.view"):
        out["low_stock"] = {
            "low": stock.low_stock().count(),
            "out": stock.stock_list(stock.StockFilters(status=stock.StockStatus.OUT)).count(),
        }
    # ADR-053: products to reorder (stock planning) and purchase orders late (purchasing).
    if (has("purchasing.view") or has("stock.view")) and is_feature_enabled(
        "stock_planning", tenant
    ):
        from apps.planning.selectors import open_suggestion_count

        out["to_reorder"] = open_suggestion_count()
    if has("purchasing.view") and is_feature_enabled("purchasing", tenant):
        from apps.purchasing.selectors import OrderFilters, purchase_orders

        out["late_purchase_orders"] = purchase_orders(OrderFilters(late=True)).count()
    return out


def today(user: User) -> dict[str, Any]:
    day = today_ist()
    out: dict[str, Any] = {"orders_received": None, "billed": None}
    if user.has_permission_code("orders.view"):
        first, last = ist_bounds(day, day)
        placed = orders_for(user).filter(placed_at__gte=first, placed_at__lt=last)
        found = placed.aggregate(count=Count("pk"), value=Sum("grand_total"))
        out["orders_received"] = {"count": found["count"], "amount": _money(found["value"])}
    scope = _sales_scope(user)
    if scope is not None:
        ctx = Context({"date_from": day, "date_to": day}, scope)
        figures = grouped(ctx, INVOICE_DAY, CREDIT_DAY, counts=False)
        out["billed"] = _money(sum((f.total for f in figures.values()), ZERO))
    return out


INVOICE_DAY = TruncDay(INVOICE.day)
CREDIT_DAY = TruncDay(CREDIT.day)


def _day(value: Any) -> date:
    found: date = value.date() if hasattr(value, "hour") else value
    return found


def trends(user: User) -> dict[str, Any] | None:
    scope = _sales_scope(user)
    if scope is None:
        return None
    end = today_ist()
    start = end - timedelta(days=2 * TREND_DAYS - 1)
    daily = {
        _day(k): f.total
        for k, f in grouped(
            Context({"date_from": start, "date_to": end}, scope),
            INVOICE_DAY,
            CREDIT_DAY,
            counts=False,
        ).items()
    }
    days = [end - timedelta(days=TREND_DAYS - 1 - i) for i in range(TREND_DAYS)]
    month = Context({"date_from": end.replace(day=1), "date_to": end}, scope)
    ordering = orders_for(user)  # already limited to own shops where that applies
    month_start, month_end = ist_bounds(end.replace(day=1), end)
    this_month = set(
        ordering.filter(placed_at__gte=month_start, placed_at__lt=month_end).values_list(
            "retailer_id", flat=True
        )
    )
    first_orders = dict(
        ordering.filter(retailer_id__in=this_month)
        .values("retailer_id")
        .annotate(first=Min("placed_at"))
        .values_list("retailer_id", "first")
        .order_by()
    )
    new = sum(1 for pk in this_month if first_orders.get(pk) and first_orders[pk] >= month_start)
    return {
        "days": [
            {
                "date": day,
                "billed": _money(daily.get(day, ZERO)),
                "previous": _money(daily.get(day - timedelta(days=TREND_DAYS), ZERO)),
            }
            for day in days
        ],
        "billed_30_days": _money(sum((daily.get(d, ZERO) for d in days), ZERO)),
        "billed_previous_30_days": _money(
            sum((daily.get(d - timedelta(days=TREND_DAYS), ZERO) for d in days), ZERO)
        ),
        "top_products": [
            {"product_id": r["product_id"], "name": r["name"], "total": _money(r["total"])}
            for r in product_rows(month, counts=False)[:TOP]
        ],
        "top_shops": [
            {"retailer_id": r["retailer_id"], "name": r["name"], "total": _money(r["total"])}
            for r in shop_rows(month, counts=False)[:TOP]
        ],
        "new_shops": new,
        "repeat_shops": len(this_month) - new,
    }


def dashboard(user: User) -> dict[str, Any]:
    return {
        "action": action(user),
        "today": today(user),
        "trends": trends(user),
        "own_shops": engine.own_shops_only(user, "reports.sales"),
    }
