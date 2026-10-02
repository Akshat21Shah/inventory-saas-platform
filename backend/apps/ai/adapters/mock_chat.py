"""The scripted mock assistant (ADR-059 item 4): local, deterministic and free, for dev, tests,
CI and the evaluation set. It picks one tool from the question's words (and a period, a number of
rows or days, or a product), then writes a short answer from the tool's figures with a template.

It answers in the question's language (ADR-060 item 9): English, or for a question in Devanagari
the language whose own words it uses most (Hindi or Marathi). Each language's question words and
answer templates are data, ``apps/ai/assistant/words/<code>.json``; a new language adds its file.
A question's words are tried in its language first, then in English ("आज की sales कितनी है?").
A real model understands far more.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

from apps.ai.adapters.chat import ChatTurn, Message, ToolCall, ToolSpec

MODEL = "mock-scripted-1"
WORDS_DIR = Path(__file__).resolve().parent.parent / "assistant" / "words"

# The first match wins, so the more specific come first.
TOOL_ORDER = (
    "shops_not_ordering",
    "backorders",
    "low_stock",
    "product_stock",
    "dues",
    "collections",
    "sales_by_salesperson",
    "sales_by_category",
    "top_shops",
    "top_products",
    "sales_summary",
)
PERIOD_ORDER = (
    "today",
    "yesterday",
    "last_week",
    "this_week",
    "last_7_days",
    "last_30_days",
    "last_90_days",
    "last_month",
    "this_month",
    "last_quarter",
    "this_quarter",
    "last_financial_year",
    "this_financial_year",
)
WITH_PERIOD = (
    "sales_summary",
    "top_products",
    "sales_by_category",
    "top_shops",
    "sales_by_salesperson",
    "collections",
)
# What each tool lets the person ask about, in the order the fallback reply lists them.
TOPIC_ORDER = (
    "sales_summary",
    "top_products",
    "top_shops",
    "shops_not_ordering",
    "low_stock",
    "product_stock",
    "backorders",
    "dues",
    "collections",
)
_SCRIPT = re.compile(r"[ऀ-෿]")  # Devanagari and the other Indian scripts
_WORD = re.compile(r"[\wऀ-ॣ०-෿]+")


@dataclass(frozen=True)
class Words:
    """One language's question words (regular expressions) and answer templates."""

    code: str
    markers: frozenset[str]  # its own common words, to tell it from others in the same script
    tools: tuple[tuple[str, re.Pattern[str]], ...]
    periods: tuple[tuple[str, re.Pattern[str]], ...]
    top: re.Pattern[str]
    days: re.Pattern[str]
    overdue: re.Pattern[str]
    product: re.Pattern[str]
    costs: re.Pattern[str]
    when: dict[str, str]
    topics: dict[str, str]
    examples: dict[str, str]
    say: dict[str, Any]

    def text(self, key: str, count: int | None = None, **values: Any) -> str:
        template = self.say[key]
        if isinstance(template, dict):
            template = template["one" if count == 1 else "other"]
        return str(template).format(count=count, **values)


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


@cache
def words(code: str) -> Words:
    """A language's words; English for a language without its own file."""
    path = WORDS_DIR / f"{code}.json"
    if not path.exists():
        return words("en")
    data = json.loads(path.read_text("utf-8"))
    return Words(
        code,
        frozenset(data["markers"]),
        tuple((tool, _compile(data["tools"][tool])) for tool in TOOL_ORDER),
        tuple((period, _compile(data["periods"][period])) for period in PERIOD_ORDER),
        _compile(data["top"]),
        _compile(data["days"]),
        _compile(data["overdue"]),
        _compile(data["product"]),
        _compile(data["costs"]),
        data["when"],
        data["topics"],
        data["examples"],
        data["say"],
    )


@cache
def languages() -> tuple[str, ...]:
    """The languages with words, English first, then by code."""
    found = sorted(path.stem for path in WORDS_DIR.glob("*.json"))
    return ("en", *(code for code in found if code != "en"))


def language_of(question: str) -> str:
    """English, unless the question is written in an Indian script: then the language whose own
    words it uses most (the first in code order on a tie)."""
    if not _SCRIPT.search(question):
        return "en"
    used = set(_WORD.findall(question.lower()))
    others = [code for code in languages() if code != "en"]
    return max(others, key=lambda code: len(used & words(code).markers)) if others else "en"


def _tried(lang: str) -> tuple[Words, ...]:
    """The question's language first, then English."""
    return (words(lang),) if lang == "en" else (words(lang), words("en"))


def rupees(value: Any) -> str:
    """'123456.5' → '₹1,23,456.50' (Indian grouping, digits 0-9 in every language)."""
    number = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    sign = "-" if number < 0 else ""
    whole, _, paise = f"{abs(number):.2f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}₹{','.join([*groups, tail]) if groups else tail}.{paise}"


def quantity(value: Any) -> str:
    return f"{Decimal(str(value or 0)).normalize():f}"


def _period(question: str, lang: str) -> str | None:
    for language in _tried(lang):
        for period, pattern in language.periods:
            if pattern.search(question):
                return period
    return None


def _number(question: str, patterns: list[re.Pattern[str]]) -> int | None:
    for pattern in patterns:
        found = pattern.search(question)
        if found:
            return int(found.group(1))
    return None


def _product(question: str, lang: str) -> str | None:
    for language in _tried(lang):
        found = language.product.search(question.strip())
        if found:
            return found.group("name").strip(" ?.।")
    return None


def plan(question: str, offered: set[str]) -> ToolCall | str:
    """The tool call for ``question``, or a reply (in its language) when no offered tool fits."""
    lang = language_of(question)
    say = words(lang)
    tried = _tried(lang)
    tool = next(
        (
            name
            for language in tried
            for name, pattern in language.tools
            if pattern.search(question)
        ),
        None,
    )
    if tool is None:
        return can_answer(offered, lang)
    if tool not in offered:
        return say.text("no_access")
    args: dict[str, Any] = {}
    period = _period(question, lang)
    if period and tool in WITH_PERIOD:
        args["period"] = period
    top = _number(question, [language.top for language in tried])
    if top:
        args["limit"] = min(top, 20)
    if tool == "shops_not_ordering":
        args["days"] = _number(question, [language.days for language in tried]) or 30
    if tool == "dues" and any(language.overdue.search(question) for language in tried):
        args["overdue_only"] = True
    if tool == "product_stock":
        product = _product(question, lang)
        if not product:
            return say.text("which_product")
        args["product"] = product
    return ToolCall(id=f"call_{tool}", name=tool, args=args)


def can_answer(offered: set[str], lang: str = "en") -> str:
    """The fallback reply: only the topics this person's tools cover."""
    say = words(lang)
    topics = [say.topics[tool] for tool in TOPIC_ORDER if tool in offered]
    if not topics:
        return say.text("nothing_to_show")
    listed = topics[-1]
    if len(topics) > 1:
        listed = ", ".join(topics[:-1]) + say.text("and") + listed
    example = next(
        (say.examples[tool] for tool in ("shops_not_ordering", "low_stock") if tool in offered),
        None,
    )
    return say.text("can_answer", topics=listed) + (
        say.text("try", example=example) if example else ""
    )


_COST_COLUMNS = {"margin", "margin_pct", "cost", "cost_price", "value"}


def costs_note(question: str, figures: dict[str, Any], lang: str | None = None) -> str:
    """When the question asks for costs or margins the figures don't carry (the person may not
    see them), say so instead of answering around it."""
    lang = lang or language_of(question)
    if not any(language.costs.search(question) for language in _tried(lang)):
        return ""
    if _COST_COLUMNS & set((figures.get("columns") or {}).keys()):
        return ""
    return words(lang).text("costs_hidden")


def _names(rows: list[dict[str, Any]], key: str = "name", n: int = 5) -> str:
    return ", ".join(str(r.get(key, "")) for r in rows[:n])


def write(tool: str, figures: dict[str, Any], args: dict[str, Any], lang: str = "en") -> str:
    """A short answer from a tool's figures, in ``lang``."""
    say = words(lang)
    rows: list[dict[str, Any]] = figures.get("rows") or []
    totals: dict[str, Any] = figures.get("totals") or {}
    found = figures.get("rows_found", len(rows))
    when = say.when.get(args.get("period", "this_month"), "")
    mine = say.text("mine") if figures.get("only_the_askers_own_shops") else ""
    if tool == "sales_summary":
        if not totals or not Decimal(str(totals.get("total") or 0)):
            return say.text("no_sales", when=when, mine=mine)
        return say.text(
            "sales",
            when=when,
            mine=mine,
            total=rupees(totals.get("total")),
            invoices=totals.get("invoices", 0),
            credited=rupees(totals.get("credited")),
        )
    if tool in ("top_products", "top_shops", "sales_by_category", "sales_by_salesperson"):
        if not rows:
            return say.text("no_sales", when=when, mine=mine)
        # Net of returns a row can be zero or less; those aren't "top" of anything.
        sold = [r for r in rows if Decimal(str(r.get("total") or 0)) > 0]
        if not sold:
            return say.text("no_sales_after_returns", when=when, mine=mine)
        lines = [
            f"{i}. {r.get('name')}: {rupees(r.get('total'))}" for i, r in enumerate(sold[:10], 1)
        ]
        head = say.text("list_head", what=say.say["lists"][tool], when=when, mine=mine)
        return head + "\n" + "\n".join(lines)
    if tool == "shops_not_ordering":
        days = args.get("days", 30)
        if not rows:
            return say.text("everyone_ordered", mine=mine, days=days)
        never = [r for r in rows if r.get("days_since") is None]
        gone = [r for r in rows if r.get("days_since") is not None]
        parts = [say.text("not_ordering", found, mine=mine, days=days)]
        if gone:
            gaps = ", ".join(
                say.text("gap", name=r.get("name"), days=r.get("days_since")) for r in gone[:5]
            )
            parts.append(say.text("longest_gaps", items=gaps))
        if never:
            parts.append(say.text("never_ordered", names=_names(never)))
        return " ".join(parts)
    if tool == "low_stock":
        if not rows:
            return say.text("nothing_low")
        items = ", ".join(
            say.text(
                "low_item",
                name=r.get("name"),
                available=quantity(r.get("available")),
                reorder=quantity(r.get("reorder_level")),
            )
            for r in rows[:5]
        )
        return say.text("low", found, items=items)
    if tool == "product_stock":
        if not rows:
            return say.text("no_product", product=args.get("product"))
        return " ".join(
            say.text(
                "stock_item",
                name=r.get("name"),
                available=quantity(r.get("available")),
                on_hand=quantity(r.get("on_hand")),
                reserved=quantity(r.get("reserved")),
            )
            for r in rows[:5]
        )
    if tool == "dues":
        owing = [r for r in rows if Decimal(str(r.get("net") or 0)) > 0]
        if not owing:
            return say.text("nobody_owes", mine=mine)
        top = ", ".join(f"{r.get('name')} {rupees(r.get('net'))}" for r in owing[:5])
        net = Decimal(str(totals.get("net") or 0))
        if net > 0:
            balance = say.text("owed_net", amount=rupees(net))
        else:  # shops hold more credit than is owed
            balance = say.text("owed_credit", amount=rupees(-net))
        return say.text("owed", mine=mine, items=top, balance=balance)
    if tool == "collections":
        if not rows:
            return say.text("no_payments", when=when, mine=mine)
        return say.text(
            "collected", found, when=when, mine=mine, amount=rupees(totals.get("amount"))
        )
    if tool == "backorders":
        if not rows:
            return say.text("no_backorders")
        items = ", ".join(
            say.text(
                "backorder_item",
                r.get("shops"),
                name=r.get("name"),
                qty=quantity(r.get("qty")),
                shops=r.get("shops"),
            )
            for r in rows[:5]
        )
        return say.text("backorders", found, items=items)
    return say.text("figures")


def _units(text: str) -> int:
    return max(1, len(text) // 4)


class ScriptedChat:
    name = "mock"

    def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        timeout: float,
    ) -> ChatTurn:
        last = messages[-1]
        sent = system + "".join(
            m.text + "".join(r.content for r in m.tool_results) for m in messages
        )
        if last.tool_results:
            call = next(c for m in reversed(messages) for c in m.tool_calls)
            result = last.tool_results[0]
            question = next(m.text for m in messages if m.role == "user" and m.text)
            lang = language_of(question)
            if result.error:
                reply = words(lang).text("couldnt_get") + json.loads(result.content).get(
                    "error", ""
                )
            else:
                figures = json.loads(result.content)
                reply = costs_note(question, figures, lang) + write(
                    call.name, figures, call.args, lang
                )
            return ChatTurn(reply, (), _units(sent), _units(reply), MODEL)
        step = plan(last.text, {t.name for t in tools})
        if isinstance(step, str):
            return ChatTurn(step, (), _units(sent), _units(step), MODEL)
        return ChatTurn("", (step,), _units(sent), 10, MODEL)
