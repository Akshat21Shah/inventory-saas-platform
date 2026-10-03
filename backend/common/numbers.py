"""The one formatter for numbers people read (ADR-060 item 4, owner): Indian digit grouping and the
digits 0-9 in every language (6,029; 1,23,456; 12,34,567.50), in server messages, notifications
and documents. Every number inside a message goes through it: ``fill`` groups the numbers among a
message's values before filling it in, and a test fails on a translated message filled any other
way. The web has the same rule (``web/lib/format.ts``)."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any


def _group(digits: str) -> str:
    """ "12345678" -> "1,23,45,678": the last three digits, then pairs."""
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


def is_number(value: Any) -> bool:
    return isinstance(value, int | Decimal | float) and not isinstance(value, bool)


def grouped(value: int | Decimal | float | str, places: int | None = None) -> str:
    """6029 -> "6,029"; Decimal("1234.500") -> "1,234.5" (no trailing zeros); with ``places`` that
    many decimals: grouped(Decimal("1234.5"), 2) -> "1,234.50"."""
    number = Decimal(str(value))
    if places is not None:
        number = number.quantize(Decimal(1).scaleb(-places))
        text = f"{abs(number):f}"
    else:
        text = f"{abs(number).normalize():f}"
    whole, dot, fraction = text.partition(".")
    sign = "-" if number < 0 else ""
    return f"{sign}{_group(whole)}{dot}{fraction}"


def rupees(value: int | Decimal | float | str) -> str:
    """ "123456.5" -> "₹1,23,456.50"; negative: "-₹950.00"."""
    text = grouped(value, 2)
    return f"-₹{text[1:]}" if text.startswith("-") else f"₹{text}"


def fill(message: Any, values: Mapping[str, Any]) -> str:
    """A translated ``message`` with its ``%(name)s`` values filled in, every number grouped:
    fill(_("%(count)s rows checked"), {"count": 6029}) -> "6,029 rows checked"."""
    return str(message) % {k: grouped(v) if is_number(v) else v for k, v in values.items()}
