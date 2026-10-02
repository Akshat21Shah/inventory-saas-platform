"""Formatting for printed documents: Indian digit grouping, quantities, rates, dates."""

from datetime import date
from decimal import Decimal
from typing import Any

from django import template

register = template.Library()


def _group_indian(digits: str) -> str:
    """12345678 -> 1,23,45,678."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    pairs: list[str] = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return ",".join(pairs) + "," + tail


@register.filter
def amount(value: Any) -> str:
    """1234567.5 -> 12,34,567.50 (no rupee sign: column headings carry it)."""
    if value in (None, ""):
        return ""
    number = Decimal(str(value)).quantize(Decimal("0.01"))
    sign = "-" if number < 0 else ""
    whole, _, paise = f"{abs(number):.2f}".partition(".")
    return f"{sign}{_group_indian(whole)}.{paise}"


@register.filter
def indian_number(value: Any) -> str:
    """1234567 -> 12,34,567 (whole numbers: counts)."""
    if value in (None, ""):
        return ""
    number = int(value)
    return f"{'-' if number < 0 else ''}{_group_indian(str(abs(number)))}"


@register.filter
def rupees(value: Any) -> str:
    text = amount(value)
    if text.startswith("-"):
        return f"-₹{text[1:]}"
    return f"₹{text}" if text else ""


@register.filter
def qty(value: Any) -> str:
    """12.500 -> 12.5, 8.000 -> 8."""
    if value in (None, ""):
        return ""
    text = f"{Decimal(str(value)).normalize():f}"
    return text


@register.filter
def rate(value: Any) -> str:
    """9.000 -> 9%, 2.500 -> 2.5%."""
    return f"{qty(value)}%" if value not in (None, "") else ""


@register.filter
def day(value: Any) -> str:
    """28-09-2026."""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return value.strftime("%d-%m-%Y") if value else ""
