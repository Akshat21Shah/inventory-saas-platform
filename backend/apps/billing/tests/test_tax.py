"""PLAN §6.3 worked examples (fixed tests) and properties of the line/document math (§6.4).
The full invoice matrix (amount in words, HSN summary, credit notes) arrives in Phase 5."""

from decimal import Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.billing.tax import (
    ComponentRounding,
    Discount,
    DiscountType,
    LineTax,
    RoundOffMethod,
    SupplyType,
    compute_document,
    compute_line,
)

INTRA, INTER = SupplyType.INTRA, SupplyType.INTER


def pct(value: str) -> Discount:
    return Discount(DiscountType.PERCENT, D(value))


def flat(value: str) -> Discount:
    return Discount(DiscountType.FLAT_PER_UNIT, D(value))


def ex1(rounding: ComponentRounding = ComponentRounding.HALF_UP) -> LineTax:
    return compute_line(
        qty=D("10"), unit_price=D("123.45"), rate=D("18"), supply_type=INTRA, rounding=rounding
    )


def test_ex1_intra_state_no_discount():
    line = ex1()
    assert (line.gross, line.discount, line.taxable) == (D("1234.50"), D("0.00"), D("1234.50"))
    assert (line.cgst, line.sgst, line.igst, line.line_total) == (
        D("111.11"),
        D("111.11"),
        D("0.00"),
        D("1456.72"),
    )
    assert (line.cgst_rate, line.sgst_rate) == (D("9"), D("9"))
    doc = compute_document([line])
    assert (doc.grand_total, doc.round_off) == (D("1457.00"), D("0.28"))


def test_ex2_inter_state_same_line():
    line = compute_line(qty=D("10"), unit_price=D("123.45"), rate=D("18"), supply_type=INTER)
    assert (line.igst, line.cgst, line.line_total, line.igst_rate) == (
        D("222.21"),
        D("0.00"),
        D("1456.71"),
        D("18"),
    )
    doc = compute_document([line])
    assert (doc.grand_total, doc.round_off) == (D("1457.00"), D("0.29"))


def test_ex3_percentage_discount():
    line = compute_line(
        qty=D("24"), unit_price=D("57.50"), rate=D("5"), supply_type=INTRA, discount=pct("7.5")
    )
    assert (line.gross, line.discount, line.taxable) == (D("1380.00"), D("103.50"), D("1276.50"))
    assert (line.cgst, line.sgst, line.line_total) == (D("31.91"), D("31.91"), D("1340.32"))
    doc = compute_document([line])
    assert (doc.grand_total, doc.round_off) == (D("1340.00"), D("-0.32"))


def test_ex4_flat_per_unit_slab_discount_inter_state():
    line = compute_line(
        qty=D("36"), unit_price=D("42.00"), rate=D("18"), supply_type=INTER, discount=flat("1.50")
    )
    assert (line.gross, line.discount, line.taxable, line.igst) == (
        D("1512.00"),
        D("54.00"),
        D("1458.00"),
        D("262.44"),
    )
    doc = compute_document([line])
    assert (doc.grand_total, doc.round_off) == (D("1720.00"), D("-0.44"))


def test_flat_discount_never_exceeds_the_line():
    line = compute_line(
        qty=D("2"), unit_price=D("5.00"), rate=D("18"), supply_type=INTRA, discount=flat("7.00")
    )
    assert (line.discount, line.taxable, line.line_total) == (D("10.00"), D("0.00"), D("0.00"))


def test_ex5_mixed_rates_on_one_document():
    lines = [
        ex1(),
        compute_line(
            qty=D("24"), unit_price=D("57.50"), rate=D("5"), supply_type=INTRA, discount=pct("7.5")
        ),
        compute_line(qty=D("2.750"), unit_price=D("180.00"), rate=D("0"), supply_type=INTRA),
        compute_line(qty=D("5"), unit_price=D("999.99"), rate=D("12"), supply_type=INTRA),
    ]
    assert lines[3].cgst == D("300.00") and lines[3].line_total == D("5599.95")
    doc = compute_document(lines)
    assert (doc.taxable, doc.cgst, doc.sgst, doc.lines_total) == (
        D("8005.95"),
        D("443.02"),
        D("443.02"),
        D("8891.99"),
    )
    assert (doc.grand_total, doc.round_off) == (D("8892.00"), D("0.01"))


def test_ex6_inclusive_price_reconciles_exactly():
    line = compute_line(
        qty=D("3"), unit_price=D("49.99"), rate=D("18"), supply_type=INTRA, inclusive=True
    )
    assert (line.gross, line.taxable, line.cgst, line.sgst, line.line_total) == (
        D("149.97"),
        D("127.09"),
        D("11.44"),
        D("11.44"),
        D("149.97"),
    )


def test_ex7_inclusive_price_with_one_paisa_tolerance():
    line = compute_line(
        qty=D("1"), unit_price=D("7.00"), rate=D("18"), supply_type=INTRA, inclusive=True
    )
    assert (line.taxable, line.cgst, line.sgst, line.line_total) == (
        D("5.93"),
        D("0.53"),
        D("0.53"),
        D("6.99"),
    )
    doc = compute_document([line])
    assert (doc.grand_total, doc.round_off) == (D("7.00"), D("0.01"))


def test_ex8_inclusive_price_with_percentage_discount():
    line = compute_line(
        qty=D("10"),
        unit_price=D("118.00"),
        rate=D("18"),
        supply_type=INTRA,
        discount=pct("10"),
        inclusive=True,
    )
    assert (line.gross, line.discount) == (D("1180.00"), D("118.00"))
    assert (line.gross_excl, line.discount_excl, line.taxable) == (
        D("1000.00"),
        D("100.00"),
        D("900.00"),
    )
    assert (line.cgst, line.sgst, line.line_total) == (D("81.00"), D("81.00"), D("1062.00"))


def test_ex9_rounding_edges():
    half_paisa = compute_line(qty=D("1"), unit_price=D("1.00"), rate=D("1"), supply_type=INTRA)
    assert half_paisa.cgst == D("0.01")  # 0.005 rounds half-up

    def doc_for(total: str) -> tuple[D, D]:
        line = compute_line(qty=D("1"), unit_price=D(total), rate=D("0"), supply_type=INTRA)
        doc = compute_document([line])
        return doc.grand_total, doc.round_off

    assert doc_for("1000.50") == (D("1001.00"), D("0.50"))
    assert doc_for("1000.49") == (D("1000.00"), D("-0.49"))
    quarter = compute_line(qty=D("1"), unit_price=D("100"), rate=D("0.25"), supply_type=INTRA)
    assert (quarter.cgst_rate, quarter.sgst_rate) == (D("0.125"), D("0.125"))


@pytest.mark.parametrize(
    ("rounding", "to_rupee", "method", "component", "lines_total", "grand", "round_off"),
    [
        ("HALF_UP", True, "NEAREST", "111.11", "1456.72", "1457.00", "0.28"),
        ("HALF_UP", True, "DOWN", "111.11", "1456.72", "1456.00", "-0.72"),
        ("HALF_UP", True, "UP", "111.11", "1456.72", "1457.00", "0.28"),
        ("HALF_UP", False, "NEAREST", "111.11", "1456.72", "1456.72", "0.00"),
        ("HALF_EVEN", True, "NEAREST", "111.10", "1456.70", "1457.00", "0.30"),
    ],
)
def test_ex10_non_default_rounding_settings(
    rounding, to_rupee, method, component, lines_total, grand, round_off
):
    line = ex1(ComponentRounding(rounding))
    assert line.cgst == line.sgst == D(component)
    doc = compute_document([line], round_to_rupee=to_rupee, round_off_method=RoundOffMethod(method))
    assert (doc.lines_total, doc.grand_total, doc.round_off) == (
        D(lines_total),
        D(grand),
        D(round_off),
    )


# --- Properties ----------------------------------------------------------------------------------

RATES = [D(r) for r in ("0", "0.25", "3", "5", "12", "18", "28", "40")]
quantities = st.decimals(min_value=D("0.001"), max_value=D("99999"), places=3)
prices = st.decimals(min_value=D("0.01"), max_value=D("9999999.99"), places=2)
discounts = st.one_of(
    st.none(),
    st.decimals(min_value=D("0.01"), max_value=D("100"), places=2).map(
        lambda v: Discount(DiscountType.PERCENT, v)
    ),
    st.decimals(min_value=D("0.01"), max_value=D("100000"), places=2).map(
        lambda v: Discount(DiscountType.FLAT_PER_UNIT, v)
    ),
)
lines = st.builds(
    lambda qty, price, rate, supply, discount, inclusive, rounding: compute_line(
        qty=qty,
        unit_price=price,
        rate=rate,
        supply_type=supply,
        discount=discount,
        inclusive=inclusive,
        rounding=rounding,
    ),
    quantities,
    prices,
    st.sampled_from(RATES),
    st.sampled_from(list(SupplyType)),
    discounts,
    st.booleans(),
    st.sampled_from(list(ComponentRounding)),
)


@settings(max_examples=300, deadline=None)
@given(line=lines)
def test_line_invariants(line):
    assert line.line_total == line.taxable + line.cgst + line.sgst + line.igst + line.cess
    assert line.cgst == line.sgst  # both halves rounded from the same value
    assert line.cgst == 0 or line.igst == 0
    assert 0 <= line.discount <= line.gross
    assert line.gross_excl - line.discount_excl == line.taxable
    for amount in (line.gross, line.discount, line.taxable, line.cgst, line.igst, line.line_total):
        assert amount == amount.quantize(D("0.01"))


@settings(max_examples=300, deadline=None)
@given(
    qty=quantities,
    price=prices,
    rate=st.sampled_from(RATES),
    supply=st.sampled_from(list(SupplyType)),
    discount=discounts,
)
def test_inclusive_lines_stay_within_one_paisa_of_the_price_paid(
    qty, price, rate, supply, discount
):
    line = compute_line(
        qty=qty, unit_price=price, rate=rate, supply_type=supply, discount=discount, inclusive=True
    )
    net_inclusive = line.gross - line.discount
    assert abs(line.line_total - net_inclusive) <= D("0.01")


@settings(max_examples=200, deadline=None)
@given(
    many=st.lists(lines, min_size=1, max_size=8),
    method=st.sampled_from(list(RoundOffMethod)),
    to_rupee=st.booleans(),
)
def test_documents_reconcile_to_the_paisa(many, method, to_rupee):
    doc = compute_document(many, round_to_rupee=to_rupee, round_off_method=method)
    assert doc.grand_total == doc.lines_total + doc.round_off
    assert doc.lines_total == sum((line.line_total for line in many), D("0"))
    assert doc.taxable == sum((line.taxable for line in many), D("0"))
    if not to_rupee:
        assert doc.round_off == 0
    elif method == RoundOffMethod.NEAREST:
        assert D("-0.50") < doc.round_off <= D("0.50")
    elif method == RoundOffMethod.UP:
        assert D("0") <= doc.round_off < D("1")
    else:
        assert D("-1") < doc.round_off <= D("0")
