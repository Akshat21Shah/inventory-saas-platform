"""The daily summary (ADR-056 items 5-6): yesterday's figures and what needs action now, for one
person, with only what their permissions show (the dashboard's own rules). The texts are plain
lines; the WhatsApp version joins them with " · " (template values can't hold line breaks)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from django.db.models import Count, Sum
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.accounts.models import User
from apps.billing.templatetags.documents import rupees
from apps.reports import dashboard
from common.numbers import fill


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
            else fill(
                ngettext(
                    "%(count)s order received (%(amount)s)",
                    "%(count)s orders received (%(amount)s)",
                    received["count"],
                ),
                {"count": received["count"], "amount": rupees(received["amount"])},
            )
        )
    if figures["billed"] is not None:
        lines.append(fill(_("billed %(amount)s"), {"amount": rupees(figures["billed"])}))
    if user.has_permission_code("payments.view"):
        paid = (
            payments_for(user)
            .filter(payment_date=day)
            .exclude(status__in=(Payment.Status.REVERSED, Payment.Status.BOUNCED))
            .aggregate(count=Count("pk"), amount=Sum("amount"))
        )
        if paid["count"]:
            lines.append(
                fill(
                    ngettext(
                        "collected %(amount)s (%(count)s payment)",
                        "collected %(amount)s (%(count)s payments)",
                        paid["count"],
                    ),
                    {"count": paid["count"], "amount": rupees(paid["amount"])},
                )
            )
    if user.has_permission_code("retailers.view"):
        first, last = ist_bounds(day, day)
        new = retailers_for(user).filter(created_at__gte=first, created_at__lt=last).count()
        if new:
            lines.append(
                fill(ngettext("%(count)s new shop", "%(count)s new shops", new), {"count": new})
            )
    return lines


def attention_lines(user: User) -> list[str]:
    a = dashboard.action(user)
    lines: list[str] = []

    def add(count: int | None, message: Callable[[int], str]) -> None:
        """``message(count)``: the line's words for ``count``; the count is grouped (6,029)."""
        if count:
            lines.append(fill(message(count), {"count": count}))

    add(
        a["new_orders"],
        lambda n: ngettext("%(count)s new order to accept", "%(count)s new orders to accept", n),
    )
    add(
        a["on_hold"],
        lambda n: ngettext("%(count)s order on credit hold", "%(count)s orders on credit hold", n),
    )
    add(
        a["backorders_to_confirm"],
        lambda n: ngettext("%(count)s backorder to confirm", "%(count)s backorders to confirm", n),
    )
    add(
        a["to_pack"],
        lambda n: ngettext("%(count)s shipment to pack", "%(count)s shipments to pack", n),
    )
    if a["overdue"] and a["overdue"]["shops"]:
        lines.append(
            fill(
                ngettext(
                    "%(count)s shop overdue (%(amount)s)",
                    "%(count)s shops overdue (%(amount)s)",
                    a["overdue"]["shops"],
                ),
                {"count": a["overdue"]["shops"], "amount": rupees(a["overdue"]["amount"])},
            )
        )
    if a["low_stock"]:
        add(
            a["low_stock"]["low"] + a["low_stock"]["out"],
            lambda n: ngettext(
                "%(count)s product low or out of stock", "%(count)s products low or out of stock", n
            ),
        )
    add(
        a["to_reorder"],
        lambda n: ngettext("%(count)s product to reorder", "%(count)s products to reorder", n),
    )
    add(
        a["late_purchase_orders"],
        lambda n: ngettext("%(count)s purchase order late", "%(count)s purchase orders late", n),
    )
    add(a["failed_irns"], lambda n: ngettext("%(count)s IRN failed", "%(count)s IRNs failed", n))
    add(
        a["failed_ewaybills"],
        lambda n: ngettext("%(count)s e-way bill failed", "%(count)s e-way bills failed", n),
    )
    add(
        a["win_back"],
        lambda n: ngettext("%(count)s shop to win back", "%(count)s shops to win back", n),
    )
    add(
        a["return_requests"],
        lambda n: ngettext(
            "%(count)s return request to decide", "%(count)s return requests to decide", n
        ),
    )
    return lines


def summary_for(user: User, day: date) -> Summary:
    return Summary(yesterday_lines(user, day), attention_lines(user))
