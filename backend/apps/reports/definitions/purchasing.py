"""Purchasing reports (ADR-053 item 10), while the purchasing module is on: purchases by supplier.
The value received is a cost column (``costs.view``)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from django.db.models import Count, Q, Sum
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.inventory.models import StockInward, StockInwardLine
from apps.purchasing.models import PurchaseOrder
from apps.reports.registry import PERIOD, Column, Context, Group, Kind, Report, register
from common.dates import ist_bounds, today_ist

ZERO = Decimal("0")
OPEN = (PurchaseOrder.Status.SENT, PurchaseOrder.Status.PARTLY_RECEIVED)
NO_SUPPLIER = "Not linked to a supplier"


def purchases_by_supplier(ctx: Context) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = ctx.once("purchases", lambda: _purchases(ctx))
    return rows


def _purchases(ctx: Context) -> list[dict[str, Any]]:
    first, last = ist_bounds(ctx.params["date_from"], ctx.params["date_to"])
    rows: dict[Any, dict[str, Any]] = defaultdict(
        lambda: {
            "orders_sent": 0,
            "receipts": 0,
            "lines": 0,
            "value": ZERO,
            "open_orders": 0,
            "late_orders": 0,
        }
    )
    names: dict[Any, str] = {}
    received = (
        StockInward.objects.filter(
            status=StockInward.Status.POSTED, posted_at__gte=first, posted_at__lt=last
        )
        .values("supplier_id", "supplier__name")
        .annotate(receipts=Count("id", distinct=True))
        .order_by()
    )
    for r in received:
        rows[r["supplier_id"]]["receipts"] = r["receipts"]
        names[r["supplier_id"]] = r["supplier__name"] or NO_SUPPLIER
    lines = (
        StockInwardLine.objects.filter(
            inward__status=StockInward.Status.POSTED,
            inward__posted_at__gte=first,
            inward__posted_at__lt=last,
        )
        .values("inward__supplier_id")
        .annotate(lines=Count("id"), value=Sum("line_cost"))
        .order_by()
    )
    for r in lines:
        row = rows[r["inward__supplier_id"]]
        row["lines"], row["value"] = r["lines"], r["value"] or ZERO
    orders = (
        PurchaseOrder.objects.values("supplier_id", "supplier__name")
        .annotate(
            sent=Count("id", filter=Q(sent_at__gte=first, sent_at__lt=last)),
            open=Count("id", filter=Q(status__in=OPEN)),
            late=Count("id", filter=Q(status__in=OPEN, expected_date__lt=today_ist())),
        )
        .order_by()
    )
    for r in orders:
        if not (r["sent"] or r["open"]):
            continue
        row = rows[r["supplier_id"]]
        row["orders_sent"], row["open_orders"], row["late_orders"] = r["sent"], r["open"], r["late"]
        names[r["supplier_id"]] = r["supplier__name"]
    out = [
        {"supplier_id": pk, "supplier": names.get(pk, NO_SUPPLIER), **figures}
        for pk, figures in rows.items()
    ]
    out.sort(key=lambda r: (-r["value"], -r["receipts"], r["supplier"]))
    return out


def purchases_totals(ctx: Context) -> dict[str, Any]:
    rows = purchases_by_supplier(ctx)
    return {
        "orders_sent": sum(r["orders_sent"] for r in rows),
        "receipts": sum(r["receipts"] for r in rows),
        "value": sum((r["value"] for r in rows), ZERO),
    }


register(
    Report(
        code="purchases_by_supplier",
        title=gettext_lazy("Purchases by supplier"),
        group=Group.PURCHASING,
        description="What you ordered and received from each supplier, and what is late.",
        permission="purchasing.view",
        feature="purchasing",
        columns=(
            Column("supplier", "Supplier", width=30),
            Column("orders_sent", "Orders sent", Kind.INT, total=True, width=10),
            Column("receipts", "Goods receipts", Kind.INT, total=True, width=10),
            Column("lines", "Lines received", Kind.INT, width=10),
            Column("value", "Value received", Kind.MONEY, cost=True, total=True),
            Column("open_orders", "Open orders", Kind.INT, width=10),
            Column("late_orders", "Late orders", Kind.INT, width=10),
        ),
        filters=PERIOD,
        rows=purchases_by_supplier,
        totals=purchases_totals,
        notes=lambda ctx: [
            _(
                "Goods receipts posted in the period (value before GST, at cost); orders sent in "
                "the period; open and late orders as of today."
            )
        ],
    )
)
