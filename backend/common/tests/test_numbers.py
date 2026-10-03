"""Numbers people read (ADR-060 item 4, owner at the 11a final review): one formatter, Indian
grouping and the digits 0-9 in every language (6,029; 1,23,456), for every number inside a message:
server messages (``fill``), notifications (``substitute``) and documents (the template filters).
The source checks fail on a translated message filled any other way, or a number turned into text
on its own before it reaches ``fill``."""

import ast
from decimal import Decimal
from pathlib import Path

import pytest
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.billing.templatetags import documents
from apps.notifications.render import substitute
from common.numbers import fill, grouped, rupees

BACKEND = Path(__file__).resolve().parents[2]
TRANSLATED = {
    "_",
    "gettext",
    "gettext_lazy",
    "ngettext",
    "ngettext_lazy",
    "pgettext",
    "pgettext_lazy",
    "npgettext",
    "npgettext_lazy",
}


@pytest.mark.parametrize(
    ("value", "places", "shown"),
    [
        (6029, None, "6,029"),
        (123456, None, "1,23,456"),
        (12345678, None, "1,23,45,678"),
        (999, None, "999"),
        (0, None, "0"),
        (-1234567, None, "-12,34,567"),
        (Decimal("1234.500"), None, "1,234.5"),
        (Decimal("100.000"), None, "100"),
        (Decimal("1234567.5"), 2, "12,34,567.50"),
        ("98765.4", 2, "98,765.40"),
    ],
)
def test_one_formatter_with_indian_grouping(value, places, shown):
    assert grouped(value, places) == shown


def test_money_and_every_language_alike():
    assert rupees("123456.5") == "₹1,23,456.50"
    assert rupees(Decimal("-950")) == "-₹950.00"
    for language in ("en", "hi", "mr"):
        with translation.override(language):
            assert grouped(6029) == "6,029"  # digits 0-9 and the same grouping everywhere


@pytest.mark.parametrize("language", ["en", "hi", "mr"])
def test_messages_group_their_numbers_in_every_language(language):
    with translation.override(language):
        filled = fill(
            ngettext("%(count)s new shop", "%(count)s new shops", 123456), {"count": 123456}
        )
        assert "1,23,456" in filled and "123456" not in filled
        text = fill(_("%(count)s rows were imported."), {"count": 6029})
        assert "6,029" in text
    # Text is left as it is: codes, numbers of documents, names.
    assert fill("%(code)s / %(name)s", {"code": "411001", "name": "Ganesh"}) == "411001 / Ganesh"


def test_notifications_and_documents_group_their_numbers():
    assert substitute("{{ count }} orders, {{ shop }}", {"count": 6029, "shop": "Ganesh"}) == (
        "6,029 orders, Ganesh"
    )
    assert documents.qty(Decimal("123456.500")) == "1,23,456.5"
    assert documents.amount("1234567.5") == "12,34,567.50"
    assert documents.indian_number(6029) == "6,029"
    assert documents.rupees(Decimal("123456")) == "₹1,23,456.00"


def _sources() -> list[Path]:
    found = []
    for folder in ("apps", "common", "config"):
        for path in (BACKEND / folder).rglob("*.py"):
            parts = set(path.parts)
            if not parts & {"tests", "migrations", "testing"}:
                found.append(path)
    return found


def _is_translated(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in TRANSLATED
    )


def test_translated_messages_are_filled_only_through_fill():
    """``_("…") % {...}`` would print numbers without grouping: use ``fill`` (common/numbers)."""
    wrong = []
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            filled_with_percent = (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Mod)
                and _is_translated(node.left)
            )
            filled_with_format = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"
                and _is_translated(node.func.value)
            )
            if filled_with_percent or filled_with_format:
                wrong.append(f"{path.relative_to(BACKEND)}:{node.lineno}")
    assert wrong == [], "fill a translated message with common.numbers.fill"


def test_numbers_reach_fill_as_numbers():
    """A number turned into text first (f"{qty:f}", f"{n:,}") skips the grouping."""
    wrong = []
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "fill"
                and len(node.args) == 2
                and isinstance(node.args[1], ast.Dict)
            ):
                continue
            for value in node.args[1].values:
                formatted = isinstance(value, ast.JoinedStr) and any(
                    isinstance(part, ast.FormattedValue) and part.format_spec is not None
                    for part in value.values
                )
                if formatted:
                    wrong.append(f"{path.relative_to(BACKEND)}:{value.lineno}")
    assert wrong == []
