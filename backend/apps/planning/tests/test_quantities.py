"""Planning quantities in a distributor's terms (ADR-053, final review): rounding up for whole and
split units, the supplier's pack, and demand per day, week or month."""

from decimal import Decimal as D

import pytest

from apps.planning.quantities import demand_rate, up, up_to_pack


@pytest.mark.parametrize(
    ("quantity", "whole", "expected"),
    [
        ("0.938", True, "1"),  # never "reorder at 0.938 PCS"
        ("48", True, "48"),
        ("47.001", True, "48"),
        ("4.662", False, "4.67"),  # split units: 2 decimals, still up
        ("4.660", False, "4.66"),
        ("0.001", False, "0.01"),
    ],
)
def test_reorder_points_and_quantities_round_up(quantity, whole, expected):
    assert up(D(quantity), whole) == D(expected)


@pytest.mark.parametrize(
    ("quantity", "pack", "whole", "expected"),
    [
        ("84", "10", True, "90"),
        ("80.2", "10", True, "90"),  # 81 first, then the pack
        ("1.876", None, True, "2"),
        ("7.824", None, False, "7.83"),
        ("2.341", "2.5", False, "2.5"),
    ],
)
def test_quantities_go_up_to_the_suppliers_pack(quantity, pack, whole, expected):
    assert up_to_pack(D(quantity), D(pack) if pack else None, whole) == D(expected)


@pytest.mark.parametrize(
    ("demand", "days", "whole", "expected"),
    [
        ("60", 30, True, ("2", "DAY")),
        ("30", 30, True, ("1", "DAY")),  # from 1 a day
        ("2", 30, True, ("2", "MONTH")),  # "about 2 a month", not 0.067 a day
        ("6", 30, True, ("1", "WEEK")),  # 1.4 a week
        ("6", 30, False, ("1.40", "WEEK")),
        ("10", 30, False, ("2.33", "WEEK")),
        ("1", 180, True, ("0", "MONTH")),  # less than 1 a month
        ("0", 30, True, ("0", "MONTH")),
        ("5", 0, True, ("0", "MONTH")),
    ],
)
def test_demand_per_day_week_or_month(demand, days, whole, expected):
    quantity, period = demand_rate(D(demand), days, whole)
    assert (quantity, period) == (D(expected[0]), expected[1])
