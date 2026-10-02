"""The daily summary (ADR-056 items 5-6): yesterday's figures and what needs action now, for one
person, with only what their permissions show (the dashboard's own rules). The texts are plain
lines; the WhatsApp version joins them with " · " (template values can't hold line breaks)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Count, Sum

from apps.accounts.models import User
from apps.billing.templatetags.documents import rupees
from apps.reports import dashboard


@dataclass(frozen=True)
class Summary:
    yesterday: list[str]
    attention: list[str]


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def yesterday_lines(user: User, day: date) -> list[str]:
    from apps.payments.models import Payment
    from apps.payments.selectors import payments_for
    from apps.retailers.selectors import retailers_for
    from common.dates import ist_bounds

    lines: list[str] = []
    figures = dashboard.today(user, day)
    received = figures["orders_received"]
    if received is not None:
        lines.append(
            "No orders"
            if received["count"] == 0
            else f"{_plural(received['count'], 'order', 'orders')} received "
            f"({rupees(received['amount'])})"
        )
    if figures["billed"] is not None:
        lines.append(f"billed {rupees(figures['billed'])}")
    if user.has_permission_code("payments.view"):
        paid = (
            payments_for(user)
            .filter(payment_date=day)
            .exclude(status__in=(Payment.Status.REVERSED, Payment.Status.BOUNCED))
            .aggregate(count=Count("pk"), amount=Sum("amount"))
        )
        if paid["count"]:
            lines.append(
                f"collected {rupees(paid['amount'])} "
                f"({_plural(paid['count'], 'payment', 'payments')})"
            )
    if user.has_permission_code("retailers.view"):
        first, last = ist_bounds(day, day)
        new = retailers_for(user).filter(created_at__gte=first, created_at__lt=last).count()
        if new:
            lines.append(_plural(new, "new shop", "new shops"))
    return lines


def attention_lines(user: User) -> list[str]:
    a = dashboard.action(user)
    lines: list[str] = []

    def add(count: int | None, one: str, many: str) -> None:
        if count:
            lines.append(_plural(count, one, many))

    add(a["new_orders"], "new order to accept", "new orders to accept")
    add(a["on_hold"], "order on credit hold", "orders on credit hold")
    add(a["backorders_to_confirm"], "backorder to confirm", "backorders to confirm")
    add(a["to_pack"], "shipment to pack", "shipments to pack")
    if a["overdue"] and a["overdue"]["shops"]:
        lines.append(
            f"{_plural(a['overdue']['shops'], 'shop', 'shops')} overdue "
            f"({rupees(a['overdue']['amount'])})"
        )
    if a["low_stock"]:
        add(
            a["low_stock"]["low"] + a["low_stock"]["out"],
            "product low or out of stock",
            "products low or out of stock",
        )
    add(a["to_reorder"], "product to reorder", "products to reorder")
    add(a["late_purchase_orders"], "purchase order late", "purchase orders late")
    add(a["failed_irns"], "IRN failed", "IRNs failed")
    add(a["failed_ewaybills"], "e-way bill failed", "e-way bills failed")
    add(a["win_back"], "shop to win back", "shops to win back")
    return lines


def summary_for(user: User, day: date) -> Summary:
    return Summary(yesterday_lines(user, day), attention_lines(user))
