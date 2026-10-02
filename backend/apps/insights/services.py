"""Shop activity (ADR-056 items 1-3), worked out per distributor, nightly and when staff ask.

- **Orders** are those placed by or for the shop, rejected ones and those the shop itself
  cancelled left out (as demand in ADR-053); their value is the order total incl. GST.
- **Usual gap:** the median number of days between the shop's last orders (up to 10, so up to 9
  gaps), when it has at least 3.
- **Segments**, in this order: *never ordered* (no order, added more than 14 days ago; before
  that it is *new*); *new* (first order within ⚙ ``insights.new_days``); *dormant* (no order for ⚙
  ``insights.dormant_days``); *slowing* (days since the last order above ⚙
  ``insights.slowing_percent`` of the usual gap, and at least 7; or the last 90 days' orders at
  most half of the 90 before, from at least 3); otherwise *active*.
- **Win back:** dormant, slowing and never-ordered shops that are active and nobody contacted in
  the last ⚙ ``insights.contact_snooze_days``.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Max, Min, Q, QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.insights.models import WIN_BACK, Segment, ShopActivity, ShopContact
from apps.orders.models import Order, OrderStatus
from apps.platform.selectors import get_setting
from apps.retailers.models import Retailer
from common.dates import ist_bounds, to_ist, today_ist
from common.errors import InvalidFields, NotFound
from common.tenancy import require_tenant_id

ZERO = Decimal("0")
WINDOW_DAYS = 90
GAP_ORDERS = 10
MIN_ORDERS_FOR_GAP = 3
NEVER_ORDERED_AFTER_DAYS = 14
SLOWING_MIN_DAYS = 7
HISTORY_DAYS = 730  # the gaps look back this far at most
# Sorting: the segment first (dormant before slowing before never ordered), then days waited.
WEIGHT = {
    Segment.DORMANT: 4_000_000,
    Segment.SLOWING: 3_000_000,
    Segment.NEVER_ORDERED: 2_000_000,
    Segment.NEW: 1_000_000,
    Segment.ACTIVE: 0,
}


def counted_orders() -> QuerySet[Order]:
    """The active tenant's orders that count for a shop's activity."""
    return Order.objects.exclude(status=OrderStatus.REJECTED).exclude(
        Q(status=OrderStatus.CANCELLED) & Q(cancelled_by__user_type=User.UserType.RETAILER)
    )


@dataclass(frozen=True)
class Thresholds:
    new_days: int
    dormant_days: int
    slowing_percent: int

    @classmethod
    def for_tenant(cls, tenant_id: UUID) -> Thresholds:
        return cls(
            int(get_setting("insights.new_days", tenant_id)),
            int(get_setting("insights.dormant_days", tenant_id)),
            int(get_setting("insights.slowing_percent", tenant_id)),
        )


def usual_gap(order_dates: list[date]) -> Decimal | None:
    """Median days between consecutive orders, from the latest ``GAP_ORDERS`` (newest first or
    any order); none with fewer than ``MIN_ORDERS_FOR_GAP`` orders."""
    latest = sorted(order_dates, reverse=True)[:GAP_ORDERS]
    if len(latest) < MIN_ORDERS_FOR_GAP:
        return None
    gaps = [(a - b).days for a, b in pairwise(latest)]
    return Decimal(str(statistics.median(gaps))).quantize(Decimal("0.1"))


def segment_of(
    *,
    today: date,
    added: date,
    first: date | None,
    last: date | None,
    gap: Decimal | None,
    orders_90: int,
    orders_prev_90: int,
    limits: Thresholds,
) -> str:
    if first is None or last is None:
        too_long = (today - added).days > NEVER_ORDERED_AFTER_DAYS
        return Segment.NEVER_ORDERED if too_long else Segment.NEW
    if (today - first).days < limits.new_days:
        return Segment.NEW
    since = (today - last).days
    if since >= limits.dormant_days:
        return Segment.DORMANT
    late = (
        gap is not None and since >= SLOWING_MIN_DAYS and since > gap * limits.slowing_percent / 100
    )
    halved = orders_prev_90 >= MIN_ORDERS_FOR_GAP and orders_90 * 2 <= orders_prev_90
    return Segment.SLOWING if late or halved else Segment.ACTIVE


def refresh_activity(*, today: date | None = None) -> int:
    """Work out every shop's activity for the active distributor; returns how many shops."""
    tenant = require_tenant_id()
    today = today or today_ist()
    limits = Thresholds.for_tenant(tenant)
    orders = counted_orders()
    span = {
        row["retailer_id"]: (row["first"], row["last"])
        for row in orders.values("retailer_id")
        .annotate(first=Min("placed_at"), last=Max("placed_at"))
        .order_by()
    }
    since = ist_bounds(today - timedelta(days=HISTORY_DAYS), today)[0]
    recent_start = today - timedelta(days=WINDOW_DAYS - 1)
    previous_start = recent_start - timedelta(days=WINDOW_DAYS)
    dates: dict[UUID, list[date]] = defaultdict(list)
    windows: dict[UUID, list[Any]] = defaultdict(lambda: [0, 0, ZERO, ZERO])
    for retailer_id, placed_at, total in orders.filter(placed_at__gte=since).values_list(
        "retailer_id", "placed_at", "grand_total"
    ):
        day = to_ist(placed_at).date()
        dates[retailer_id].append(day)
        figures = windows[retailer_id]
        if recent_start <= day <= today:
            figures[0] += 1
            figures[2] += total
        elif previous_start <= day < recent_start:
            figures[1] += 1
            figures[3] += total
    contacted = dict(
        ShopContact.objects.values("retailer_id")
        .annotate(last=Max("created_at"))
        .values_list("retailer_id", "last")
        .order_by()
    )
    now = timezone.now()
    rows = []
    for shop_id, created_at in Retailer.objects.values_list("pk", "created_at"):
        first_at, last_at = span.get(shop_id, (None, None))
        first = to_ist(first_at).date() if first_at else None
        last = to_ist(last_at).date() if last_at else None
        gap = usual_gap(dates.get(shop_id, []))
        o90, oprev, v90, vprev = windows.get(shop_id, (0, 0, ZERO, ZERO))
        segment = segment_of(
            today=today,
            added=to_ist(created_at).date(),
            first=first,
            last=last,
            gap=gap,
            orders_90=o90,
            orders_prev_90=oprev,
            limits=limits,
        )
        waited = (today - last).days if last else (today - to_ist(created_at).date()).days
        rows.append(
            ShopActivity(
                tenant_id=tenant,
                retailer_id=shop_id,
                computed_at=now,
                segment=segment,
                first_order_date=first,
                last_order_date=last,
                days_since_last=(today - last).days if last else None,
                usual_gap_days=gap,
                orders_90=o90,
                orders_prev_90=oprev,
                value_90=v90,
                value_prev_90=vprev,
                last_contact_at=contacted.get(shop_id),
                urgency=WEIGHT[Segment(segment)] + min(max(waited, 0), 999_999),
            )
        )
    with transaction.atomic():
        ShopActivity.objects.all().delete()
        ShopActivity.objects.bulk_create(rows, batch_size=1000)
    return len(rows)


def snoozed_since(tenant_id: UUID, today: date | None = None) -> Any:
    """Contacts after this moment keep a shop off the win-back list."""
    days = int(get_setting("insights.contact_snooze_days", tenant_id))
    return ist_bounds((today or today_ist()) - timedelta(days=days - 1), today or today_ist())[0]


def win_back_filter(tenant_id: UUID) -> Q:
    """Shops to win back: dormant, slowing or never ordered; active; not contacted lately."""
    return (
        Q(segment__in=WIN_BACK)
        & Q(retailer__status=Retailer.Status.ACTIVE)
        & (Q(last_contact_at__isnull=True) | Q(last_contact_at__lt=snoozed_since(tenant_id)))
    )


@transaction.atomic
def log_contact(
    retailer_id: UUID, *, channel: str, outcome: str, note: str, by: User
) -> ShopContact:
    """Record a call, message or visit; the shop leaves the win-back list for a while."""
    retailer = Retailer.objects.filter(pk=retailer_id).first()
    if retailer is None:
        raise NotFound()
    problems: dict[str, list[str]] = {}
    if channel not in ShopContact.Channel.values:
        problems["channel"] = ["Choose how you contacted the shop."]
    if outcome not in ShopContact.Outcome.values:
        problems["outcome"] = ["Choose what happened."]
    if problems:
        raise InvalidFields(problems)
    contact: ShopContact = ShopContact.objects.create(
        retailer=retailer, by=by, channel=channel, outcome=outcome, note=note.strip()[:500]
    )
    ShopActivity.objects.filter(retailer=retailer).update(last_contact_at=contact.created_at)
    return contact
