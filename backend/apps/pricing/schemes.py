"""Free-goods schemes (ADR-056 items 7-9): which scheme a shop gets on a product and how many
units it earns. The quote (``orders/quote.py``) adds the free lines; nothing here writes.

- A scheme earns ``free_qty`` for every ``buy_qty`` bought (``repeat``), or once when the line
  reaches ``buy_qty``; ``max_free_qty`` caps the free quantity per order line.
- One scheme per bought product applies: the one giving the most free units at the line's
  quantity; ties go to the most specific audience (shop > price list > everyone), then the newest.
- The hint ("Add 2 more to get 1 free") is for the applied scheme's next step, or, before any
  scheme is reached, for the one with the smallest quantity to buy.
- The order line keeps the scheme's terms (``rule``), so later changes to the scheme never change
  what an order earns.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Q

from apps.platform.selectors import is_feature_enabled
from apps.pricing.models import FreeGoodsScheme
from apps.retailers.models import Retailer
from common.dates import today_ist

FLAG = "free_goods"
ZERO = Decimal("0")
_AUDIENCE_RANK = {"RETAILER": 3, "PRICE_LIST": 2, "ALL": 1}


@dataclass(frozen=True)
class Terms:
    scheme_id: UUID
    name: str
    buy_product_id: UUID
    buy_qty: Decimal
    free_product_id: UUID
    free_qty: Decimal
    repeat: bool
    max_free_qty: Decimal | None
    free_product_name: str = ""
    free_unit: str = ""
    rank: int = 1  # audience: shop 3, price list 2, everyone 1
    created_at: datetime | None = None

    @property
    def same_product(self) -> bool:
        return self.free_product_id == self.buy_product_id

    @classmethod
    def of(cls, scheme: FreeGoodsScheme) -> Terms:
        return cls(
            scheme_id=scheme.pk,
            name=scheme.name,
            buy_product_id=scheme.buy_product_id,
            buy_qty=Decimal(scheme.buy_qty),
            free_product_id=scheme.free_product_id,
            free_qty=Decimal(scheme.free_qty),
            repeat=scheme.repeat,
            max_free_qty=None if scheme.max_free_qty is None else Decimal(scheme.max_free_qty),
            free_product_name=scheme.free_product.name,
            free_unit=scheme.free_product.unit.code,
            rank=_AUDIENCE_RANK.get(scheme.audience_type, 1),
            created_at=scheme.created_at,
        )

    def rule(self) -> dict[str, Any]:
        """The terms kept on the order line (JSON)."""
        cap = self.max_free_qty
        return {
            "buy_qty": f"{self.buy_qty.normalize():f}",
            "free_qty": f"{self.free_qty.normalize():f}",
            "repeat": self.repeat,
            "max_free_qty": None if cap is None else f"{cap.normalize():f}",
        }

    @classmethod
    def from_line(cls, line: Any) -> Terms:
        """The terms an order line was given (``scheme_rule``), for what it still earns."""
        rule = line.scheme_rule or {}
        cap = rule.get("max_free_qty")
        source = line.free_of_line if line.free_of_line_id else line
        return cls(
            scheme_id=line.scheme_id,
            name=line.scheme_name,
            buy_product_id=source.product_id,
            buy_qty=Decimal(rule["buy_qty"]),
            free_product_id=line.product_id,
            free_qty=Decimal(rule["free_qty"]),
            repeat=bool(rule.get("repeat", True)),
            max_free_qty=None if cap is None else Decimal(cap),
            free_product_name=line.product_name,
            free_unit=line.unit_code,
        )

    def earned(self, bought: Decimal) -> Decimal:
        """Free units for ``bought`` units on one line."""
        if bought < self.buy_qty or self.buy_qty <= 0:
            return ZERO
        times = math.floor(bought / self.buy_qty) if self.repeat else 1
        free = self.free_qty * times
        if self.max_free_qty is not None:
            free = min(free, self.max_free_qty)
        return free

    def next_step(self, bought: Decimal) -> tuple[Decimal, Decimal] | None:
        """(how many more to buy, how many more free) for the next free units; none when the
        line already earns all it can."""
        now = self.earned(bought)
        if self.max_free_qty is not None and now >= self.max_free_qty:
            return None
        if bought < self.buy_qty:
            target = self.buy_qty
        elif self.repeat:
            target = (math.floor(bought / self.buy_qty) + 1) * self.buy_qty
        else:
            return None
        return target - bought, self.earned(target) - now


def enabled(tenant_id: UUID) -> bool:
    return bool(is_feature_enabled(FLAG, tenant_id))


def for_shop(
    retailer: Retailer, product_ids: Iterable[UUID] | None = None, *, on: date | None = None
) -> dict[UUID, list[Terms]]:
    """The schemes this shop can get today, by bought product (the flag is the caller's)."""
    day = on or today_ist()
    audience = Q(audience_type="ALL") | Q(audience_type="RETAILER", retailer_id=retailer.pk)
    if retailer.price_list_id:
        audience |= Q(audience_type="PRICE_LIST", price_list_id=retailer.price_list_id)
    qs = (
        FreeGoodsScheme.objects.filter(audience, is_active=True)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=day))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=day))
        .filter(free_product__is_active=True, free_product__deleted_at__isnull=True)
        .select_related("free_product__unit")
    )
    if product_ids is not None:
        qs = qs.filter(buy_product_id__in=list(product_ids))
    found: dict[UUID, list[Terms]] = defaultdict(list)
    for scheme in qs:
        found[scheme.buy_product_id].append(Terms.of(scheme))
    return dict(found)


def _newest(terms: Terms) -> float:
    return terms.created_at.timestamp() if terms.created_at else 0.0


def best(options: list[Terms], bought: Decimal) -> Terms | None:
    """The scheme that applies at ``bought``: most free units, then audience, then newest."""
    earning = [t for t in options if t.earned(bought) > 0]
    if not earning:
        return None
    return max(earning, key=lambda t: (t.earned(bought), t.rank, _newest(t)))


def headline(options: list[Terms]) -> Terms | None:
    """The scheme to show on a product: the smallest quantity to buy, then audience, newest."""
    if not options:
        return None
    return min(options, key=lambda t: (t.buy_qty, -t.rank, -_newest(t)))


def headlines(retailer: Retailer, product_ids: Iterable[UUID]) -> dict[UUID, Terms]:
    """The scheme to show on each product card ("Buy 10 get 1 free"); none with the flag off."""
    if not enabled(retailer.tenant_id):
        return {}
    found = for_shop(retailer, product_ids)
    return {pid: chosen for pid, options in found.items() if (chosen := headline(options))}


def hint(options: list[Terms], bought: Decimal) -> tuple[Terms, Decimal, Decimal] | None:
    """(scheme, buy this many more, get this many more free) for the cart."""
    chosen = best(options, bought) or headline(options)
    if chosen is None:
        return None
    step = chosen.next_step(bought)
    return None if step is None else (chosen, step[0], step[1])
