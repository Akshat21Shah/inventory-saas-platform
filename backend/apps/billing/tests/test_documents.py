"""Document helpers in billing/tax.py (PLAN §6.1, §6.4, §6.5): amount in words, HSN summary,
financial years, due dates, and credit-note proration without drift."""

from datetime import date, datetime
from decimal import Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.billing.tax import (
    ComponentRounding,
    Components,
    Discount,
    DiscountType,
    RoundOffMethod,
    SupplyType,
    amount_in_words,
    compute_document,
    compute_line,
    credit_for_quantity,
    credit_for_taxable,
    credit_note_totals,
    due_date,
    financial_year,
    fy_short,
    hsn_summary,
)
from common.dates import IST


@pytest.mark.parametrize(
    ("amount", "words"),
    [
        ("0", "Rupees Zero Only"),
        ("1", "Rupees One Only"),
        ("0.50", "Rupees Zero and Fifty Paise Only"),
        ("19", "Rupees Nineteen Only"),
        ("20", "Rupees Twenty Only"),
        ("45", "Rupees Forty Five Only"),
        ("100", "Rupees One Hundred Only"),
        ("1457", "Rupees One Thousand Four Hundred Fifty Seven Only"),
        ("100000", "Rupees One Lakh Only"),
        ("1000000", "Rupees Ten Lakh Only"),
        ("10000000", "Rupees One Crore Only"),
        (
            "12345678.90",
            "Rupees One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight "
            "and Ninety Paise Only",
        ),
        ("1000000000", "Rupees One Hundred Crore Only"),
        ("8892.01", "Rupees Eight Thousand Eight Hundred Ninety Two and One Paise Only"),
    ],
)
def test_amount_in_words_indian_system(amount, words):
    assert amount_in_words(D(amount)) == words


def test_amount_in_words_refuses_negative_amounts():
    with pytest.raises(ValueError):
        amount_in_words(D("-1"))


@pytest.mark.parametrize(
    ("day", "fy"),
    [
        (date(2026, 3, 31), "2025-26"),
        (date(2026, 4, 1), "2026-27"),
        (date(2026, 9, 28), "2026-27"),
        (date(2027, 1, 1), "2026-27"),
        (date(2099, 4, 1), "2099-00"),
    ],
)
def test_financial_year(day, fy):
    assert financial_year(day) == fy


def test_financial_year_uses_the_indian_date():
    # 31 March 2027, 19:00 UTC is already 1 April in India: the new financial year.
    utc = datetime.fromisoformat("2027-03-31T19:00:00+00:00")
    assert utc.date() == date(2027, 3, 31)
    assert financial_year(utc.astimezone(IST).date()) == "2027-28"
    assert fy_short("2026-27") == "26-27"


def test_due_date():
    assert due_date(date(2026, 9, 28), 30) == date(2026, 10, 28)
    assert due_date(date(2026, 9, 28), 0) == date(2026, 9, 28)


def _line(qty, price, rate, supply=SupplyType.INTRA, **kw):
    return compute_line(qty=D(qty), unit_price=D(price), rate=D(rate), supply_type=supply, **kw)


def test_hsn_summary_sums_lines_by_code_and_rate():
    a = _line("10", "123.45", "18")
    b = _line("24", "57.50", "5", discount=Discount(DiscountType.PERCENT, D("7.5")))
    c = _line("2", "100.00", "18")
    rows = hsn_summary([("1905", D("18"), a), ("0902", D("5"), b), ("1905", D("18"), c)])
    assert [(r.hsn, r.rate) for r in rows] == [("0902", D("5")), ("1905", D("18"))]
    biscuits = rows[1]
    assert biscuits.taxable == a.taxable + c.taxable == D("1434.50")
    assert biscuits.cgst == a.cgst + c.cgst == D("129.11")
    assert biscuits.tax == a.tax + c.tax


# --- Credit notes (PLAN §6.5) -------------------------------------------------------------------


def test_return_three_then_seven_reverses_the_line_exactly():
    line = _line("10", "123.45", "18")  # Ex 1
    first = credit_for_quantity(
        D("3"),
        invoiced_qty=D("10"),
        remaining_qty=D("10"),
        line=line,
        remaining=Components.of(line),
    )
    assert (first.taxable, first.cgst, first.sgst, first.total) == (
        D("370.35"),
        D("33.33"),
        D("33.33"),
        D("437.01"),
    )
    rest = Components.of(line).minus(first)
    second = credit_for_quantity(
        D("7"), invoiced_qty=D("10"), remaining_qty=D("7"), line=line, remaining=rest
    )
    assert (second.taxable, second.cgst, second.sgst, second.total) == (
        D("864.15"),
        D("77.78"),
        D("77.78"),
        D("1019.71"),
    )
    assert first.total + second.total == line.line_total == D("1456.72")


def test_credit_note_that_uses_up_the_invoice_lands_on_zero():
    line = _line("10", "123.45", "18")
    invoice = compute_document([line])
    assert invoice.grand_total == D("1457.00")
    first = credit_for_quantity(
        D("3"),
        invoiced_qty=D("10"),
        remaining_qty=D("10"),
        line=line,
        remaining=Components.of(line),
    )
    cn1 = credit_note_totals([first], round_to_rupee=True, round_off_method=RoundOffMethod.NEAREST)
    assert (cn1.grand_total, cn1.round_off) == (D("437.00"), D("-0.01"))
    second = Components.of(line).minus(first)
    cn2 = credit_note_totals(
        [second],
        round_to_rupee=True,
        round_off_method=RoundOffMethod.NEAREST,
        invoice_left=invoice.grand_total - cn1.grand_total,
    )
    assert (cn2.grand_total, cn2.round_off) == (D("1020.00"), D("0.29"))
    assert cn1.grand_total + cn2.grand_total == invoice.grand_total


def test_inter_state_and_value_only_credits():
    line = _line("36", "42.00", "18", SupplyType.INTER)  # Ex 4 without discount
    value = credit_for_taxable(D("100.00"), rates=line, remaining=Components.of(line))
    assert (value.taxable, value.igst, value.cgst) == (D("100.00"), D("18.00"), D("0.00"))
    everything = credit_for_taxable(D("99999"), rates=line, remaining=Components.of(line))
    assert everything == Components.of(line)  # capped at what is left


def test_credit_refuses_nonsense():
    line = _line("10", "123.45", "18")
    with pytest.raises(ValueError):
        credit_for_quantity(
            D("11"),
            invoiced_qty=D("10"),
            remaining_qty=D("10"),
            line=line,
            remaining=Components.of(line),
        )
    with pytest.raises(ValueError):
        credit_for_taxable(D("0"), rates=line, remaining=Components.of(line))


quantities = st.decimals(min_value=D("0.001"), max_value=D("999"), places=3)
prices = st.decimals(min_value=D("0.01"), max_value=D("99999.99"), places=2)
rates = st.sampled_from([D(r) for r in ("0", "0.25", "3", "5", "12", "18", "28", "40")])


@settings(max_examples=300, deadline=None)
@given(
    qty=quantities,
    price=prices,
    rate=rates,
    supply=st.sampled_from(list(SupplyType)),
    rounding=st.sampled_from(list(ComponentRounding)),
    parts=st.lists(st.integers(min_value=1, max_value=9), min_size=1, max_size=6),
)
def test_returns_in_parts_always_reverse_the_line_exactly(
    qty, price, rate, supply, rounding, parts
):
    """Whatever the split, the credit notes for a line add up to the line to the paisa, and no
    credit goes below zero or above what was invoiced."""
    line = compute_line(qty=qty, unit_price=price, rate=rate, supply_type=supply, rounding=rounding)
    remaining_qty, remaining = qty, Components.of(line)
    total_parts = sum(parts)
    credited = []
    for index, part in enumerate(parts):
        q = (
            remaining_qty
            if index == len(parts) - 1
            else min(remaining_qty, (qty * part / total_parts).quantize(D("0.001")))
        )
        if q <= 0:
            continue
        credit = credit_for_quantity(
            q,
            invoiced_qty=qty,
            remaining_qty=remaining_qty,
            line=line,
            remaining=remaining,
            rounding=rounding,
        )
        for part_value in (credit.taxable, credit.cgst, credit.sgst, credit.igst, credit.cess):
            assert part_value >= 0
        if supply == SupplyType.INTRA and q != remaining_qty:
            assert credit.cgst == credit.sgst
        credited.append(credit)
        remaining_qty -= q
        remaining = remaining.minus(credit)
    assert remaining_qty == 0
    assert remaining == Components(D("0.00"), D("0.00"), D("0.00"), D("0.00"), D("0.00"))
    assert sum((c.total for c in credited), D("0")) == line.line_total
