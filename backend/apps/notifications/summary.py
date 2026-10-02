"""The daily summary (ADR-056 items 5-6): yesterday's figures and what needs action now, for one
person, with only what their permissions show (the dashboard's own rules). The texts are plain
lines; the WhatsApp version joins them with " · " (template values can't hold line breaks)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import Count, Sum
from django.utils.translation import gettext as _
from django.utils.translation import ngettext, ngettext_lazy

from apps.accounts.models import User
from apps.billing.templatetags.documents import rupees
from apps.reports import dashboard


@dataclass(frozen=True)
class Summary:
    yesterday: list[str]
    attention: list[str]


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
            _("No orders")
            if received["count"] == 0
            else ngettext(
                "%(count)s order received (%(amount)s)",
                "%(count)s orders received (%(amount)s)",
                received["count"],
            )
            % {"count": received["count"], "amount": rupees(received["amount"])}
        )
    if figures["billed"] is not None:
        lines.append(_("billed %(amount)s") % {"amount": rupees(figures["billed"])})
    if user.has_permission_code("payments.view"):
        paid = (
            payments_for(user)
            .filter(payment_date=day)
            .exclude(status__in=(Payment.Status.REVERSED, Payment.Status.BOUNCED))
            .aggregate(count=Count("pk"), amount=Sum("amount"))
        )
        if paid["count"]:
            lines.append(
                ngettext(
                    "collected %(amount)s (%(count)s payment)",
                    "collected %(amount)s (%(count)s payments)",
                    paid["count"],
                )
                % {"count": paid["count"], "amount": rupees(paid["amount"])}
            )
    if user.has_permission_code("retailers.view"):
        first, last = ist_bounds(day, day)
        new = retailers_for(user).filter(created_at__gte=first, created_at__lt=last).count()
        if new:
            lines.append(
                ngettext("%(count)s new shop", "%(count)s new shops", new) % {"count": new}
            )
    return lines


def attention_lines(user: User) -> list[str]:
    a = dashboard.action(user)
    lines: list[str] = []

    def add(count: int | None, message: Any) -> None:
        """``message``: an ``ngettext_lazy`` whose plural form follows "count"."""
        if count:
            lines.append(message % {"count": count})

    add(
        a["new_orders"],
        ngettext_lazy("%(count)s new order to accept", "%(count)s new orders to accept", "count"),
    )
    add(
        a["on_hold"],
        ngettext_lazy("%(count)s order on credit hold", "%(count)s orders on credit hold", "count"),
    )
    add(
        a["backorders_to_confirm"],
        ngettext_lazy("%(count)s backorder to confirm", "%(count)s backorders to confirm", "count"),
    )
    add(
        a["to_pack"],
        ngettext_lazy("%(count)s shipment to pack", "%(count)s shipments to pack", "count"),
    )
    if a["overdue"] and a["overdue"]["shops"]:
        lines.append(
            ngettext(
                "%(count)s shop overdue (%(amount)s)",
                "%(count)s shops overdue (%(amount)s)",
                a["overdue"]["shops"],
            )
            % {"count": a["overdue"]["shops"], "amount": rupees(a["overdue"]["amount"])}
        )
    if a["low_stock"]:
        add(
            a["low_stock"]["low"] + a["low_stock"]["out"],
            ngettext_lazy(
                "%(count)s product low or out of stock",
                "%(count)s products low or out of stock",
                "count",
            ),
        )
    add(
        a["to_reorder"],
        ngettext_lazy("%(count)s product to reorder", "%(count)s products to reorder", "count"),
    )
    add(
        a["late_purchase_orders"],
        ngettext_lazy("%(count)s purchase order late", "%(count)s purchase orders late", "count"),
    )
    add(a["failed_irns"], ngettext_lazy("%(count)s IRN failed", "%(count)s IRNs failed", "count"))
    add(
        a["failed_ewaybills"],
        ngettext_lazy("%(count)s e-way bill failed", "%(count)s e-way bills failed", "count"),
    )
    add(
        a["win_back"],
        ngettext_lazy("%(count)s shop to win back", "%(count)s shops to win back", "count"),
    )
    add(
        a["return_requests"],
        ngettext_lazy(
            "%(count)s return request to decide", "%(count)s return requests to decide", "count"
        ),
    )
    return lines


def summary_for(user: User, day: date) -> Summary:
    return Summary(yesterday_lines(user, day), attention_lines(user))
