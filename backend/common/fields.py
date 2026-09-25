"""Decimal field types with the project's fixed precision (ADR-001). Never use float for these."""

from typing import Any

from django.db import models


class _PresetDecimalField(models.DecimalField):  # type: ignore[type-arg]
    MAX_DIGITS = 14
    DECIMAL_PLACES = 2

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", self.MAX_DIGITS)
        kwargs.setdefault("decimal_places", self.DECIMAL_PLACES)
        super().__init__(*args, **kwargs)


class MoneyField(_PresetDecimalField):
    """Monetary amount in INR: Decimal(14, 2)."""


class QtyField(_PresetDecimalField):
    """Stock / order quantity: Decimal(14, 3)."""

    DECIMAL_PLACES = 3


class RateField(_PresetDecimalField):
    """Percentage rate such as GST (18.000) or half of 0.25% (0.125): Decimal(6, 3)."""

    MAX_DIGITS = 6
    DECIMAL_PLACES = 3


class UnitCostField(_PresetDecimalField):
    """Per-unit / weighted-average cost only: Decimal(14, 4). Totals remain MoneyField."""

    DECIMAL_PLACES = 4
