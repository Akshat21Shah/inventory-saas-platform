"""Stock planning quantities in a distributor's terms (ADR-053, final review).

- Units that can't be split (PCS, BOX…): whole numbers, always rounded up, for reorder points and
  quantities to order; units that can be split (KG, LTR…): up to 2 decimals, rounded up. A
  quantity to order then goes up to the supplier's pack.
- Demand is told per day from 1 a day, else per week from 1 a week, else per month (30 days):
  "about 2 a month", never "0.067 a day". The rate is to the nearest whole number for units that
  can't be split (0: less than 1 a month), to 2 decimals otherwise.
"""

import math
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from django.db import models

ONE = Decimal("1")
CENT = Decimal("0.01")
QTY = Decimal("0.001")  # how quantities are stored


class RatePeriod(models.TextChoices):
    DAY = "DAY", "A day"
    WEEK = "WEEK", "A week"
    MONTH = "MONTH", "A month"


def up(quantity: Decimal, whole: bool) -> Decimal:
    """Rounded up: to a whole number for units that can't be split, else to 2 decimals."""
    return quantity.quantize(ONE if whole else CENT, ROUND_CEILING).quantize(QTY)


def up_to_pack(quantity: Decimal, pack: Decimal | None, whole: bool) -> Decimal:
    """A quantity to order: rounded up for its unit, then up to the supplier's pack."""
    rounded = up(quantity, whole)
    if pack:
        return (Decimal(math.ceil(rounded / pack)) * pack).quantize(QTY)
    return rounded


def demand_rate(demand_qty: Decimal, demand_days: int, whole: bool) -> tuple[Decimal, str]:
    """(quantity, period) for "about {quantity} a {period}", from what shops ordered over the
    demand period (exact, not the rounded daily figure)."""
    per_day = demand_qty / demand_days if demand_days else Decimal("0")
    if per_day >= 1:
        amount, period = per_day, RatePeriod.DAY
    elif per_day * 7 >= 1:
        amount, period = per_day * 7, RatePeriod.WEEK
    else:
        amount, period = per_day * 30, RatePeriod.MONTH
    return amount.quantize(ONE if whole else CENT, ROUND_HALF_UP), str(period)
