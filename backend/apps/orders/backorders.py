"""Backorder allocation (spec 5.9, PLAN §4.3, §5.2, ADR-014/021). Filled in by the backorder
commit; order services already call these hooks wherever stock is freed."""

from collections.abc import Iterable
from uuid import UUID


def after_stock_released(product_ids: Iterable[UUID]) -> None:
    """Stock released by a reject, cancel, short pack or cancelled shipment may serve older
    backorders: allocation runs for these products after the transaction commits."""
