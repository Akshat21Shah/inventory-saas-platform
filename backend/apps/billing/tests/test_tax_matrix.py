"""The exhaustive matrix of PLAN §6.4: every rate, supply type, price basis, discount kind,
quantity and price, under every value of every tax-relevant setting (tax.prices_include_gst x
tax.component_rounding x invoicing.round_to_rupee x invoicing.round_off_method). Each case checks
the invariants every invoice must satisfy (ADR-009)."""

import itertools
from decimal import Decimal as D

import pytest

from apps.billing.tax import (
    ComponentRounding,
    Discount,
    DiscountType,
    RoundOffMethod,
    SupplyType,
    compute_document,
    compute_line,
    round2,
)

RATES = [D(r) for r in ("0", "0.25", "3", "5", "12", "18", "28", "40")]
QUANTITIES = [D(q) for q in ("1", "0.001", "2.750", "99999")]
PRICES = [D(p) for p in ("0.01", "7.00", "123.45", "9999999.99")]
DISCOUNTS = [
    None,
    Discount(DiscountType.PERCENT, D("7.5")),
    Discount(DiscountType.FLAT_PER_UNIT, D("1.50")),
    Discount(DiscountType.FLAT_PER_UNIT, D("99999999")),  # more than the gross: capped
]
# Every combination of the four settings (rupee rounding off ignores the method).
SETTINGS = [
    (inclusive, rounding, to_rupee, method)
    for inclusive in (False, True)
    for rounding in ComponentRounding
    for to_rupee in (True, False)
    for method in (RoundOffMethod if to_rupee else [RoundOffMethod.NEAREST])
]
ROUND_OFF_RANGE = {
    RoundOffMethod.NEAREST: (D("-0.49"), D("0.50")),
    RoundOffMethod.UP: (D("0.00"), D("0.99")),
    RoundOffMethod.DOWN: (D("-0.99"), D("0.00")),
}


@pytest.mark.parametrize(("inclusive", "rounding", "to_rupee", "method"), SETTINGS)
def test_every_line_and_document_under_every_setting(inclusive, rounding, to_rupee, method):
    lines = []
    for rate, supply, discount, qty, price in itertools.product(
        RATES, SupplyType, DISCOUNTS, QUANTITIES, PRICES
    ):
        line = compute_line(
            qty=qty,
            unit_price=price,
            rate=rate,
            supply_type=supply,
            discount=discount,
            inclusive=inclusive,
            rounding=rounding,
        )
        # Amounts are paise, never negative; the discount never exceeds the gross.
        for amount in (line.gross, line.discount, line.taxable, line.cgst, line.igst, line.cess):
            assert amount == round2(amount) and amount >= 0, (rate, qty, price)
        assert line.discount <= line.gross
        assert line.discount_excl <= line.gross_excl
        # The line adds up.
        assert line.line_total == line.taxable + line.cgst + line.sgst + line.igst + line.cess
        if supply == SupplyType.INTRA:
            assert line.cgst == line.sgst and line.igst == 0
            assert line.cgst_rate == line.sgst_rate == rate / 2
        else:
            assert line.cgst == line.sgst == 0
            assert line.igst_rate == rate
        if inclusive:
            # What the shop pays for the line is within a paisa of the price shown.
            assert abs(line.line_total - (line.gross - line.discount)) <= D("0.01")
            assert line.gross_excl - line.discount_excl == line.taxable
        else:
            assert line.taxable == line.gross - line.discount
        lines.append(line)

    for chunk in (lines[:7], lines[100:163], lines):
        document = compute_document(chunk, round_to_rupee=to_rupee, round_off_method=method)
        assert document.grand_total == document.lines_total + document.round_off
        assert document.lines_total == sum((x.line_total for x in chunk), D("0"))
        assert document.taxable == sum((x.taxable for x in chunk), D("0"))
        if to_rupee:
            low, high = ROUND_OFF_RANGE[method]
            assert low <= document.round_off <= high
            assert document.grand_total == document.grand_total.to_integral_value()
        else:
            assert document.round_off == 0


def test_the_matrix_covers_every_setting_value():
    """A new setting value (e.g. a new rounding method) must be added to the matrix."""
    assert {s[0] for s in SETTINGS} == {False, True}
    assert {s[1] for s in SETTINGS} == set(ComponentRounding)
    assert {s[2] for s in SETTINGS} == {False, True}
    assert {s[3] for s in SETTINGS if s[2]} == set(RoundOffMethod)
    from apps.platform.registry import REGISTRY

    for key, values in {
        "tax.component_rounding": {m.value for m in ComponentRounding},
        "invoicing.round_off_method": {m.value for m in RoundOffMethod},
    }.items():
        assert set(REGISTRY[key].allowed) == values, key
