"""GST line and document arithmetic (PLAN §6, ADR-009). The ONLY place where tax or discount
amounts are rounded: pricing estimates, orders and invoices all use it.

Status: ADR-009 is "Accepted — pending CA confirmation before Phase 5". Defaults follow it:
components rounded HALF_UP per line, invoice total rounded to the rupee (NEAREST).

All arithmetic is ``Decimal``. Quantities have 3 decimals, money 2, rates 3.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from enum import StrEnum

PAISA = Decimal("0.01")
RUPEE = Decimal("1")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")


class SupplyType(StrEnum):
    INTRA = "INTRA"  # CGST + SGST
    INTER = "INTER"  # IGST


class DiscountType(StrEnum):
    PERCENT = "PERCENT"
    FLAT_PER_UNIT = "FLAT_PER_UNIT"


class ComponentRounding(StrEnum):
    """⚙ ``tax.component_rounding``."""

    HALF_UP = "HALF_UP"
    HALF_EVEN = "HALF_EVEN"


class RoundOffMethod(StrEnum):
    """⚙ ``invoicing.round_off_method``."""

    NEAREST = "NEAREST"  # half-up
    UP = "UP"
    DOWN = "DOWN"


_COMPONENT_MODES = {
    ComponentRounding.HALF_UP: ROUND_HALF_UP,
    ComponentRounding.HALF_EVEN: ROUND_HALF_EVEN,
}
_RUPEE_MODES = {
    RoundOffMethod.NEAREST: ROUND_HALF_UP,
    RoundOffMethod.UP: ROUND_CEILING,
    RoundOffMethod.DOWN: ROUND_FLOOR,
}


def round2(value: Decimal, rounding: ComponentRounding = ComponentRounding.HALF_UP) -> Decimal:
    """Round to the paisa."""
    return value.quantize(PAISA, _COMPONENT_MODES[rounding])


@dataclass(frozen=True)
class Discount:
    """``value`` is a percentage (0 < value ≤ 100) or rupees off per unit."""

    type: DiscountType
    value: Decimal


@dataclass(frozen=True)
class LineTax:
    gross: Decimal  # qty * unit price, as entered (inclusive or exclusive of GST)
    discount: Decimal  # on the same basis as ``gross``
    gross_excl: Decimal  # exclusive of GST (equals gross when prices exclude GST)
    discount_excl: Decimal
    taxable: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal
    line_total: Decimal
    cgst_rate: Decimal
    sgst_rate: Decimal
    igst_rate: Decimal
    cess_rate: Decimal

    @property
    def tax(self) -> Decimal:
        return self.cgst + self.sgst + self.igst + self.cess


def line_gross(qty: Decimal, unit_price: Decimal, rounding: ComponentRounding) -> Decimal:
    return round2(qty * unit_price, rounding)


def line_discount(
    gross: Decimal, qty: Decimal, discount: Discount | None, rounding: ComponentRounding
) -> Decimal:
    """PLAN M1/M2: percentage of the line gross; flat is per unit and never exceeds the gross."""
    if discount is None:
        return ZERO
    if discount.type == DiscountType.PERCENT:
        return round2(gross * discount.value / HUNDRED, rounding)
    return min(round2(qty * discount.value, rounding), gross)


RUPEE = Decimal("1")


def adjust_price(price: Decimal, percent: Decimal, *, whole_rupees: bool = False) -> Decimal:
    """``price`` changed by ``percent`` (e.g. 5 or -2.5), rounded half-up to the paisa or to whole
    rupees (bulk price-list changes, ADR-037). Never below zero."""
    changed = price * (HUNDRED + percent) / HUNDRED
    step = RUPEE if whole_rupees else PAISA
    return max(changed.quantize(step, ROUND_HALF_UP), Decimal("0")).quantize(PAISA)


def percent_of(part: Decimal, whole: Decimal, rounding: ComponentRounding) -> Decimal:
    """``part`` as a percentage of ``whole`` to two decimals (a discount shown to shops)."""
    if whole <= 0:
        return Decimal("0.00")
    return round2(part * HUNDRED / whole, rounding)


# --- Stock cost (ADR-041): per-unit costs before GST ------------------------------------------

UNIT_COST_STEP = Decimal("0.0001")


def cost_per_base_unit(entered_cost: Decimal, base_units_per_entered_unit: Decimal) -> Decimal:
    """Cost of one base unit from the cost of one entered unit (a pack holds several base units),
    to 4 decimals, half-up. ``cost_per_base_unit(Decimal("100"), Decimal("12"))`` is 8.3333."""
    if base_units_per_entered_unit <= 0:
        raise ValueError("a pack holds more than zero base units")
    return (entered_cost / base_units_per_entered_unit).quantize(UNIT_COST_STEP, ROUND_HALF_UP)


def stock_value(qty: Decimal, unit_cost: Decimal) -> Decimal:
    """Value of ``qty`` at ``unit_cost``, half-up to the paisa (movements, receipts, valuation)."""
    return round2(qty * unit_cost)


def weighted_average_cost(
    on_hand: Decimal, cost_price: Decimal | None, received: Decimal, unit_cost: Decimal
) -> Decimal:
    """New cost price after receiving ``received`` units at ``unit_cost`` (⚙ ``stock.cost_method``
    WEIGHTED_AVERAGE), half-up to the paisa. With no stock (0 or less) or no cost price yet, the
    bill cost becomes the cost price."""
    if received <= 0:
        raise ValueError("received quantity must be above zero")
    if on_hand <= 0 or cost_price is None:
        return round2(unit_cost)
    return round2((on_hand * cost_price + received * unit_cost) / (on_hand + received))


def compute_line(
    *,
    qty: Decimal,
    unit_price: Decimal,
    rate: Decimal,
    supply_type: SupplyType,
    discount: Discount | None = None,
    discount_amount: Decimal | None = None,
    cess_rate: Decimal = ZERO,
    inclusive: bool = False,
    rounding: ComponentRounding = ComponentRounding.HALF_UP,
) -> LineTax:
    """One invoice/order line (PLAN §6.2). Each component is rounded independently to paise."""
    gross = line_gross(qty, unit_price, rounding)
    if discount is not None and discount_amount is not None:
        raise ValueError("pass either a discount rule or a discount amount, not both")
    # ``discount_amount``: already worked out for the line by pricing (several rules combined,
    # ADR-038), on the same price basis as ``unit_price``; never more than the gross.
    disc = (
        min(round2(discount_amount, rounding), gross)
        if discount_amount is not None
        else line_discount(gross, qty, discount, rounding)
    )
    if inclusive:
        # Back the tax out at line level; the discount column is derived so the columns
        # reconcile (a ±0.01 line tolerance is absorbed by the document round-off, PLAN M6).
        divisor = HUNDRED + rate + cess_rate
        taxable = round2((gross - disc) * HUNDRED / divisor, rounding)
        gross_excl = round2(gross * HUNDRED / divisor, rounding)
        disc_excl = gross_excl - taxable
    else:
        taxable = gross - disc
        gross_excl, disc_excl = gross, disc
    if supply_type == SupplyType.INTRA:
        half = rate / 2
        cgst = sgst = round2(taxable * half / HUNDRED, rounding)
        igst = ZERO
        cgst_rate = sgst_rate = half
        igst_rate = Decimal("0")
    else:
        cgst = sgst = ZERO
        igst = round2(taxable * rate / HUNDRED, rounding)
        cgst_rate = sgst_rate = Decimal("0")
        igst_rate = rate
    cess = round2(taxable * cess_rate / HUNDRED, rounding)
    return LineTax(
        gross=gross,
        discount=disc,
        gross_excl=gross_excl,
        discount_excl=disc_excl,
        taxable=taxable,
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        cess=cess,
        line_total=taxable + cgst + sgst + igst + cess,
        cgst_rate=cgst_rate,
        sgst_rate=sgst_rate,
        igst_rate=igst_rate,
        cess_rate=cess_rate,
    )


@dataclass(frozen=True)
class DocumentTotals:
    taxable: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal
    lines_total: Decimal
    round_off: Decimal
    grand_total: Decimal


def compute_document(
    lines: list[LineTax],
    *,
    round_to_rupee: bool = True,
    round_off_method: RoundOffMethod = RoundOffMethod.NEAREST,
) -> DocumentTotals:
    """Totals are sums of the line components, never recomputed; the grand total reconciles to
    the paisa: ``grand_total = lines_total + round_off``."""
    lines_total = sum((line.line_total for line in lines), ZERO)
    if round_to_rupee:
        grand = lines_total.quantize(RUPEE, _RUPEE_MODES[round_off_method]).quantize(PAISA)
    else:
        grand = lines_total
    return DocumentTotals(
        taxable=sum((line.taxable for line in lines), ZERO),
        cgst=sum((line.cgst for line in lines), ZERO),
        sgst=sum((line.sgst for line in lines), ZERO),
        igst=sum((line.igst for line in lines), ZERO),
        cess=sum((line.cess for line in lines), ZERO),
        lines_total=lines_total,
        round_off=grand - lines_total,
        grand_total=grand,
    )


# --- Documents: words, HSN summary, dates (PLAN §6.1, §6.4) --------------------------------------

_ONES = [
    "Zero",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
]
_TENS = ["_", "_", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")


def _below_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = [f"{_ONES[hundreds]} Hundred"] if hundreds else []
    if rest:
        parts.append(_below_hundred(rest))
    return " ".join(parts)


def _indian_words(n: int) -> str:
    """Whole rupees in the Indian system: crore, lakh, thousand, hundred."""
    if n == 0:
        return "Zero"
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    parts = []
    if crore:
        parts.append(f"{_indian_words(crore)} Crore")
    if lakh:
        parts.append(f"{_below_hundred(lakh)} Lakh")
    if thousand:
        parts.append(f"{_below_hundred(thousand)} Thousand")
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def amount_in_words(amount: Decimal) -> str:
    """ "Rupees One Thousand Four Hundred Fifty Seven Only"; paise when there are any:
    "Rupees One Crore ... and Ninety Paise Only". Printed on invoices (Indian system)."""
    if amount < 0:
        raise ValueError("amounts in words are for amounts of zero or more")
    paise_total = int(amount.quantize(PAISA) * 100)
    rupees, paise = divmod(paise_total, 100)
    words = f"Rupees {_indian_words(rupees)}"
    if paise:
        words += f" and {_below_hundred(paise)} Paise"
    return f"{words} Only"


@dataclass(frozen=True)
class HsnRow:
    hsn: str
    rate: Decimal  # the GST rate (CGST + SGST, or IGST)
    taxable: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal

    @property
    def tax(self) -> Decimal:
        return self.cgst + self.sgst + self.igst + self.cess


def hsn_summary(lines: list[tuple[str, Decimal, LineTax]]) -> list[HsnRow]:
    """The invoice's HSN-wise summary: line components summed by (HSN, rate), never recomputed
    (PLAN §6.1). ``lines`` are (hsn code, GST rate, line tax)."""
    groups: dict[tuple[str, Decimal], list[LineTax]] = {}
    for hsn, rate, line in lines:
        groups.setdefault((hsn, rate), []).append(line)
    return [
        HsnRow(
            hsn=hsn,
            rate=rate,
            taxable=sum((x.taxable for x in group), ZERO),
            cgst=sum((x.cgst for x in group), ZERO),
            sgst=sum((x.sgst for x in group), ZERO),
            igst=sum((x.igst for x in group), ZERO),
            cess=sum((x.cess for x in group), ZERO),
        )
        for (hsn, rate), group in sorted(groups.items())
    ]


def financial_year(day: date) -> str:
    """Indian financial year (April to March) of an IST date: 2026-09-28 → "2026-27"."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def fy_short(fy: str) -> str:
    """ "2026-27" → "26-27" (the part printed in document numbers)."""
    return fy[2:]


def due_date(invoice_date: date, terms_days: int) -> date:
    """Invoice date plus the shop's payment terms (ADR-046)."""
    return invoice_date + timedelta(days=terms_days)


# --- Credit notes: proration without drift (PLAN §6.5) --------------------------------------------


@dataclass(frozen=True)
class Components:
    """The money parts of an invoice line (or what is left of it after earlier credit notes)."""

    taxable: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal

    @property
    def total(self) -> Decimal:
        return self.taxable + self.cgst + self.sgst + self.igst + self.cess

    def minus(self, other: "Components") -> "Components":
        return Components(
            taxable=self.taxable - other.taxable,
            cgst=self.cgst - other.cgst,
            sgst=self.sgst - other.sgst,
            igst=self.igst - other.igst,
            cess=self.cess - other.cess,
        )

    @classmethod
    def of(cls, line: LineTax) -> "Components":
        return cls(line.taxable, line.cgst, line.sgst, line.igst, line.cess)


def credit_for_taxable(
    taxable: Decimal,
    *,
    rates: LineTax,
    remaining: Components,
    rounding: ComponentRounding = ComponentRounding.HALF_UP,
) -> Components:
    """Credit ``taxable`` (before tax) against an invoice line: taxes at the invoice line's rates
    (``rates``: the original line's rate fields). A credit that reaches what is left of the line
    takes exactly the remainder of every component, so the line is reversed with no paisa left."""
    if taxable <= 0:
        raise ValueError("a credit needs a taxable value above zero")
    if taxable >= remaining.taxable:
        return remaining

    def tax(rate: Decimal, left: Decimal) -> Decimal:
        return min(round2(taxable * rate / HUNDRED, rounding), left)

    return Components(
        taxable=taxable,
        cgst=tax(rates.cgst_rate, remaining.cgst),
        sgst=tax(rates.sgst_rate, remaining.sgst),
        igst=tax(rates.igst_rate, remaining.igst),
        cess=tax(rates.cess_rate, remaining.cess),
    )


def credit_for_quantity(
    qty: Decimal,
    *,
    invoiced_qty: Decimal,
    remaining_qty: Decimal,
    line: LineTax,
    remaining: Components,
    rounding: ComponentRounding = ComponentRounding.HALF_UP,
) -> Components:
    """Credit ``qty`` of an invoice line: the same share of its taxable value, taxes at its rates;
    the credit that uses up the line's quantity takes exactly what is left (PLAN §6.5)."""
    if qty <= 0 or qty > remaining_qty:
        raise ValueError("credit between zero and the quantity not yet credited")
    if qty == remaining_qty:
        return remaining
    taxable = round2(line.taxable * qty / invoiced_qty, rounding)
    if taxable <= 0:  # a share worth less than a paisa: nothing yet; the last return takes it
        return Components(ZERO, ZERO, ZERO, ZERO, ZERO)
    return credit_for_taxable(taxable, rates=line, remaining=remaining, rounding=rounding)


def credit_note_totals(
    lines: list[Components],
    *,
    round_to_rupee: bool,
    round_off_method: RoundOffMethod,
    invoice_left: Decimal | None = None,
) -> DocumentTotals:
    """A credit note's totals, rounded like an invoice. When it uses up the whole invoice
    (``invoice_left`` = invoice grand total - earlier credit notes' grand totals), its grand
    total is exactly that amount, so the invoice's balance lands on zero (PLAN §6.5)."""
    lines_total = sum((x.total for x in lines), ZERO)
    if invoice_left is not None:
        grand = invoice_left
    elif round_to_rupee:
        grand = lines_total.quantize(RUPEE, _RUPEE_MODES[round_off_method]).quantize(PAISA)
    else:
        grand = lines_total
    return DocumentTotals(
        taxable=sum((x.taxable for x in lines), ZERO),
        cgst=sum((x.cgst for x in lines), ZERO),
        sgst=sum((x.sgst for x in lines), ZERO),
        igst=sum((x.igst for x in lines), ZERO),
        cess=sum((x.cess for x in lines), ZERO),
        lines_total=lines_total,
        round_off=grand - lines_total,
        grand_total=grand,
    )
