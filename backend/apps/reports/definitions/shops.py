"""Shop activity (ADR-056 item 3): each shop's ordering pattern and segment, as last worked out,
with the shops to win back first. Order values are sales figures (a sales-report permission);
sales staff limited to their own shops see only those."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.insights.models import Segment, ShopActivity
from apps.reports.definitions.sales import SALES
from apps.reports.registry import Column, Context, Filter, FilterKind, Group, Kind, Report, register

SALESPERSON = Filter("salesperson", "Salesperson", FilterKind.ID, entity="staff")
SEGMENT = Filter("segment", "Segment", FilterKind.CHOICE, choices=tuple(Segment.values))


def shop_activity(ctx: Context) -> list[dict[str, Any]]:
    rows = ctx.shops(
        ShopActivity.objects.select_related("retailer", "retailer__salesperson"), "retailer"
    ).filter(retailer__deleted_at__isnull=True)
    if ctx.params.get("salesperson"):
        rows = rows.filter(retailer__salesperson_id=ctx.params["salesperson"])
    if ctx.params.get("segment"):
        rows = rows.filter(segment=ctx.params["segment"])
    labels = dict(Segment.choices)
    out = []
    for row in rows.order_by("-urgency", "retailer__shop_name"):
        person = row.retailer.salesperson
        out.append(
            {
                "retailer_id": row.retailer_id,
                "code": row.retailer.code,
                "name": row.retailer.shop_name,
                "salesperson": (person.full_name or person.email) if person else "",
                "segment": labels[row.segment],
                "last_order": row.last_order_date,
                "days_since": row.days_since_last,
                "usual_gap": row.usual_gap_days,
                "orders_90": row.orders_90,
                "orders_prev_90": row.orders_prev_90,
                "value_90": row.value_90,
                "value_prev_90": row.value_prev_90,
                "last_contact": row.last_contact_at.date() if row.last_contact_at else None,
            }
        )
    return out


register(
    Report(
        code="shop_activity",
        title=gettext_lazy("Shop activity"),
        group=Group.SALES,
        description="Who is ordering less or has stopped: each shop's last order, usual gap and "
        "the last 90 days against the 90 before.",
        permission=SALES,
        full="reports.sales",
        columns=(
            Column("code", "Code", width=12),
            Column("name", "Shop", width=30),
            Column("salesperson", "Salesperson", width=20),
            Column("segment", "Segment", width=18),
            Column("last_order", "Last order", Kind.DATE, width=12),
            Column("days_since", "Days since", Kind.INT, width=10),
            Column("usual_gap", "Usual gap (days)", Kind.QTY, width=12),
            Column("orders_90", "Orders, last 90 days", Kind.INT, total=True, width=12),
            Column("orders_prev_90", "Orders, 90 days before", Kind.INT, total=True, width=12),
            Column("value_90", "Value, last 90 days", Kind.MONEY, total=True),
            Column("value_prev_90", "Value, 90 days before", Kind.MONEY, total=True),
            Column("last_contact", "Last contacted", Kind.DATE, width=12),
        ),
        filters=(SEGMENT, SALESPERSON),
        rows=shop_activity,
        notes=lambda ctx: [
            _(
                "As worked out last night (or when someone asked). Values are order totals "
                "incl. GST."
            )
        ],
    )
)
