"""Formatting for printed documents: Indian digit grouping (the shared formatter,
``common/numbers.py``), quantities, rates, dates, and the labels in English and the document's
language (ADR-060)."""

from datetime import date
from typing import Any

from django import template
from django.utils import translation
from django.utils.functional import Promise
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import SafeString, mark_safe

from common import numbers

register = template.Library()


@register.filter
def amount(value: Any) -> str:
    """1234567.5 -> 12,34,567.50 (no rupee sign: column headings carry it)."""
    return "" if value in (None, "") else numbers.grouped(value, 2)


@register.filter
def indian_number(value: Any) -> str:
    """1234567 -> 12,34,567 (whole numbers: counts)."""
    return "" if value in (None, "") else numbers.grouped(int(value))


@register.filter
def rupees(value: Any) -> str:
    """1234567.5 -> ₹12,34,567.50."""
    return "" if value in (None, "") else numbers.rupees(value)


@register.filter
def qty(value: Any) -> str:
    """12.500 -> 12.5, 8.000 -> 8, 1234.5 -> 1,234.5."""
    return "" if value in (None, "") else numbers.grouped(value)


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
