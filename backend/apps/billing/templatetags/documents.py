"""Formatting for printed documents: Indian digit grouping, quantities, rates, dates, and the
labels in English and the document's language (ADR-060)."""

from datetime import date
from decimal import Decimal
from typing import Any

from django import template
from django.utils import translation
from django.utils.functional import Promise
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import SafeString, mark_safe

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


def _both(english: str, other: str) -> SafeString:
    """ "English / अनुवाद" (English only when the two are the same). Both are escaped."""
    if not other or other == english:
        return conditional_escape(english)
    return format_html('{} <span class="tr">/ {}</span>', english, other)


_lookup = translation.gettext  # labels are listed in labels.py; looked up when printed


def _fill(text: str, values: dict[str, Any], bold: str) -> SafeString:
    """``text`` with its values, everything escaped; the value named ``bold`` in bold."""
    safe = {key: conditional_escape(value) for key, value in values.items()}
    if bold in safe:
        safe[bold] = format_html("<b>{}</b>", safe[bold])
    # Escaped text with escaped values: safe to mark so.
    return mark_safe(conditional_escape(text) % safe)  # noqa: S308


@register.simple_tag(takes_context=True)
def t(context: Any, english: str, bold: str = "", **values: Any) -> SafeString:
    """A label in English, then in the document's language (``lang``): ``{% t "Tax invoice" %}``
    or with values ``{% t "For %(name)s" name=seller.legal_name bold="name" %}``. Every label
    is listed in ``apps/billing/labels.py``."""
    lang = context.get("lang") or "en"
    first = _fill(english, values, bold)
    if lang == "en":
        return first
    with translation.override(lang):
        other = _lookup(english)  # a label listed in labels.py, looked up at print time
    return _both(first, _fill(other, values, bold))


@register.simple_tag(takes_context=True)
def tl(context: Any, label: Any) -> SafeString:
    """A model choice's label (a payment mode, a credit note's kind) in both languages."""
    lang = context.get("lang") or "en"
    with translation.override("en"):
        english = str(label)
    if lang == "en":
        return conditional_escape(english)
    with translation.override(lang):
        other = str(label) if isinstance(label, Promise) else _lookup(english)
    return _both(english, other)
