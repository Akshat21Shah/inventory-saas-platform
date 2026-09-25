"""Decimal helpers for money and quantities.

These helpers only quantize. Business rounding *policy* (tax components, round-off to the rupee)
lives exclusively in ``apps/billing/tax.py`` (CLAUDE.md §4, ADR-009).
"""

from decimal import ROUND_HALF_UP, Decimal

MONEY_QUANTUM = Decimal("0.01")
QTY_QUANTUM = Decimal("0.001")
RATE_QUANTUM = Decimal("0.001")
ZERO = Decimal("0")


def to_decimal(value: Decimal | int | str) -> Decimal:
    """Convert to Decimal, refusing floats so binary rounding errors never enter money math."""
    if isinstance(value, (bool, float)):
        raise TypeError(
            f"Refusing to convert {type(value).__name__} to Decimal; use str or Decimal"
        )
    return value if isinstance(value, Decimal) else Decimal(value)


def quantize_money(value: Decimal | int | str, rounding: str = ROUND_HALF_UP) -> Decimal:
    return to_decimal(value).quantize(MONEY_QUANTUM, rounding=rounding)


def quantize_qty(value: Decimal | int | str, rounding: str = ROUND_HALF_UP) -> Decimal:
    return to_decimal(value).quantize(QTY_QUANTUM, rounding=rounding)
